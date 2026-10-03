from django.contrib import admin

from .models import Showtime


@admin.register(Showtime)
class ShowtimeAdmin(admin.ModelAdmin):
    list_display = ["movie", "hall", "starts_at", "price", "language", "subtitles"]
    list_filter = ["hall", "movie"]
    date_hierarchy = "starts_at"
