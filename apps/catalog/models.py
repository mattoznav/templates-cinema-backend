from django.db import models


class Genre(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=60)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Movie(models.Model):
    class Status(models.TextChoices):
        NOW_SHOWING = "now_showing", "Now showing"
        COMING_SOON = "coming_soon", "Coming soon"
        ARCHIVE = "archive", "Archive"

    slug = models.SlugField(unique=True, max_length=120)
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.COMING_SOON, db_index=True)
    release_date = models.DateField(null=True, blank=True)
    runtime_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    synopsis = models.TextField(blank=True)
    directors = models.JSONField(default=list, blank=True)
    cast = models.JSONField(default=list, blank=True)
    countries = models.JSONField(default=list, blank=True)
    languages = models.JSONField(default=list, blank=True)
    genres = models.ManyToManyField(Genre, related_name="movies", blank=True)
    trailer_youtube_id = models.CharField(max_length=20, blank=True)
    poster_url = models.URLField(blank=True, help_text="Leave empty to use the generated demo poster.")
    popularity = models.PositiveIntegerField(default=0)
    # Where the demo data comes from, kept for attribution
    wikidata_id = models.CharField(max_length=20, blank=True)
    source_url = models.URLField(blank=True)

    class Meta:
        ordering = ["-popularity", "title"]

    def __str__(self):
        return self.title

    @property
    def trailer_url(self):
        return f"https://www.youtube.com/watch?v={self.trailer_youtube_id}" if self.trailer_youtube_id else ""
