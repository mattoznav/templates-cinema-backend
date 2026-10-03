"""Build the demo movie catalogue from open data.

Sources:
- Wikidata (CC0): titles, release dates, runtimes, genres, credits, countries,
  languages and YouTube trailer IDs.
- Wikipedia (CC BY-SA 4.0): the lead paragraph, used as the synopsis. Each row
  keeps its source URL so the attribution travels with the data.

Writes data/genres.csv, data/movies.csv and data/movie_genres.csv.
Uses only the standard library, so it runs without the project's virtualenv:

    python tools/build_catalog.py
"""

from __future__ import annotations

import csv
import json
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
USER_AGENT = "cinema-template-catalog-builder/1.0 (https://github.com/mattoznav/templates)"
SPARQL = "https://query.wikidata.org/sparql"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"

NOW_SHOWING = 12
MIN_SITELINKS = 22
MIN_SITELINKS_UPCOMING = 12
MAX_CAST = 4

# Wikidata genres are very granular ("supernatural horror film"): fold them into
# a short list a cinema would actually show. Order sets the priority.
GENRES = [
    ("action", "Action", ("action", "martial arts", "superhero", "spy")),
    ("adventure", "Adventure", ("adventure", "epic", "sword")),
    ("animation", "Animation", ("animated", "animation")),
    ("biography", "Biography", ("biographical",)),
    ("comedy", "Comedy", ("comedy", "parody", "satirical")),
    ("crime", "Crime", ("crime", "heist", "police", "neo-noir")),
    ("drama", "Drama", ("drama", "docudrama")),
    ("family", "Family", ("family",)),
    ("fantasy", "Fantasy", ("fantasy",)),
    ("history", "History", ("historical", "period")),
    ("horror", "Horror", ("horror", "slasher", "vampire")),
    ("musical", "Musical", ("musical",)),
    ("mystery", "Mystery", ("mystery", "detective")),
    ("romance", "Romance", ("romance", "romantic")),
    ("science-fiction", "Science Fiction", ("science fiction", "dystopian", "post-apocalyptic", "space western")),
    ("sport", "Sport", ("sport",)),
    ("thriller", "Thriller", ("thriller",)),
    ("western", "Western", ("western",)),
]
MAX_GENRES = 3


def http_json(url: str, params: dict | None = None) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=90) as res:
        return json.load(res)


def sparql(query: str) -> list[dict]:
    return http_json(SPARQL, {"query": query})["results"]["bindings"]


def qid(binding: dict) -> str:
    return binding["film"]["value"].rsplit("/", 1)[1]


def first_release_query(start: str, end: str, min_links: int, limit: int) -> str:
    # The earliest release date decides: re-releases of older films are filtered out.
    return f"""
    SELECT ?film (MIN(?d) AS ?release) (MAX(?l) AS ?links) WHERE {{
      ?film wdt:P577 ?d0. FILTER(?d0 >= "{start}"^^xsd:dateTime && ?d0 < "{end}"^^xsd:dateTime)
      ?film wdt:P31 wd:Q11424; wikibase:sitelinks ?l. FILTER(?l >= {min_links})
      ?film wdt:P577 ?d.
    }} GROUP BY ?film HAVING (MIN(?d) >= "{start}"^^xsd:dateTime)
    ORDER BY DESC(?links) LIMIT {limit}
    """


def label(var: str, out: str) -> str:
    return f'?{var} rdfs:label ?{out}. FILTER(LANG(?{out}) = "en")'


def fetch(today: date) -> tuple[dict, dict]:
    start = (today - timedelta(days=550)).isoformat()
    end = (today + timedelta(days=240)).isoformat()
    films: dict[str, dict] = {}
    for b in sparql(first_release_query(start, end, MIN_SITELINKS, 100)) + sparql(
        first_release_query(today.isoformat(), end, MIN_SITELINKS_UPCOMING, 30)
    ):
        films.setdefault(qid(b), {"release": b["release"]["value"][:10], "links": int(b["links"]["value"])})

    values = " ".join(f"wd:{q}" for q in films)
    details: dict[str, dict] = defaultdict(lambda: defaultdict(list))

    def collect(query: str, key: str, field: str) -> None:
        for b in sparql(query):
            value = b[field]["value"]
            if value not in details[qid(b)][key]:
                details[qid(b)][key].append(value)

    base = f"""SELECT ?film ?title ?dur ?yt ?wp WHERE {{ VALUES ?film {{ {values} }}
      OPTIONAL {{ {label("film", "title")} }} OPTIONAL {{ ?film wdt:P2047 ?dur }} OPTIONAL {{ ?film wdt:P1651 ?yt }}
      OPTIONAL {{ ?wp schema:about ?film; schema:isPartOf <https://en.wikipedia.org/> }} }}"""
    for b in sparql(base):
        for key, field in (("title", "title"), ("runtime", "dur"), ("trailer", "yt"), ("wikipedia", "wp")):
            if field in b and b[field]["value"] not in details[qid(b)][key]:
                details[qid(b)][key].append(b[field]["value"])

    collect(f"SELECT ?film ?x WHERE {{ VALUES ?film {{ {values} }} ?film wdt:P136 ?g. {label('g', 'x')} }}", "genres", "x")
    collect(f"SELECT ?film ?x WHERE {{ VALUES ?film {{ {values} }} ?film wdt:P57 ?p. {label('p', 'x')} }}", "directors", "x")
    collect(f"SELECT ?film ?x WHERE {{ VALUES ?film {{ {values} }} ?film wdt:P495 ?c. ?c wdt:P297 ?x }}", "countries", "x")
    collect(f"SELECT ?film ?x WHERE {{ VALUES ?film {{ {values} }} ?film wdt:P364 ?l. ?l wdt:P218 ?x }}", "languages", "x")

    # Cast keeps the billing order when Wikidata has it
    cast: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for b in sparql(
        f"""SELECT ?film ?x ?ord WHERE {{ VALUES ?film {{ {values} }} ?film p:P161 ?st. ?st ps:P161 ?p.
        OPTIONAL {{ ?st pq:P1545 ?ord }} {label('p', 'x')} }}"""
    ):
        order = b.get("ord", {}).get("value", "")
        cast[qid(b)].append((int(order) if order.isdigit() else 999, b["x"]["value"]))
    for q, people in cast.items():
        seen: list[str] = []
        for _, name in sorted(people, key=lambda p: p[0]):
            if name not in seen:
                seen.append(name)
        details[q]["cast"] = seen

    return films, details


def wikipedia_summary(url: str) -> dict:
    title = url.rsplit("/", 1)[1]
    req = urllib.request.Request(WIKI_SUMMARY + title, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)


def runtime_minutes(values: list[str]) -> int | None:
    for raw in values:
        minutes = float(raw)
        if minutes > 400:  # some entries are stored in seconds
            minutes /= 60
        if 60 <= minutes <= 240:
            return round(minutes)
    return None


def rank_cast(cast: list[str], synopsis: str) -> list[str]:
    # Billing order is rarely on Wikidata; the synopsis names the leads first.
    def position(name: str) -> tuple[int, int]:
        at = synopsis.find(name)
        return (0, at) if at >= 0 else (1, cast.index(name))

    return sorted(cast, key=position)[:MAX_CAST]


def map_genres(raw: list[str]) -> list[str]:
    found = []
    text = " | ".join(g.lower() for g in raw)
    for slug, _, keywords in GENRES:
        if any(k in text for k in keywords):
            found.append(slug)
    return found[:MAX_GENRES]


def slugify(text: str) -> str:
    text = text.lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def main() -> None:
    today = date.today()
    films, details = fetch(today)

    rows = []
    for q, film in films.items():
        d = details[q]
        runtime = runtime_minutes(d["runtime"])
        upcoming = film["release"] > today.isoformat()
        if not d["wikipedia"] or (runtime is None and not upcoming):
            continue
        summary = wikipedia_summary(d["wikipedia"][0])
        time.sleep(0.15)
        # Wikipedia titles carry disambiguation like "(2025 film)"; labels on
        # Wikidata are occasionally vandalised, so Wikipedia wins when they differ.
        title = re.sub(r"\s*\((?:\d{4} )?film\)$", "", summary.get("title", "")) or d["title"][0]
        rows.append(
            {
                "wikidata_id": q,
                "title": title,
                "release_date": film["release"],
                "runtime_minutes": runtime or "",
                "synopsis": (summary.get("extract") or "").strip(),
                "directors": "|".join(d["directors"]),
                "cast": "|".join(rank_cast(d.get("cast", []), summary.get("extract") or "")),
                "countries": "|".join(sorted(d["countries"])),
                "languages": "|".join(d["languages"]),
                "trailer_youtube_id": (d["trailer"] or [""])[0],
                "genres": map_genres(d["genres"]),
                "popularity": film["links"],
                "source_url": summary.get("content_urls", {}).get("desktop", {}).get("page", d["wikipedia"][0]),
            }
        )

    released = sorted((r for r in rows if r["release_date"] <= today.isoformat()), key=lambda r: r["release_date"], reverse=True)
    showing = {r["wikidata_id"] for r in released[:NOW_SHOWING]}
    for r in rows:
        if r["release_date"] > today.isoformat():
            r["status"] = "coming_soon"
        elif r["wikidata_id"] in showing:
            r["status"] = "now_showing"
        else:
            r["status"] = "archive"

    order = {"now_showing": 0, "coming_soon": 1, "archive": 2}
    rows.sort(key=lambda r: (order[r["status"]], -r["popularity"]))

    DATA.mkdir(exist_ok=True)
    with open(DATA / "genres.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "slug", "name"])
        for i, (slug, name, _) in enumerate(GENRES, 1):
            w.writerow([i, slug, name])
    genre_id = {slug: i for i, (slug, _, _) in enumerate(GENRES, 1)}

    used = set()
    movie_fields = [
        "id", "slug", "title", "status", "release_date", "runtime_minutes", "synopsis", "directors", "cast",
        "countries", "languages", "trailer_youtube_id", "popularity", "wikidata_id", "source_url",
    ]
    with open(DATA / "movies.csv", "w", newline="") as f, open(DATA / "movie_genres.csv", "w", newline="") as g:
        mw = csv.DictWriter(f, fieldnames=movie_fields, extrasaction="ignore")
        mw.writeheader()
        gw = csv.writer(g)
        gw.writerow(["movie_id", "genre_id"])
        for i, r in enumerate(rows, 1):
            slug = slugify(r["title"])
            if slug in used:
                slug = f"{slug}-{r['release_date'][:4]}"
            used.add(slug)
            mw.writerow({**r, "id": i, "slug": slug})
            for genre in r["genres"]:
                gw.writerow([i, genre_id[genre]])

    counts = {s: sum(r["status"] == s for r in rows) for s in order}
    print(f"Wrote {len(rows)} movies: {counts}")


if __name__ == "__main__":
    main()
