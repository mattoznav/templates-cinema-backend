from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.bookings.models import Ticket
from apps.catalog.models import Movie
from apps.core.csvdata import load_all
from apps.showtimes.models import Showtime

User = get_user_model()


@override_settings(PAYMENT_PROVIDER="fake")
class BackOfficeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        load_all()
        cls.staff = User.objects.create_user("staff@example.com", "a-long-password", is_staff=True)
        cls.customer = User.objects.create_user("noor.haddad@example.com", "a-long-password", first_name="Noor")
        cls.showtime = Showtime.objects.filter(starts_at__gt=timezone.now() + timedelta(hours=3)).first()

    def as_user(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def book_and_pay(self, seats=2):
        client = self.as_user(self.customer)
        picks = [{"seat": s.id} for s in self.showtime.hall.seats.order_by("id")[:seats]]
        booking = client.post(reverse("booking-list"), {"showtime": self.showtime.id, "seats": picks}, format="json").data
        payment = client.post(reverse("booking-checkout", args=[booking["id"]])).data
        client.post(reverse("payment-fake-complete"), {"payment_id": payment["payment_id"]}, format="json")
        return booking

    def test_summary_counts_sold_seats_and_takings(self):
        booking = self.book_and_pay(seats=2)
        day = timezone.localtime(self.showtime.starts_at).date().isoformat()
        data = self.as_user(self.staff).get(reverse("admin-summary"), {"date": day}).data
        row = next(r for r in data["showtimes"] if r["id"] == self.showtime.id)
        self.assertEqual(row["sold"], 2)
        self.assertEqual(float(row["revenue"]), float(booking["total"]))
        self.assertEqual(data["sales_today"]["tickets"], 2)

    def test_summary_is_staff_only(self):
        self.assertEqual(self.as_user(self.customer).get(reverse("admin-summary")).status_code, 403)

    def test_staff_search_by_email_and_reference(self):
        booking = self.book_and_pay()
        staff = self.as_user(self.staff)
        by_email = staff.get(reverse("booking-list"), {"q": "noor.haddad"}).data["results"]
        by_ref = staff.get(reverse("booking-list"), {"q": booking["reference"].lower()}).data["results"]
        self.assertEqual([b["id"] for b in by_email], [booking["id"]])
        self.assertEqual([b["id"] for b in by_ref], [booking["id"]])
        self.assertEqual(by_email[0]["customer"]["email"], "noor.haddad@example.com")
        self.assertEqual(by_email[0]["payments"][0]["status"], "succeeded")

    def test_customers_do_not_see_staff_fields(self):
        self.book_and_pay()
        mine = self.as_user(self.customer).get(reverse("booking-list")).data["results"][0]
        self.assertIsNone(mine["customer"])
        self.assertIsNone(mine["payments"])

    def test_checked_in_booking_cannot_be_cancelled(self):
        booking = self.book_and_pay(seats=1)
        Ticket.objects.filter(booking_seat__booking_id=booking["id"]).update(checked_in_at=timezone.now())
        staff = self.as_user(self.staff)
        self.assertFalse(staff.get(reverse("booking-detail", args=[booking["id"]])).data["can_cancel"])
        self.assertEqual(staff.post(reverse("booking-cancel", args=[booking["id"]])).status_code, 400)

    def test_showtime_with_bookings_is_protected(self):
        self.book_and_pay(seats=1)
        staff = self.as_user(self.staff)
        self.assertEqual(staff.delete(reverse("showtime-detail", args=[self.showtime.id])).status_code, 409)
        other_hall = 1 if self.showtime.hall_id != 1 else 2
        res = staff.patch(reverse("showtime-detail", args=[self.showtime.id]), {"hall": other_hall}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("hall", res.data)
        movie = self.showtime.movie
        self.assertEqual(staff.delete(reverse("movie-detail", args=[movie.slug])).status_code, 409)

    def test_film_without_bookings_can_be_deleted(self):
        movie = Movie.objects.filter(status="archive").first()
        self.assertEqual(self.as_user(self.staff).delete(reverse("movie-detail", args=[movie.slug])).status_code, 204)
