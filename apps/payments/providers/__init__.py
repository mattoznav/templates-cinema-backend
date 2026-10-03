from django.conf import settings

from .base import FAILED, SUCCEEDED, CheckoutSession, InvalidWebhook, PaymentEvent, PaymentProvider


def get_provider(name: str | None = None) -> PaymentProvider:
    name = name or settings.PAYMENT_PROVIDER
    if name == "fake":
        from .fake import FakeProvider

        return FakeProvider()
    if name == "stripe":
        from .stripe import StripeProvider

        return StripeProvider()
    raise ValueError(f"Unknown payment provider: {name}")


__all__ = [
    "FAILED",
    "SUCCEEDED",
    "CheckoutSession",
    "InvalidWebhook",
    "PaymentEvent",
    "PaymentProvider",
    "get_provider",
]
