from django.core.management.base import BaseCommand

from apps.alerts.service import check_watches


class Command(BaseCommand):
    help = "Send Telegram alerts for watches whose price moved enough (normally a Celery task)."

    def handle(self, *args, **options):
        self.stdout.write(str(check_watches()))
