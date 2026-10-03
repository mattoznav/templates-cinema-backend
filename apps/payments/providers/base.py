from dataclasses import dataclass

SUCCEEDED = "succeeded"
FAILED = "failed"


@dataclass
class CheckoutSession:
    provider_ref: str
    client_secret: str


@dataclass
class PaymentEvent:
    """A payment outcome reported by the provider, usually through a webhook."""

    provider_ref: str
    outcome: str  # SUCCEEDED or FAILED


class InvalidWebhook(Exception):
    pass


class PaymentProvider:
    name = ""

    def create(self, payment) -> CheckoutSession:
        raise NotImplementedError

    def refund(self, payment) -> None:
        raise NotImplementedError

    def parse_webhook(self, request) -> PaymentEvent | None:
        """Return the event carried by a webhook request, or None to ignore it."""
        raise NotImplementedError

    def public_config(self) -> dict:
        return {}
