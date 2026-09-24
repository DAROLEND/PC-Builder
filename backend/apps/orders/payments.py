"""Payment providers.

``FakeProvider`` confirms immediately and is the default for local development
and tests. ``StripeProvider`` uses Stripe Checkout: we create a session, send
the user to Stripe, and Stripe tells us about the result via a signed webhook.
The order is marked paid only by the webhook, never by the browser redirect,
because the redirect can be forged or never happen.
"""

from dataclasses import dataclass

from django.conf import settings

from .models import Order


class PaymentError(Exception):
    pass


@dataclass
class PaymentSession:
    provider: str
    reference: str
    checkout_url: str | None  # None → already confirmed (fake provider)
    confirmed: bool


class FakeProvider:
    name = "fake"

    def create_session(self, order: Order) -> PaymentSession:
        return PaymentSession(self.name, f"fake_{order.pk}", None, confirmed=True)


class StripeProvider:
    name = "stripe"

    def __init__(self):
        import stripe

        if not settings.STRIPE_SECRET_KEY:
            raise PaymentError("STRIPE_SECRET_KEY is not configured.")
        self.stripe = stripe
        self.client = stripe.StripeClient(settings.STRIPE_SECRET_KEY)

    def create_session(self, order: Order) -> PaymentSession:
        line_items = [
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": item.component_name},
                    "unit_amount": int(item.unit_price * 100),
                },
                "quantity": item.quantity,
            }
            for item in order.items.all()
        ]
        try:
            session = self.client.v1.checkout.sessions.create(
                params={
                    "mode": "payment",
                    "line_items": line_items,
                    "client_reference_id": str(order.pk),
                    "metadata": {"order_id": str(order.pk)},
                    "success_url": f"{settings.FRONTEND_URL}/orders/{order.pk}?paid=1",
                    "cancel_url": f"{settings.FRONTEND_URL}/orders/{order.pk}",
                }
            )
        except self.stripe.StripeError as exc:
            raise PaymentError(str(exc)) from exc
        return PaymentSession(self.name, session.id, session.url, confirmed=False)

    def parse_webhook(self, payload: bytes, signature: str):
        try:
            return self.stripe.Webhook.construct_event(
                payload, signature, settings.STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, self.stripe.SignatureVerificationError) as exc:
            raise PaymentError("Invalid webhook signature.") from exc


def get_provider():
    if settings.PAYMENT_PROVIDER == "stripe":
        return StripeProvider()
    return FakeProvider()
