from datetime import timedelta

from django.conf import settings
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

    class Meta:
        model = Booking
        fields = [
            "id", "reference", "status", "showtime", "seats", "total", "currency", "expires_at",
            "created_at", "confirmed_at", "cancelled_at", "can_cancel",
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
    """Customers see their own bookings, staff see all of them (filter with `status`)."""

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Booking.objects.select_related("showtime__movie", "showtime__hall").prefetch_related(
            "seats__seat__seat_type", "seats__ticket_type", "seats__ticket"
        )
        if not self.request.user.is_staff:
            qs = qs.filter(user=self.request.user)
        if status_filter := self.request.query_params.get("status"):
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
        return Response(BookingSerializer(self.get_queryset().get(pk=booking.pk)).data, status=status.HTTP_201_CREATED)

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
        return Response(BookingSerializer(self.get_queryset().get(pk=booking.pk)).data)


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
