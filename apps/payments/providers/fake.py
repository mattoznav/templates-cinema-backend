import uuid

from .base import CheckoutSession, PaymentProvider


class FakeProvider(PaymentProvider):
    """Offline stand-in for a real provider.

    It follows the same steps as Stripe: the payment starts as pending and the
    outcome arrives later, through `POST /api/payments/fake/complete/`, which plays
    the part of the webhook. No money moves and no account is needed.
    """

    name = "fake"

    def create(self, payment) -> CheckoutSession:
        ref = f"fake_{uuid.uuid4().hex}"
        return CheckoutSession(provider_ref=ref, client_secret=f"{ref}_secret")

    def refund(self, payment) -> None:
        return None

    def parse_webhook(self, request):
        return None
