from django.db import models


class SeatType(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=60)
    surcharge = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    def __str__(self):
        return self.name


class Hall(models.Model):
    name = models.CharField(max_length=60)
    format = models.CharField(max_length=40, blank=True, help_text="For example IMAX or Dolby Atmos.")
    rows = models.PositiveSmallIntegerField()
    seats_per_row = models.PositiveSmallIntegerField()
    base_price = models.DecimalField(max_digits=6, decimal_places=2)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name


class Seat(models.Model):
    hall = models.ForeignKey(Hall, on_delete=models.CASCADE, related_name="seats")
    row = models.CharField(max_length=2)
    number = models.PositiveSmallIntegerField()
    seat_type = models.ForeignKey(SeatType, on_delete=models.PROTECT, related_name="seats")

    class Meta:
        ordering = ["hall", "row", "number"]
        constraints = [models.UniqueConstraint(fields=["hall", "row", "number"], name="unique_seat_position")]

    def __str__(self):
        return f"{self.hall} {self.label}"

    @property
    def label(self):
        return f"{self.row}{self.number}"
