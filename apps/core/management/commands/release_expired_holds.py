from django.core.management.base import BaseCommand

from apps.bookings.services import release_expired


class Command(BaseCommand):
    help = "Free the seats of unpaid bookings past their deadline. Seat maps also do this on read; run it from cron to keep lists tidy."

    def handle(self, *args, **options):
        count = release_expired()
        self.stdout.write(f"Released {count} expired booking(s)")
