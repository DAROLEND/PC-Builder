from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone

from apps.catalog.models import Component
from apps.orders.models import InvalidTransition, Order, OrderStatus
from apps.orders.services import change_status
from apps.orders.tasks import expire_unpaid_orders
from tests.factories import make_build

pytestmark = pytest.mark.django_db


@pytest.fixture
def complete_build(user, budget_gaming_ids):
    return make_build(user, list(Component.objects.filter(id__in=budget_gaming_ids)), name="ok")


def create_order(client, build):
    return client.post(
        "/api/orders/", {"build": build.id, "shipping_address": "Kyiv, Khreshchatyk 1"}
    )


def test_order_snapshots_prices(auth_api, complete_build):
    expected_total = complete_build.compute_total()
    resp = create_order(auth_api, complete_build)
    assert resp.status_code == 201, resp.data
    order = Order.objects.get(pk=resp.data["id"])
    assert order.status == OrderStatus.PENDING
    assert order.total == expected_total

    # A later price change does not touch the order.
    Component.objects.update(price=Decimal("1.00"))
    order.refresh_from_db()
    assert order.total == expected_total
    assert sum(i.line_total for i in order.items.all()) == expected_total


def test_incomplete_build_cannot_be_ordered(auth_api, user, comp):
    draft = make_build(user, [comp("Ryzen 5 7600")], name="draft")
    resp = create_order(auth_api, draft)
    assert resp.status_code == 400
    assert "missing" in str(resp.data["build"])


def test_cannot_order_someone_elses_private_build(auth_api, other_user, comp):
    private = make_build(other_user, [comp("Ryzen 5 7600")], is_public=False)
    assert create_order(auth_api, private).status_code == 400


def test_pay_with_fake_provider(auth_api, complete_build):
    order_id = create_order(auth_api, complete_build).data["id"]
    resp = auth_api.post(f"/api/orders/{order_id}/pay/")
    assert resp.status_code == 200
    assert resp.data["confirmed"] is True
    assert resp.data["order"]["status"] == "paid"
    assert resp.data["order"]["paid_at"] is not None
    # Paying twice is not allowed.
    assert auth_api.post(f"/api/orders/{order_id}/pay/").status_code == 400


def test_status_machine(auth_api, complete_build):
    order_id = create_order(auth_api, complete_build).data["id"]
    with pytest.raises(InvalidTransition):
        change_status(order_id, OrderStatus.SHIPPED)  # must be paid first
    change_status(order_id, OrderStatus.PAID)
    change_status(order_id, OrderStatus.SHIPPED)
    change_status(order_id, OrderStatus.DELIVERED)
    with pytest.raises(InvalidTransition):
        change_status(order_id, OrderStatus.CANCELLED)


def test_change_status_is_idempotent(auth_api, complete_build):
    order_id = create_order(auth_api, complete_build).data["id"]
    change_status(order_id, OrderStatus.PAID)
    paid_at = Order.objects.get(pk=order_id).paid_at
    change_status(order_id, OrderStatus.PAID)  # duplicate webhook
    assert Order.objects.get(pk=order_id).paid_at == paid_at


def test_only_staff_can_advance(api, user, complete_build):
    api.force_authenticate(user)
    order_id = create_order(api, complete_build).data["id"]
    api.post(f"/api/orders/{order_id}/pay/")
    assert api.post(f"/api/orders/{order_id}/advance/", {"status": "shipped"}).status_code == 403

    user.is_staff = True
    user.save()
    resp = api.post(f"/api/orders/{order_id}/advance/", {"status": "shipped"})
    assert resp.status_code == 200
    assert resp.data["status"] == "shipped"
    # Shipped orders can no longer be cancelled.
    assert api.post(f"/api/orders/{order_id}/cancel/").status_code == 400


def test_users_see_only_their_orders(api, user, other_user, complete_build):
    api.force_authenticate(user)
    order_id = create_order(api, complete_build).data["id"]
    api.force_authenticate(other_user)
    assert api.get(f"/api/orders/{order_id}/").status_code == 404
    assert api.get("/api/orders/").data["count"] == 0


def test_expiry_cancels_only_stale_pending_orders(auth_api, complete_build):
    stale = create_order(auth_api, complete_build).data["id"]
    fresh = create_order(auth_api, complete_build).data["id"]
    Order.objects.filter(pk=stale).update(created_at=timezone.now() - timedelta(days=3))
    assert expire_unpaid_orders() == 1
    assert Order.objects.get(pk=stale).status == OrderStatus.CANCELLED
    assert Order.objects.get(pk=fresh).status == OrderStatus.PENDING


def test_expiry_does_not_cancel_order_paid_after_selection(auth_api, complete_build):
    """Regression: the task selects pending ids without a lock. If a webhook pays
    the order in between, the task must not cancel it (paid → cancelled is legal)."""
    order_id = create_order(auth_api, complete_build).data["id"]
    Order.objects.filter(pk=order_id).update(created_at=timezone.now() - timedelta(days=3))

    from apps.orders import services

    real_change_status = services.change_status
    calls = []

    def webhook_wins_the_race(pk, target, **kwargs):
        if not calls:
            calls.append(pk)
            real_change_status(pk, OrderStatus.PAID)  # webhook lands first
        return real_change_status(pk, target, **kwargs)

    with mock.patch.object(services, "change_status", side_effect=webhook_wins_the_race):
        assert expire_unpaid_orders() == 0
    assert Order.objects.get(pk=order_id).status == OrderStatus.PAID


def test_stripe_webhook_rejects_bad_signature(api, settings):
    settings.STRIPE_SECRET_KEY = "sk_test_dummy"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_dummy"
    resp = api.post(
        "/api/payments/stripe/webhook/", {"type": "x"}, format="json", HTTP_STRIPE_SIGNATURE="bad"
    )
    assert resp.status_code == 400


def test_stripe_webhook_marks_order_paid(api, auth_api, settings, complete_build):
    settings.STRIPE_SECRET_KEY = "sk_test_dummy"
    order_id = create_order(auth_api, complete_build).data["id"]
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"order_id": str(order_id)}, "payment_status": "paid"}},
    }
    with mock.patch("apps.orders.payments.StripeProvider.parse_webhook", return_value=event):
        resp = api.post("/api/payments/stripe/webhook/", {}, format="json")
    assert resp.status_code == 200
    assert Order.objects.get(pk=order_id).status == OrderStatus.PAID


def test_broker_outage_does_not_fail_a_committed_payment(
    auth_api, complete_build, settings, django_capture_on_commit_callbacks
):
    """Regression: with Redis down, the status e-mail could not be queued and the
    pay endpoint returned 500 although the order was already paid."""
    settings.CELERY_TASK_ALWAYS_EAGER = False
    order_id = create_order(auth_api, complete_build).data["id"]
    with (
        mock.patch(
            "apps.orders.tasks.send_order_status_email.apply_async",
            side_effect=ConnectionError("broker down"),
        ),
        django_capture_on_commit_callbacks(execute=True),
    ):
        resp = auth_api.post(f"/api/orders/{order_id}/pay/")
    assert resp.status_code == 200
    assert Order.objects.get(pk=order_id).status == OrderStatus.PAID
