from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsStaff
from apps.halls.models import Seat
from apps.payments.providers import get_provider
from apps.payments.services import PaymentError, start_checkout
from apps.showtimes.models import Showtime

from . import services
from .models import Booking, BookingSeat, Ticket, TicketType


class TicketTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketType
        fields = ["code", "name", "description", "price_delta"]


class BookingSeatSerializer(serializers.ModelSerializer):
    seat = serializers.CharField(source="seat.label")
    seat_type = serializers.CharField(source="seat.seat_type.code")
    ticket_type = serializers.CharField(source="ticket_type.code")
    ticket = serializers.SerializerMethodField()

    class Meta:
        model = BookingSeat
        fields = ["seat", "seat_type", "ticket_type", "price", "ticket"]

    def get_ticket(self, booking_seat):
        ticket = getattr(booking_seat, "ticket", None)
        return {"code": ticket.code, "checked_in_at": ticket.checked_in_at} if ticket else None


class BookingSerializer(serializers.ModelSerializer):
    showtime = serializers.SerializerMethodField()
    seats = BookingSeatSerializer(many=True, read_only=True)
    can_cancel = serializers.SerializerMethodField()
    customer = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id", "reference", "status", "showtime", "seats", "total", "currency", "expires_at",
            "created_at", "confirmed_at", "cancelled_at", "can_cancel", "customer", "payments",
        ]

    @property
    def _staff(self):
        request = self.context.get("request")
        return bool(request and request.user.is_staff)

    def get_customer(self, booking):
        # Only the back office sees who booked
        if not self._staff:
            return None
        user = booking.user
        return {"email": user.email, "name": user.get_full_name()}

    def get_payments(self, booking):
        if not self._staff:
            return None
        return [
            {"provider": p.provider, "status": p.status, "amount": p.amount, "created_at": p.created_at}
            for p in booking.payments.all()
        ]

    def get_showtime(self, booking):
        s = booking.showtime
        return {
            "id": s.id,
            "starts_at": s.starts_at,
            "movie": {"slug": s.movie.slug, "title": s.movie.title},
            "hall": {"id": s.hall_id, "name": s.hall.name, "format": s.hall.format},
        }

    def get_can_cancel(self, booking):
        if booking.status == Booking.Status.PENDING:
            return True
        if booking.status == Booking.Status.CONFIRMED and self._staff:
            return not any(s.ticket.checked_in_at for s in booking.seats.all() if hasattr(s, "ticket"))
        cutoff = booking.showtime.starts_at - timedelta(hours=settings.CANCELLATION_CUTOFF_HOURS)
        return booking.status == Booking.Status.CONFIRMED and timezone.now() < cutoff


class SeatPickSerializer(serializers.Serializer):
    seat = serializers.IntegerField()
    ticket_type = serializers.SlugField(default="adult")


class BookingCreateSerializer(serializers.Serializer):
    showtime = serializers.PrimaryKeyRelatedField(queryset=Showtime.objects.select_related("hall"))
    seats = SeatPickSerializer(many=True)

    def validate(self, attrs):
        picks = attrs["seats"]
        seats = Seat.objects.select_related("seat_type").in_bulk([p["seat"] for p in picks])
        ticket_types = {t.code: t for t in TicketType.objects.all()}
        requests = []
        for p in picks:
            if p["seat"] not in seats:
                raise ValidationError({"seats": f"Seat {p['seat']} does not exist."})
            if p["ticket_type"] not in ticket_types:
                raise ValidationError({"seats": f"Unknown ticket type '{p['ticket_type']}'."})
            requests.append(services.SeatRequest(seats[p["seat"]], ticket_types[p["ticket_type"]]))
        attrs["requests"] = requests
        return attrs


class BookingViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    """Customers see their own bookings, staff see all of them.

    Filters: `status`. Staff only: `q` (reference or customer email), `showtime`, `date` (YYYY-MM-DD of the show).
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Booking.objects.select_related("user", "showtime__movie", "showtime__hall").prefetch_related(
            "seats__seat__seat_type", "seats__ticket_type", "seats__ticket", "payments"
        )
        params = self.request.query_params
        if not self.request.user.is_staff:
            qs = qs.filter(user=self.request.user)
        else:
            if q := params.get("q"):
                qs = qs.filter(Q(reference__iexact=q.strip()) | Q(user__email__icontains=q.strip()))
            if showtime := params.get("showtime"):
                qs = qs.filter(showtime_id=showtime)
            if day := params.get("date"):
                try:
                    start = datetime.combine(date.fromisoformat(day), time.min, timezone.get_current_timezone())
                except ValueError:
                    raise ValidationError({"date": "Use the YYYY-MM-DD format."}) from None
                qs = qs.filter(showtime__starts_at__gte=start, showtime__starts_at__lt=start + timedelta(days=1))
        if status_filter := params.get("status"):
            qs = qs.filter(status=status_filter)
        return qs

    def get_serializer_class(self):
        return BookingCreateSerializer if self.action == "create" else BookingSerializer

    def create(self, request, *args, **kwargs):
        """Hold seats for a few minutes, until the booking is paid."""
        data = BookingCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            booking = services.hold_seats(request.user, data.validated_data["showtime"], data.validated_data["requests"])
        except services.SeatsUnavailable as exc:
            return Response({"detail": str(exc), "seats": exc.labels}, status=status.HTTP_409_CONFLICT)
        except services.BookingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(BookingSerializer(self.get_queryset().get(pk=booking.pk), context=self.get_serializer_context()).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def checkout(self, request, pk=None):
        """Start paying. Returns what the client needs to complete the payment."""
        booking = self.get_object()
        try:
            payment, client_secret = start_checkout(booking)
        except PaymentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(
            {
                "payment_id": payment.id,
                "provider": payment.provider,
                "amount": payment.amount,
                "currency": payment.currency,
                "client_secret": client_secret,
                **get_provider(payment.provider).public_config(),
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        try:
            booking = services.cancel(booking, by_staff=request.user.is_staff)
        except services.BookingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(BookingSerializer(self.get_queryset().get(pk=booking.pk), context=self.get_serializer_context()).data)


class TicketTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TicketType.objects.all()
    serializer_class = TicketTypeSerializer
    permission_classes = [AllowAny]
    pagination_class = None
    lookup_field = "code"


@api_view(["POST"])
@permission_classes([IsStaff])
def check_in(request, code):
    """Scan a ticket at the door. Each ticket works once."""
    ticket = get_object_or_404(
        Ticket.objects.select_related("booking_seat__booking__showtime__movie", "booking_seat__seat"), code=code
    )
    booking = ticket.booking_seat.booking
    info = {
        "code": ticket.code,
        "seat": ticket.booking_seat.seat.label,
        "booking": booking.reference,
        "movie": booking.showtime.movie.title,
        "starts_at": booking.showtime.starts_at,
    }
    if booking.status != Booking.Status.CONFIRMED:
        return Response({**info, "detail": "This booking is not valid."}, status=status.HTTP_409_CONFLICT)
    if ticket.checked_in_at:
        return Response(
            {**info, "checked_in_at": ticket.checked_in_at, "detail": "Ticket already used."},
            status=status.HTTP_409_CONFLICT,
        )
    ticket.checked_in_at = timezone.now()
    ticket.save(update_fields=["checked_in_at"])
    return Response({**info, "checked_in_at": ticket.checked_in_at})
