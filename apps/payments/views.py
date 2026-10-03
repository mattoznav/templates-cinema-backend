from django.conf import settings
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from rest_framework import serializers, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from . import services
from .models import Payment
from .providers import FAILED, SUCCEEDED, InvalidWebhook, PaymentEvent, get_provider


@api_view(["GET"])
@permission_classes([AllowAny])
def config(request):
    """Which provider is active, and its public settings for the clients."""
    return Response({"provider": settings.PAYMENT_PROVIDER, **get_provider().public_config()})


class FakeCompleteSerializer(serializers.Serializer):
    payment_id = serializers.IntegerField()
    outcome = serializers.ChoiceField(choices=[SUCCEEDED, FAILED], default=SUCCEEDED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def fake_complete(request):
    """Fake provider only: the customer "pays" and the outcome is delivered like a webhook."""
    if settings.PAYMENT_PROVIDER != "fake":
        return Response({"detail": "The fake provider is not active."}, status=status.HTTP_404_NOT_FOUND)
    data = FakeCompleteSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    payment = get_object_or_404(Payment, pk=data.validated_data["payment_id"], provider="fake", booking__user=request.user)
    payment = services.handle_event("fake", PaymentEvent(payment.provider_ref, data.validated_data["outcome"]))
    payment.booking.refresh_from_db()
    return Response({"payment_status": payment.status, "booking_status": payment.booking.status})


@csrf_exempt
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def stripe_webhook(request):
    try:
        event = get_provider("stripe").parse_webhook(request)
    except (InvalidWebhook, RuntimeError) as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if event is not None:
        services.handle_event("stripe", event)
    return Response({"received": True})
