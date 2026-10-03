"""Booking rules: holding seats, releasing them, confirming and cancelling."""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.models import Venue
from apps.halls.models import Seat
from apps.showtimes.models import Showtime

from .models import Booking, BookingSeat, Ticket, TicketType


class BookingError(Exception):
    """The request breaks a booking rule. The message is safe to show to users."""


class SeatsUnavailable(BookingError):
    def __init__(self, labels):
        self.labels = labels
        super().__init__(f"These seats are no longer available: {', '.join(labels)}.")


@dataclass
class SeatRequest:
    seat: Seat
    ticket_type: TicketType


def seat_price(showtime: Showtime, seat: Seat, ticket_type: TicketType) -> Decimal:
    return max(Decimal("0.00"), showtime.price + seat.seat_type.surcharge + ticket_type.price_delta)


def release_expired(showtime: Showtime | None = None) -> int:
    """Expire unpaid bookings past their deadline and free their seats."""
    expired = Booking.objects.filter(status=Booking.Status.PENDING, expires_at__lte=timezone.now())
    if showtime is not None:
        expired = expired.filter(showtime=showtime)
    ids = list(expired.values_list("id", flat=True))
    if ids:
        with transaction.atomic():
            BookingSeat.objects.filter(booking_id__in=ids, active=True).update(active=False)
            Booking.objects.filter(id__in=ids).update(status=Booking.Status.EXPIRED)
    return len(ids)


def taken_seat_ids(showtime: Showtime) -> dict[int, str]:
    """Seat id -> "held" or "sold" for every seat that cannot be picked."""
    release_expired(showtime)
    rows = BookingSeat.objects.filter(showtime=showtime, active=True).values_list("seat_id", "booking__status")
    return {seat_id: "sold" if status == Booking.Status.CONFIRMED else "held" for seat_id, status in rows}


def hold_seats(user, showtime: Showtime, requests: list[SeatRequest]) -> Booking:
    if not showtime.is_bookable:
        raise BookingError("This showtime has already started.")
    if not requests:
        raise BookingError("Pick at least one seat.")
    if len(requests) > settings.BOOKING_MAX_SEATS:
        raise BookingError(f"You can book up to {settings.BOOKING_MAX_SEATS} seats at a time.")
    seat_ids = [r.seat.id for r in requests]
    if len(set(seat_ids)) != len(seat_ids):
        raise BookingError("Each seat can only be picked once.")
    if any(r.seat.hall_id != showtime.hall_id for r in requests):
        raise BookingError("Some seats are not in this showtime's hall.")

    release_expired(showtime)
    venue = Venue.objects.first()
    currency = venue.currency if venue else "EUR"

    try:
        with transaction.atomic():
            # Picking new seats for the same show replaces the previous unpaid selection
            for previous in Booking.objects.filter(user=user, showtime=showtime, status=Booking.Status.PENDING):
                _close(previous, Booking.Status.CANCELLED)

            booking = Booking.objects.create(
                user=user,
                showtime=showtime,
                total=Decimal("0.00"),
                currency=currency,
                expires_at=timezone.now() + timedelta(minutes=settings.BOOKING_HOLD_MINUTES),
            )
            total = Decimal("0.00")
            for r in requests:
                price = seat_price(showtime, r.seat, r.ticket_type)
                BookingSeat.objects.create(
                    booking=booking, showtime=showtime, seat=r.seat, ticket_type=r.ticket_type, price=price
                )
                total += price
            booking.total = total
            booking.save(update_fields=["total"])
    except IntegrityError:
        taken = taken_seat_ids(showtime)
        raise SeatsUnavailable([r.seat.label for r in requests if r.seat.id in taken]) from None
    return booking


@transaction.atomic
def confirm(booking: Booking) -> bool:
    """Mark a paid booking as confirmed and issue its tickets.

    Returns False when the hold had expired and someone else took the seats in
    the meantime: the caller must then refund the payment.
    """
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    if booking.status == Booking.Status.CONFIRMED:
        return True
    if booking.status not in (Booking.Status.PENDING, Booking.Status.EXPIRED):
        return False

    if booking.status == Booking.Status.EXPIRED:
        # Paid after the deadline: keep the booking only if the seats are still free
        try:
            with transaction.atomic():
                booking.seats.update(active=True)
        except IntegrityError:
            return False

    booking.status = Booking.Status.CONFIRMED
    booking.confirmed_at = timezone.now()
    booking.save(update_fields=["status", "confirmed_at"])
    Ticket.objects.bulk_create([Ticket(booking_seat=s) for s in booking.seats.filter(active=True)])
    return True


def cancel(booking: Booking, *, by_staff: bool = False) -> Booking:
    from apps.payments.services import refund_booking

    if booking.status in (Booking.Status.CANCELLED, Booking.Status.EXPIRED):
        raise BookingError("This booking is no longer active.")
    if booking.status == Booking.Status.CONFIRMED:
        cutoff = booking.showtime.starts_at - timedelta(hours=settings.CANCELLATION_CUTOFF_HOURS)
        if not by_staff and timezone.now() > cutoff:
            raise BookingError(
                f"Bookings can be cancelled up to {settings.CANCELLATION_CUTOFF_HOURS} hours before the show."
            )
        if booking.seats.filter(ticket__checked_in_at__isnull=False).exists():
            raise BookingError("Tickets already used at the door cannot be cancelled.")
        refund_booking(booking)
    with transaction.atomic():
        _close(booking, Booking.Status.CANCELLED)
    booking.refresh_from_db()
    return booking


def _close(booking: Booking, status: str) -> None:
    booking.seats.filter(active=True).update(active=False)
    booking.status = status
    booking.cancelled_at = timezone.now()
    booking.save(update_fields=["status", "cancelled_at"])
