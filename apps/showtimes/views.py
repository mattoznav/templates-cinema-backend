from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.bookings.models import TicketType
from apps.bookings.services import taken_seat_ids
from apps.catalog.models import Movie
from apps.core.permissions import IsStaffOrReadOnly
from apps.halls.models import Hall

from .models import Showtime


class ShowtimeSerializer(serializers.ModelSerializer):
    movie = serializers.SlugRelatedField(slug_field="slug", queryset=Movie.objects.all())
    movie_title = serializers.CharField(source="movie.title", read_only=True)
    hall = serializers.PrimaryKeyRelatedField(queryset=Hall.objects.all())
    hall_name = serializers.CharField(source="hall.name", read_only=True)
    hall_format = serializers.CharField(source="hall.format", read_only=True)
    ends_at = serializers.DateTimeField(read_only=True)
    is_bookable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Showtime
        fields = [
            "id", "movie", "movie_title", "hall", "hall_name", "hall_format", "starts_at", "ends_at",
            "price", "language", "subtitles", "is_bookable",
        ]

    def validate(self, attrs):
        if self.instance and "hall" in attrs and attrs["hall"] != self.instance.hall and self.instance.booked_seats.filter(active=True).exists():
            raise ValidationError({"hall": "Seats are already booked in this hall. Cancel the bookings before moving the show."})
        # A hall can only show one film at a time
        movie = attrs.get("movie") or self.instance.movie
        hall = attrs.get("hall") or self.instance.hall
        starts = attrs.get("starts_at") or self.instance.starts_at
        ends = starts + timedelta(minutes=movie.runtime_minutes or 0)
        overlapping = Showtime.objects.filter(hall=hall, starts_at__lt=ends, starts_at__gt=starts - timedelta(hours=4))
        if self.instance:
            overlapping = overlapping.exclude(pk=self.instance.pk)
        if any(other.ends_at > starts for other in overlapping.select_related("movie")):
            raise ValidationError({"starts_at": "The hall is busy with another showtime at this time."})
        return attrs


class ShowtimeViewSet(viewsets.ModelViewSet):
    """Showtimes from now on.

    Filters: `date` (YYYY-MM-DD, local time), `movie` (slug), `hall` (id).
    Without `date`, returns the next days of programming.
    """

    serializer_class = ShowtimeSerializer
    permission_classes = [IsStaffOrReadOnly]

    def get_queryset(self):
        qs = Showtime.objects.select_related("movie", "hall")
        if self.action != "list":
            return qs
        params = self.request.query_params
        if day := params.get("date"):
            try:
                day = date.fromisoformat(day)
            except ValueError:
                raise ValidationError({"date": "Use the YYYY-MM-DD format."}) from None
            start = datetime.combine(day, time.min, timezone.get_current_timezone())
            qs = qs.filter(starts_at__gte=start, starts_at__lt=start + timedelta(days=1))
        else:
            now = timezone.now()
            qs = qs.filter(starts_at__gte=now, starts_at__lt=now + timedelta(days=settings.SCHEDULE_DAYS))
        if movie := params.get("movie"):
            qs = qs.filter(movie__slug=movie)
        if hall := params.get("hall"):
            qs = qs.filter(hall_id=hall)
        return qs

    def destroy(self, request, *args, **kwargs):
        showtime = self.get_object()
        if showtime.bookings.exists():
            return Response(
                {"detail": "This showtime has bookings. Cancel them first, or keep the show in the programme."},
                status=status.HTTP_409_CONFLICT,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def seats(self, request, pk=None):
        """The seat map with live availability and prices per ticket type."""
        showtime = self.get_object()
        taken = taken_seat_ids(showtime)
        ticket_types = list(TicketType.objects.all())
        seats = showtime.hall.seats.select_related("seat_type")
        return Response(
            {
                "showtime": ShowtimeSerializer(showtime, context={"request": request}).data,
                "rows": showtime.hall.rows,
                "seats_per_row": showtime.hall.seats_per_row,
                "ticket_types": [
                    {"code": t.code, "name": t.name, "description": t.description, "price_delta": t.price_delta}
                    for t in ticket_types
                ],
                "seats": [
                    {
                        "id": seat.id,
                        "row": seat.row,
                        "number": seat.number,
                        "label": seat.label,
                        "type": seat.seat_type.code,
                        "price": showtime.price + seat.seat_type.surcharge,
                        "status": taken.get(seat.id, "available"),
                    }
                    for seat in seats
                ],
            }
        )
