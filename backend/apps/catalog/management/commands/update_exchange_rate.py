from django.core.management.base import BaseCommand

from apps.catalog.integrations import IntegrationError
from apps.catalog.tasks import update_exchange_rate


class Command(BaseCommand):
    help = "Fetch today's USD/UAH rate from the National Bank of Ukraine."

    def handle(self, *args, **options):
        # Independent of MARKET_FETCH_ENABLED: this is the NBU's public API,
        # and prices in UAH need it even on a site without a Celery beat.
        try:
            self.stdout.write(update_exchange_rate())
        except IntegrationError as exc:
            self.stdout.write(self.style.WARNING(f"NBU rate unavailable: {exc}"))
