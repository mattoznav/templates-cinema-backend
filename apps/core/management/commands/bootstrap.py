from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the database and fill it from data/*.csv. Safe to run again to reset the demo."

    def handle(self, *args, **options):
        call_command("migrate", interactive=False, verbosity=0)
        call_command("load_data")
