from django.contrib import admin

from .models import Hall, Seat, SeatType


@admin.register(Hall)
class HallAdmin(admin.ModelAdmin):
    list_display = ["name", "format", "rows", "seats_per_row", "base_price"]


@admin.register(SeatType)
class SeatTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "surcharge"]


@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ["hall", "row", "number", "seat_type"]
    list_filter = ["hall", "seat_type"]
