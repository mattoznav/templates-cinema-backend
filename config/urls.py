from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.views import MeView, RegisterView
from apps.bookings.views import BookingViewSet, TicketTypeViewSet, check_in
from apps.catalog.views import GenreViewSet, MovieViewSet
from apps.core.views import health, venue
from apps.halls.views import HallViewSet, SeatTypeViewSet
from apps.payments import views as payments
from apps.showtimes.views import ShowtimeViewSet

router = DefaultRouter()
router.register("movies", MovieViewSet, basename="movie")
router.register("genres", GenreViewSet, basename="genre")
router.register("halls", HallViewSet, basename="hall")
router.register("seat-types", SeatTypeViewSet, basename="seat-type")
router.register("ticket-types", TicketTypeViewSet, basename="ticket-type")
router.register("showtimes", ShowtimeViewSet, basename="showtime")
router.register("bookings", BookingViewSet, basename="booking")

api = [
    path("", include(router.urls)),
    path("venue/", venue, name="venue"),
    path("health/", health, name="health"),
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/token/", TokenObtainPairView.as_view(), name="token"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("tickets/<str:code>/check-in/", check_in, name="ticket-check-in"),
    path("payments/config/", payments.config, name="payment-config"),
    path("payments/fake/complete/", payments.fake_complete, name="payment-fake-complete"),
    path("payments/stripe/webhook/", payments.stripe_webhook, name="payment-stripe-webhook"),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(api)),
]
