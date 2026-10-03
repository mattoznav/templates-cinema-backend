"""Generate data/seats.csv and data/showtimes.csv from the halls and movies.

Showtimes are stored relative to the day the data is loaded (`day_offset`), so
the demo always shows the next two weeks, whenever it is started.

    python tools/build_schedule.py
"""

from __future__ import annotations

import csv
import random
import string
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
DAYS = 14
FIRST_SHOW = 14 * 60 + 30
LAST_START = 22 * 60 + 45
CLEANING = 20
MATINEE_END = 17 * 60
MATINEE_DISCOUNT = 1.50


def read(name: str) -> list[dict]:
    with open(DATA / name, newline="") as f:
        return list(csv.DictReader(f))


def write(name: str, fields: list[str], rows: list[dict]) -> None:
    with open(DATA / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def seats(halls: list[dict]) -> list[dict]:
    rows = []
    for hall in halls:
        n_rows, per_row = int(hall["rows"]), int(hall["seats_per_row"])
        # Premium: the central block of the back half. Wheelchair: front row ends.
        premium_rows = range(n_rows // 2, n_rows - 1)
        premium_cols = range(per_row // 4 + 1, per_row - per_row // 4 + 1)
        for r in range(n_rows):
            for n in range(1, per_row + 1):
                if r == 0 and n in (1, per_row):
                    kind = 3
                elif r in premium_rows and n in premium_cols:
                    kind = 2
                else:
                    kind = 1
                rows.append({"hall_id": hall["id"], "row": string.ascii_uppercase[r], "number": n, "seat_type_id": kind})
    for i, row in enumerate(rows, 1):
        row["id"] = i
    return rows


def showtimes(halls: list[dict], movies: list[dict]) -> list[dict]:
    rng = random.Random(42)
    showing = [m for m in movies if m["status"] == "now_showing" and m["runtime_minutes"]]
    # Bigger screens favour the most popular titles, smaller ones the rest
    showing.sort(key=lambda m: -int(m["popularity"]))
    rows = []
    for day in range(DAYS):
        for h, hall in enumerate(halls):
            pool = showing[: max(4, len(showing) // 2)] if h < 2 else showing[len(showing) // 3 :]
            minute = FIRST_SHOW + rng.choice((0, 15, 30))
            while minute <= LAST_START:
                movie = rng.choice(pool)
                price = float(hall["base_price"]) - (MATINEE_DISCOUNT if minute < MATINEE_END else 0)
                original = movie["languages"].split("|")[0] if movie["languages"] else "en"
                rows.append(
                    {
                        "movie_id": movie["id"],
                        "hall_id": hall["id"],
                        "day_offset": day,
                        "start_time": f"{minute // 60:02d}:{minute % 60:02d}",
                        "price": f"{price:.2f}",
                        "language": original,
                        "subtitles": "en" if original != "en" else "",
                    }
                )
                # Next show after the film, the cleaning break, rounded up to five minutes
                minute += int(movie["runtime_minutes"]) + CLEANING
                minute += -minute % 5
    for i, row in enumerate(rows, 1):
        row["id"] = i
    return rows


def main() -> None:
    halls = read("halls.csv")
    movies = read("movies.csv")
    seat_rows = seats(halls)
    write("seats.csv", ["id", "hall_id", "row", "number", "seat_type_id"], seat_rows)
    show_rows = showtimes(halls, movies)
    write("showtimes.csv", ["id", "movie_id", "hall_id", "day_offset", "start_time", "price", "language", "subtitles"], show_rows)
    print(f"Wrote {len(seat_rows)} seats and {len(show_rows)} showtimes")


if __name__ == "__main__":
    main()
