from django.db import models


class Venue(models.Model):
    """The cinema itself. The template runs a single venue."""

    name = models.CharField(max_length=120)
    tagline = models.CharField(max_length=200, blank=True)
    address = models.CharField(max_length=200)
    city = models.CharField(max_length=120)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=2)
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    timezone = models.CharField(max_length=60)
    currency = models.CharField(max_length=3)

    def __str__(self):
        return self.name
