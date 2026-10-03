"""Payment flow, the same for every provider.

1. `start_checkout` creates a pending payment and returns the client secret.
2. The customer pays on the client.
3. The provider reports the outcome (webhook) and `handle_event` applies it.

`handle_event` is idempotent: providers may deliver the same event twice.
"""

from django.db import transaction
from django.utils import timezone

from apps.bookings import services as bookings
from apps.bookings.models import Booking

from .models import Payment
from .providers import FAILED, SUCCEEDED, PaymentEvent, get_provider


class PaymentError(Exception):
    pass


def start_checkout(booking: Booking) -> tuple[Payment, str]:
    if booking.status != Booking.Status.PENDING or booking.expires_at <= timezone.now():
        raise PaymentError("This booking can no longer be paid. Pick your seats again.")

    provider = get_provider()
    # A new attempt replaces any unfinished one
    booking.payments.filter(status=Payment.Status.PENDING).update(status=Payment.Status.CANCELLED)
    payment = Payment.objects.create(
        booking=booking, provider=provider.name, amount=booking.total, currency=booking.currency
    )
    session = provider.create(payment)
    payment.provider_ref = session.provider_ref
    payment.save(update_fields=["provider_ref", "updated_at"])
    return payment, session.client_secret


def handle_event(provider_name: str, event: PaymentEvent) -> Payment | None:
    with transaction.atomic():
        payment = (
            Payment.objects.select_for_update()
            .select_related("booking")
            .filter(provider=provider_name, provider_ref=event.provider_ref)
            .first()
        )
        if payment is None or payment.status in (Payment.Status.SUCCEEDED, Payment.Status.REFUNDED):
            return payment

        if event.outcome == FAILED:
            if payment.status == Payment.Status.PENDING:
                payment.status = Payment.Status.FAILED
                payment.save(update_fields=["status", "updated_at"])
            return payment

        if event.outcome != SUCCEEDED:
            return payment

        # Money was taken, even if this attempt had been replaced: honour it
        payment.status = Payment.Status.SUCCEEDED
        payment.save(update_fields=["status", "updated_at"])
        booking = payment.booking
        already_paid = booking.status == Booking.Status.CONFIRMED

    if already_paid or not bookings.confirm(booking):
        # Paid twice, or paid too late for seats that are now gone
        refund(payment)
    return payment


def refund(payment: Payment) -> None:
    if payment.status != Payment.Status.SUCCEEDED:
        return
    get_provider(payment.provider).refund(payment)
    payment.status = Payment.Status.REFUNDED
    payment.save(update_fields=["status", "updated_at"])


def refund_booking(booking: Booking) -> None:
    for payment in booking.payments.filter(status=Payment.Status.SUCCEEDED):
        refund(payment)
