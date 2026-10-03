from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["booking", "provider", "provider_ref", "amount", "currency", "status", "created_at"]
    list_filter = ["provider", "status"]
    search_fields = ["provider_ref", "booking__reference"]
