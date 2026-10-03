from decimal import Decimal

import stripe
from django.conf import settings

from .base import FAILED, SUCCEEDED, CheckoutSession, InvalidWebhook, PaymentEvent, PaymentProvider

# Stripe expects amounts in the smallest currency unit
ZERO_DECIMAL_CURRENCIES = {"JPY", "KRW", "VND", "CLP", "ISK", "HUF", "TWD", "UGX"}

EVENT_OUTCOMES = {
    "payment_intent.succeeded": SUCCEEDED,
    "payment_intent.payment_failed": FAILED,
}


def to_minor_units(amount: Decimal, currency: str) -> int:
    return int(amount) if currency.upper() in ZERO_DECIMAL_CURRENCIES else int(amount * 100)


class StripeProvider(PaymentProvider):
    """Payment Intents with automatic payment methods.

    The client confirms the payment with Stripe.js or the Flutter SDK using the
    client secret; Stripe then calls the webhook with the outcome.
    """

    name = "stripe"

    def __init__(self):
        if not settings.STRIPE_SECRET_KEY:
            raise RuntimeError("STRIPE_SECRET_KEY is not set.")
        self.client = stripe.StripeClient(settings.STRIPE_SECRET_KEY)

    def create(self, payment) -> CheckoutSession:
        intent = self.client.v1.payment_intents.create(
            params={
                "amount": to_minor_units(payment.amount, payment.currency),
                "currency": payment.currency.lower(),
                "automatic_payment_methods": {"enabled": True},
                "metadata": {"booking": payment.booking.reference, "payment_id": str(payment.pk)},
            },
            options={"idempotency_key": f"payment-{payment.pk}"},
        )
        return CheckoutSession(provider_ref=intent.id, client_secret=intent.client_secret)

    def refund(self, payment) -> None:
        self.client.v1.refunds.create(
            params={"payment_intent": payment.provider_ref},
            options={"idempotency_key": f"refund-{payment.pk}"},
        )

    def parse_webhook(self, request):
        if not settings.STRIPE_WEBHOOK_SECRET:
            raise InvalidWebhook("STRIPE_WEBHOOK_SECRET is not set.")
        try:
            event = self.client.construct_event(
                request.body, request.headers.get("Stripe-Signature"), settings.STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise InvalidWebhook(str(exc)) from exc
        outcome = EVENT_OUTCOMES.get(event.type)
        if outcome is None:
            return None
        return PaymentEvent(provider_ref=event.data.object.id, outcome=outcome)

    def public_config(self) -> dict:
        return {"publishable_key": settings.STRIPE_PUBLISHABLE_KEY}
