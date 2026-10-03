"""Load the demo data from data/*.csv into the database.

Every CSV file is a table: one row per record, an `id` column as primary key
and `<table>_id` columns as foreign keys. Edit the files, then run
`python manage.py load_data` to rebuild the database from them.
"""

import csv
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction

from apps.bookings.models import Booking, TicketType
from apps.catalog.models import Genre, Movie
from apps.core.models import Venue
from apps.halls.models import Hall, Seat, SeatType
from apps.payments.models import Payment
from apps.showtimes.models import Showtime


def read(name: str, data_dir: Path | None = None) -> list[dict]:
    path = Path(data_dir or settings.CINEMA_DATA_DIR) / name
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def split(value: str) -> list[str]:
    return [v for v in value.split("|") if v] if value else []


def optional_int(value: str) -> int | None:
    return int(value) if value else None


@transaction.atomic
def load_all(data_dir: Path | None = None, today: date | None = None) -> dict[str, int]:
    """Replace every table with the CSV contents. Users are kept."""

    def rows(name: str) -> list[dict]:
        return read(name, data_dir)

    # Children first, so foreign keys never point to a missing row
    Payment.objects.all().delete()
    Booking.objects.all().delete()
    for model in (Showtime, Seat, Hall, SeatType, TicketType, Movie, Genre, Venue):
        model.objects.all().delete()

    venues = [Venue(**row) for row in rows("venue.csv")]
    Venue.objects.bulk_create(venues)
    tz = ZoneInfo(venues[0].timezone if venues else settings.TIME_ZONE)

    Genre.objects.bulk_create([Genre(id=int(r["id"]), slug=r["slug"], name=r["name"]) for r in rows("genres.csv")])
    Movie.objects.bulk_create(
        [
            Movie(
                id=int(r["id"]),
                slug=r["slug"],
                title=r["title"],
                status=r["status"],
                release_date=date.fromisoformat(r["release_date"]) if r["release_date"] else None,
                runtime_minutes=optional_int(r["runtime_minutes"]),
                synopsis=r["synopsis"],
                directors=split(r["directors"]),
                cast=split(r["cast"]),
                countries=split(r["countries"]),
                languages=split(r["languages"]),
                trailer_youtube_id=r["trailer_youtube_id"],
                popularity=optional_int(r["popularity"]) or 0,
                wikidata_id=r["wikidata_id"],
                source_url=r["source_url"],
            )
            for r in rows("movies.csv")
        ]
    )
    Movie.genres.through.objects.bulk_create(
        [Movie.genres.through(movie_id=int(r["movie_id"]), genre_id=int(r["genre_id"])) for r in rows("movie_genres.csv")]
    )

    SeatType.objects.bulk_create(
        [SeatType(id=int(r["id"]), code=r["code"], name=r["name"], surcharge=Decimal(r["surcharge"])) for r in rows("seat_types.csv")]
    )
    TicketType.objects.bulk_create(
        [
            TicketType(
                id=int(r["id"]), code=r["code"], name=r["name"], description=r["description"], price_delta=Decimal(r["price_delta"])
            )
            for r in rows("ticket_types.csv")
        ]
    )
    Hall.objects.bulk_create(
        [
            Hall(
                id=int(r["id"]),
                name=r["name"],
                format=r["format"],
                rows=int(r["rows"]),
                seats_per_row=int(r["seats_per_row"]),
                base_price=Decimal(r["base_price"]),
            )
            for r in rows("halls.csv")
        ]
    )
    Seat.objects.bulk_create(
        [
            Seat(id=int(r["id"]), hall_id=int(r["hall_id"]), row=r["row"], number=int(r["number"]), seat_type_id=int(r["seat_type_id"]))
            for r in rows("seats.csv")
        ]
    )

    # Showtimes are stored as "days from today", so the schedule never goes stale
    today = today or datetime.now(tz).date()
    Showtime.objects.bulk_create(
        [
            Showtime(
                id=int(r["id"]),
                movie_id=int(r["movie_id"]),
                hall_id=int(r["hall_id"]),
                starts_at=datetime.combine(today + timedelta(days=int(r["day_offset"])), time.fromisoformat(r["start_time"]), tz),
                price=Decimal(r["price"]),
                language=r["language"],
                subtitles=r["subtitles"],
            )
            for r in rows("showtimes.csv")
        ]
    )

    return {
        "movies": Movie.objects.count(),
        "halls": Hall.objects.count(),
        "seats": Seat.objects.count(),
        "showtimes": Showtime.objects.count(),
    }
