from django.contrib import admin

from .models import Genre, Movie


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ["name", "slug"]


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ["title", "status", "release_date", "runtime_minutes", "popularity"]
    list_filter = ["status", "genres"]
    search_fields = ["title", "slug"]
    prepopulated_fields = {"slug": ["title"]}
    filter_horizontal = ["genres"]
