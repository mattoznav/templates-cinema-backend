from rest_framework import serializers, viewsets
from rest_framework.permissions import AllowAny

from .models import Hall, SeatType


class SeatTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeatType
        fields = ["code", "name", "surcharge"]


class HallSerializer(serializers.ModelSerializer):
    capacity = serializers.SerializerMethodField()

    class Meta:
        model = Hall
        fields = ["id", "name", "format", "rows", "seats_per_row", "base_price", "capacity"]

    def get_capacity(self, hall):
        return hall.seats.count()


class HallViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Hall.objects.all()
    serializer_class = HallSerializer
    permission_classes = [AllowAny]
    pagination_class = None


class SeatTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SeatType.objects.all()
    serializer_class = SeatTypeSerializer
    permission_classes = [AllowAny]
    pagination_class = None
    lookup_field = "code"
