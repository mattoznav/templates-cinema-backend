from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.bookings.models import Booking, BookingSeat, Ticket
from apps.core.csvdata import load_all
from apps.payments.models import Payment
from apps.payments.providers import PaymentEvent
from apps.payments.services import handle_event
from apps.showtimes.models import Showtime

User = get_user_model()


@override_settings(PAYMENT_PROVIDER="fake")
class BookingFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        load_all()
        cls.showtime = Showtime.objects.filter(starts_at__gt=timezone.now() + timedelta(hours=3)).first()
        cls.seats = list(cls.showtime.hall.seats.order_by("id")[:4])
        cls.alice = User.objects.create_user("alice@example.com", "a-long-password")
        cls.bob = User.objects.create_user("bob@example.com", "a-long-password")
        cls.staff = User.objects.create_user("staff@example.com", "a-long-password", is_staff=True)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def hold(self, user, seats, ticket_type="adult"):
        return self.client_for(user).post(
            reverse("booking-list"),
            {"showtime": self.showtime.id, "seats": [{"seat": s.id, "ticket_type": ticket_type} for s in seats]},
            format="json",
        )

    def pay(self, user, booking_id, outcome="succeeded"):
        client = self.client_for(user)
        checkout = client.post(reverse("booking-checkout", args=[booking_id]))
        self.assertEqual(checkout.status_code, 201, checkout.data)
        return client.post(
            reverse("payment-fake-complete"), {"payment_id": checkout.data["payment_id"], "outcome": outcome}, format="json"
        )

    def test_hold_prices_and_seat_map(self):
        res = self.hold(self.alice, self.seats[:2], "reduced")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["status"], "pending")
        expected = sum(self.showtime.price + s.seat_type.surcharge - 2 for s in self.seats[:2])
        self.assertEqual(float(res.data["total"]), float(expected))

        seat_map = APIClient().get(reverse("showtime-seats", args=[self.showtime.id])).data
        status = {s["id"]: s["status"] for s in seat_map["seats"]}
        self.assertEqual(status[self.seats[0].id], "held")
        self.assertEqual(status[self.seats[2].id], "available")

    def test_same_seat_cannot_be_held_twice(self):
        self.assertEqual(self.hold(self.alice, self.seats[:2]).status_code, 201)
        res = self.hold(self.bob, self.seats[1:3])
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.data["seats"], [self.seats[1].label])

    def test_expired_hold_frees_the_seats(self):
        booking_id = self.hold(self.alice, self.seats[:1]).data["id"]
        Booking.objects.filter(pk=booking_id).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.hold(self.bob, self.seats[:1]).status_code, 201)
        self.assertEqual(Booking.objects.get(pk=booking_id).status, "expired")

    def test_new_selection_replaces_the_previous_one(self):
        first = self.hold(self.alice, self.seats[:1]).data["id"]
        self.assertEqual(self.hold(self.alice, self.seats[:2]).status_code, 201)
        self.assertEqual(Booking.objects.get(pk=first).status, "cancelled")

    def test_successful_payment_issues_tickets(self):
        booking_id = self.hold(self.alice, self.seats[:2]).data["id"]
        res = self.pay(self.alice, booking_id)
        self.assertEqual(res.data, {"payment_status": "succeeded", "booking_status": "confirmed"})
        self.assertEqual(Ticket.objects.filter(booking_seat__booking_id=booking_id).count(), 2)

        seat_map = APIClient().get(reverse("showtime-seats", args=[self.showtime.id])).data
        self.assertEqual({s["id"]: s["status"] for s in seat_map["seats"]}[self.seats[0].id], "sold")

    def test_failed_payment_keeps_the_hold_for_a_retry(self):
        booking_id = self.hold(self.alice, self.seats[:1]).data["id"]
        self.assertEqual(self.pay(self.alice, booking_id, "failed").data["booking_status"], "pending")
        self.assertEqual(self.pay(self.alice, booking_id).data["booking_status"], "confirmed")

    def test_duplicate_webhook_is_ignored(self):
        booking_id = self.hold(self.alice, self.seats[:1]).data["id"]
        self.pay(self.alice, booking_id)
        payment = Payment.objects.get(booking_id=booking_id, status="succeeded")
        handle_event("fake", PaymentEvent(payment.provider_ref, "succeeded"))
        self.assertEqual(Ticket.objects.filter(booking_seat__booking_id=booking_id).count(), 1)
        self.assertEqual(Payment.objects.get(pk=payment.pk).status, "succeeded")

    def test_late_payment_is_refunded_when_seats_are_gone(self):
        booking_id = self.hold(self.alice, self.seats[:1]).data["id"]
        checkout = self.client_for(self.alice).post(reverse("booking-checkout", args=[booking_id])).data
        Booking.objects.filter(pk=booking_id).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.hold(self.bob, self.seats[:1]).status_code, 201)

        payment = Payment.objects.get(pk=checkout["payment_id"])
        handle_event("fake", PaymentEvent(payment.provider_ref, "succeeded"))
        self.assertEqual(Payment.objects.get(pk=payment.pk).status, "refunded")
        self.assertEqual(Booking.objects.get(pk=booking_id).status, "expired")

    def test_late_payment_is_kept_when_seats_are_still_free(self):
        booking_id = self.hold(self.alice, self.seats[:1]).data["id"]
        checkout = self.client_for(self.alice).post(reverse("booking-checkout", args=[booking_id])).data
        Booking.objects.filter(pk=booking_id).update(expires_at=timezone.now() - timedelta(seconds=1))
        APIClient().get(reverse("showtime-seats", args=[self.showtime.id]))  # triggers the release

        payment = Payment.objects.get(pk=checkout["payment_id"])
        handle_event("fake", PaymentEvent(payment.provider_ref, "succeeded"))
        self.assertEqual(Booking.objects.get(pk=booking_id).status, "confirmed")
        self.assertTrue(BookingSeat.objects.get(booking_id=booking_id).active)

    def test_cancel_confirmed_booking_refunds_and_frees_seats(self):
        booking_id = self.hold(self.alice, self.seats[:1]).data["id"]
        self.pay(self.alice, booking_id)
        res = self.client_for(self.alice).post(reverse("booking-cancel", args=[booking_id]))
        self.assertEqual(res.data["status"], "cancelled")
        self.assertEqual(Payment.objects.get(booking_id=booking_id, provider="fake", status="refunded").booking_id, booking_id)
        self.assertEqual(self.hold(self.bob, self.seats[:1]).status_code, 201)

    def test_cannot_cancel_close_to_the_show(self):
        soon = Showtime.objects.filter(starts_at__gt=timezone.now()).first()
        Showtime.objects.filter(pk=soon.pk).update(starts_at=timezone.now() + timedelta(minutes=30))
        seat = soon.hall.seats.first()
        client = self.client_for(self.alice)
        booking_id = client.post(
            reverse("booking-list"), {"showtime": soon.id, "seats": [{"seat": seat.id}]}, format="json"
        ).data["id"]
        self.pay(self.alice, booking_id)
        self.assertEqual(client.post(reverse("booking-cancel", args=[booking_id])).status_code, 400)
        # Staff can still cancel, for example when a show is called off
        self.assertEqual(self.client_for(self.staff).post(reverse("booking-cancel", args=[booking_id])).status_code, 200)

    def test_check_in_works_once(self):
        booking_id = self.hold(self.alice, self.seats[:1]).data["id"]
        self.pay(self.alice, booking_id)
        code = Ticket.objects.get(booking_seat__booking_id=booking_id).code
        url = reverse("ticket-check-in", args=[code])
        self.assertEqual(self.client_for(self.alice).post(url).status_code, 403)
        self.assertEqual(self.client_for(self.staff).post(url).status_code, 200)
        self.assertEqual(self.client_for(self.staff).post(url).status_code, 409)

    def test_users_only_see_their_own_bookings(self):
        booking_id = self.hold(self.alice, self.seats[:1]).data["id"]
        self.assertEqual(self.client_for(self.bob).get(reverse("booking-detail", args=[booking_id])).status_code, 404)
        self.assertEqual(self.client_for(self.staff).get(reverse("booking-detail", args=[booking_id])).status_code, 200)

    def test_past_showtime_cannot_be_booked(self):
        Showtime.objects.filter(pk=self.showtime.pk).update(starts_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.hold(self.alice, self.seats[:1]).status_code, 400)


@override_settings(
    PAYMENT_PROVIDER="stripe", STRIPE_SECRET_KEY="sk_test_dummy", STRIPE_WEBHOOK_SECRET="whsec_dummy"
)
class StripeWebhookTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        load_all()
        cls.user = User.objects.create_user("carol@example.com", "a-long-password")

    def test_webhook_confirms_booking(self):
        showtime = Showtime.objects.filter(starts_at__gt=timezone.now()).first()
        client = APIClient()
        client.force_authenticate(self.user)
        booking_id = client.post(
            reverse("booking-list"), {"showtime": showtime.id, "seats": [{"seat": showtime.hall.seats.first().id}]}, format="json"
        ).data["id"]

        intent = mock.Mock(id="pi_123", client_secret="pi_123_secret")
        with mock.patch("stripe.StripeClient") as stripe_client:
            stripe_client.return_value.v1.payment_intents.create.return_value = intent
            checkout = client.post(reverse("booking-checkout", args=[booking_id]))
        self.assertEqual(checkout.data["client_secret"], "pi_123_secret")

        event = mock.Mock(type="payment_intent.succeeded")
        event.data.object.id = "pi_123"
        with mock.patch("stripe.StripeClient") as stripe_client:
            stripe_client.return_value.construct_event.return_value = event
            res = APIClient().post(
                reverse("payment-stripe-webhook"), data=b"{}", content_type="application/json", HTTP_STRIPE_SIGNATURE="t=1,v1=x"
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Booking.objects.get(pk=booking_id).status, "confirmed")

    def test_invalid_signature_is_rejected(self):
        res = APIClient().post(
            reverse("payment-stripe-webhook"), data=b"{}", content_type="application/json", HTTP_STRIPE_SIGNATURE="bad"
        )
        self.assertEqual(res.status_code, 400)
