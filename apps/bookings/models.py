import secrets
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.halls.models import Seat
from apps.showtimes.models import Showtime

# No 0/O or 1/I: references are read out loud at the box office
REFERENCE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_reference():
    return "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(8))


def new_ticket_code():
    return uuid.uuid4().hex


class TicketType(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=60)
    description = models.CharField(max_length=200, blank=True)
    price_delta = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending payment"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    reference = models.CharField(max_length=12, unique=True, default=new_reference, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings")
    showtime = models.ForeignKey(Showtime, on_delete=models.PROTECT, related_name="bookings")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    total = models.DecimalField(max_digits=8, decimal_places=2)
    currency = models.CharField(max_length=3)
    expires_at = models.DateTimeField(help_text="Seats are released after this time unless the booking is paid.")
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.reference


class BookingSeat(models.Model):
    """A seat inside a booking.

    `active` seats are held or sold. The partial unique constraint is what stops
    two people from getting the same seat, even when they click at the same time.
    """

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="seats")
    showtime = models.ForeignKey(Showtime, on_delete=models.PROTECT, related_name="booked_seats")
    seat = models.ForeignKey(Seat, on_delete=models.PROTECT, related_name="bookings")
    ticket_type = models.ForeignKey(TicketType, on_delete=models.PROTECT)
    price = models.DecimalField(max_digits=6, decimal_places=2)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["seat__row", "seat__number"]
        constraints = [
            models.UniqueConstraint(
                fields=["showtime", "seat"],
                condition=Q(active=True),
                name="unique_active_seat_per_showtime",
            )
        ]

    def __str__(self):
        return f"{self.booking} {self.seat.label}"


class Ticket(models.Model):
    booking_seat = models.OneToOneField(BookingSeat, on_delete=models.CASCADE, related_name="ticket")
    code = models.CharField(max_length=32, unique=True, default=new_ticket_code, editable=False)
    checked_in_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.code
