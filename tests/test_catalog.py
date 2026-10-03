from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.models import Movie
from apps.core.csvdata import load_all
from apps.showtimes.models import Showtime

User = get_user_model()


class CatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.counts = load_all()
        cls.staff = User.objects.create_user("staff@example.com", "a-long-password", is_staff=True)

    def test_csv_tables_are_loaded(self):
        self.assertGreater(self.counts["movies"], 0)
        self.assertGreater(self.counts["showtimes"], 0)
        # Every showtime is in the future window and every now-showing movie is scheduled
        first = Showtime.objects.order_by("starts_at").first()
        self.assertEqual(timezone.localtime(first.starts_at).date(), timezone.localdate())
        for movie in Movie.objects.filter(status="now_showing"):
            self.assertTrue(movie.showtimes.exists(), movie.title)

    def test_filters(self):
        client = APIClient()
        showing = client.get(reverse("movie-list"), {"status": "now_showing"}).data
        self.assertTrue(all(m["status"] == "now_showing" for m in showing["results"]))
        horror = client.get(reverse("movie-list"), {"genre": "horror"}).data["results"]
        self.assertTrue(horror and all("horror" in m["genres"] for m in horror))

    def test_poster_is_generated(self):
        movie = Movie.objects.first()
        res = APIClient().get(reverse("movie-poster", args=[movie.slug]))
        self.assertEqual(res["Content-Type"], "image/svg+xml")
        self.assertIn(b"<svg", res.content)

    def test_only_staff_can_edit(self):
        movie = Movie.objects.first()
        url = reverse("movie-detail", args=[movie.slug])
        self.assertIn(APIClient().patch(url, {"title": "x"}).status_code, (401, 403))
        client = APIClient()
        client.force_authenticate(self.staff)
        self.assertEqual(client.patch(url, {"title": "Renamed"}, format="json").status_code, 200)

    def test_showtimes_by_date(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        rows = APIClient().get(reverse("showtime-list"), {"date": tomorrow.isoformat()}).data["results"]
        self.assertTrue(rows)
        self.assertTrue(all(timezone.localtime(Showtime.objects.get(pk=r["id"]).starts_at).date() == tomorrow for r in rows))

    def test_overlapping_showtime_is_rejected(self):
        existing = Showtime.objects.select_related("movie").first()
        client = APIClient()
        client.force_authenticate(self.staff)
        res = client.post(
            reverse("showtime-list"),
            {
                "movie": existing.movie.slug,
                "hall": existing.hall_id,
                "starts_at": (existing.starts_at + timedelta(minutes=10)).isoformat(),
                "price": "9.00",
                "language": "en",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("starts_at", res.data)

    def test_register_and_sign_in(self):
        client = APIClient()
        res = client.post(
            reverse("register"), {"email": "dana@example.com", "password": "a-long-password"}, format="json"
        )
        self.assertEqual(res.status_code, 201)
        token = client.post(reverse("token"), {"email": "dana@example.com", "password": "a-long-password"}).data["access"]
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(client.get(reverse("me")).data["email"], "dana@example.com")
