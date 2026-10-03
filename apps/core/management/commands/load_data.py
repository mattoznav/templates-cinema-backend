from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.core.csvdata import load_all


class Command(BaseCommand):
    help = "Rebuild the database from data/*.csv. Bookings and payments are cleared, users are kept."

    def handle(self, *args, **options):
        counts = load_all()
        self.stdout.write(self.style.SUCCESS("Loaded " + ", ".join(f"{n} {name}" for name, n in counts.items())))

        if settings.DEMO_ADMIN_PASSWORD:
            User = get_user_model()
            user, created = User.objects.get_or_create(
                email=settings.DEMO_ADMIN_EMAIL, defaults={"is_staff": True, "is_superuser": True}
            )
            if created:
                user.set_password(settings.DEMO_ADMIN_PASSWORD)
                user.save()
                self.stdout.write(self.style.SUCCESS(f"Created admin user {user.email}"))
