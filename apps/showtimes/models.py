from datetime import timedelta

from django.db import models
from django.utils import timezone

from apps.catalog.models import Movie
from apps.halls.models import Hall


class Showtime(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="showtimes")
    hall = models.ForeignKey(Hall, on_delete=models.PROTECT, related_name="showtimes")
    starts_at = models.DateTimeField(db_index=True)
    price = models.DecimalField(max_digits=6, decimal_places=2)
    language = models.CharField(max_length=8, help_text="ISO 639-1 code of the audio.")
    subtitles = models.CharField(max_length=8, blank=True, help_text="ISO 639-1 code, empty for none.")

    class Meta:
        ordering = ["starts_at", "hall"]

    def __str__(self):
        return f"{self.movie} · {self.hall} · {timezone.localtime(self.starts_at):%Y-%m-%d %H:%M}"

    @property
    def ends_at(self):
        return self.starts_at + timedelta(minutes=self.movie.runtime_minutes or 0)

    @property
    def is_bookable(self):
        return self.starts_at > timezone.now()
