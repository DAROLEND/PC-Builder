"""Order use cases.

Status changes always go through ``change_status`` which locks the row with
SELECT ... FOR UPDATE. Without the lock, a Stripe webhook marking the order
paid and the user pressing "cancel" at the same moment could both read
"pending" and both succeed.
"""

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.builds.models import Build
from config.celery import enqueue_best_effort

from .models import InvalidTransition, Order, OrderItem, OrderStatus
from .payments import PaymentSession, get_provider
from .tasks import send_order_status_email


@transaction.atomic
def create_order_from_build(*, user, build: Build, shipping_address: str) -> Order:
    lines = list(
        build.build_components.select_related("component__category", "component__manufacturer")
    )
    if not lines:
        raise ValidationError({"build": "The build is empty."})

    inactive = [str(line.component) for line in lines if not line.component.is_active]
    if inactive:
        raise ValidationError({"build": f"No longer available: {', '.join(inactive)}."})

    report = build.compatibility_report()
    if not report.is_complete:
        raise ValidationError({"build": f"The build is missing: {', '.join(report.missing)}."})
    if not report.is_compatible:
        raise ValidationError({"build": [issue.message for issue in report.errors]})

    order = Order.objects.create(
        user=user,
        build=build,
        shipping_address=shipping_address,
        total=sum(line.component.price * line.quantity for line in lines),
    )
    OrderItem.objects.bulk_create(
        OrderItem(
            order=order,
            component=line.component,
            component_name=str(line.component),
            unit_price=line.component.price,
            quantity=line.quantity,
        )
        for line in lines
    )
    return order


def change_status(order_id: int, target: str, *, expected: str | None = None) -> Order:
    """Move an order to ``target`` under a row lock.

    ``expected`` guards background jobs that decided on the transition from a
    stale read: the expiry task selects "pending" orders without a lock, and
    by the time it locks the row a webhook may have marked it paid.
    paid → cancelled is a legal transition, so without this check the job
    would cancel a paid order.
    """
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if order.status == target:
            return order  # idempotent: webhooks may be delivered more than once
        if expected is not None and order.status != expected:
            raise InvalidTransition(order.status, target)
        order.transition_to(target)
        order.save(update_fields=["status", "paid_at", "updated_at"])
        transaction.on_commit(lambda: enqueue_best_effort(send_order_status_email, order.pk))
    return order


def start_payment(order: Order) -> PaymentSession:
    if order.status != OrderStatus.PENDING:
        raise ValidationError({"status": "Only orders awaiting payment can be paid."})
    provider = get_provider()
    session = provider.create_session(order)
    Order.objects.filter(pk=order.pk).update(
        payment_provider=session.provider, payment_reference=session.reference
    )
    if session.confirmed:
        change_status(order.pk, OrderStatus.PAID)
    return session
