"""Daily figures for the admin back office."""

from datetime import date, datetime, time, timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.bookings.models import Booking, BookingSeat
from apps.bookings.services import release_expired
from apps.halls.models import Hall
from apps.showtimes.models import Showtime

from .models import Venue
from .permissions import IsStaff

SOLD = Q(booked_seats__active=True, booked_seats__booking__status=Booking.Status.CONFIRMED)
HELD = Q(booked_seats__active=True, booked_seats__booking__status=Booking.Status.PENDING)
CHECKED_IN = SOLD & Q(booked_seats__ticket__checked_in_at__isnull=False)


@api_view(["GET"])
@permission_classes([IsStaff])
def summary(request):
    """Screenings of a day (`date`, default today) with occupancy and takings, plus today's sales."""
    try:
        day = date.fromisoformat(request.query_params["date"]) if "date" in request.query_params else timezone.localdate()
    except ValueError:
        raise ValidationError({"date": "Use the YYYY-MM-DD format."}) from None
    start = datetime.combine(day, time.min, timezone.get_current_timezone())
    end = start + timedelta(days=1)

    release_expired()
    capacity = dict(Hall.objects.annotate(n=Count("seats")).values_list("id", "n"))
    showtimes = (
        Showtime.objects.filter(starts_at__gte=start, starts_at__lt=end)
        .select_related("movie", "hall")
        .annotate(
            sold=Count("booked_seats", filter=SOLD),
            held=Count("booked_seats", filter=HELD),
            checked_in=Count("booked_seats", filter=CHECKED_IN),
            revenue=Sum("booked_seats__price", filter=SOLD),
        )
        .order_by("starts_at", "hall_id")
    )
    rows = [
        {
            "id": s.id,
            "starts_at": s.starts_at,
            "ends_at": s.ends_at,
            "movie": {"slug": s.movie.slug, "title": s.movie.title},
            "hall": {"id": s.hall_id, "name": s.hall.name, "format": s.hall.format},
            "capacity": capacity.get(s.hall_id, 0),
            "sold": s.sold,
            "held": s.held,
            "checked_in": s.checked_in,
            "revenue": s.revenue or 0,
        }
        for s in showtimes
    ]

    today = timezone.localdate()
    sales_start = datetime.combine(today, time.min, timezone.get_current_timezone())
    sales = BookingSeat.objects.filter(
        booking__status=Booking.Status.CONFIRMED,
        booking__confirmed_at__gte=sales_start,
        booking__confirmed_at__lt=sales_start + timedelta(days=1),
    ).aggregate(tickets=Count("id"), revenue=Sum("price"), bookings=Count("booking", distinct=True))

    venue = Venue.objects.first()
    return Response(
        {
            "date": day,
            "currency": venue.currency if venue else "EUR",
            "totals": {
                "showtimes": len(rows),
                "capacity": sum(r["capacity"] for r in rows),
                "sold": sum(r["sold"] for r in rows),
                "held": sum(r["held"] for r in rows),
                "checked_in": sum(r["checked_in"] for r in rows),
                "revenue": sum(r["revenue"] for r in rows),
            },
            "sales_today": {
                "bookings": sales["bookings"],
                "tickets": sales["tickets"],
                "revenue": sales["revenue"] or 0,
            },
            "showtimes": rows,
        }
    )
