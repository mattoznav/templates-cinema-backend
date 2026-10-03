from django.contrib import admin

from .models import Booking, BookingSeat, Ticket, TicketType


class BookingSeatInline(admin.TabularInline):
    model = BookingSeat
    extra = 0
    readonly_fields = ["seat", "ticket_type", "price", "active"]
    exclude = ["showtime"]


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["reference", "user", "showtime", "status", "total", "created_at"]
    list_filter = ["status"]
    search_fields = ["reference", "user__email"]
    readonly_fields = ["reference", "created_at", "confirmed_at", "cancelled_at"]
    inlines = [BookingSeatInline]


@admin.register(TicketType)
class TicketTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "price_delta"]


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ["code", "booking_seat", "checked_in_at"]
    search_fields = ["code"]
