from celery import chain
from django.core.management.base import BaseCommand

from apps.catalog.integrations import IntegrationError
from apps.catalog.market import FETCH_DISABLED, Fetcher, fetching_enabled
from apps.catalog.market_service import listings_due, refresh_listing
from apps.catalog.models import ExchangeRate
from apps.catalog.tasks import refresh_market_listings, update_exchange_rate


class Command(BaseCommand):
    help = "Refresh market prices and photos from product pages (hotline.ua and others)."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Ignore MARKET_STALE_HOURS.")
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument(
            "--async", action="store_true", dest="run_async", help="Queue a Celery task instead."
        )

    def handle(self, *args, **options):
        if not fetching_enabled():
            self.stdout.write(self.style.WARNING(FETCH_DISABLED))
            return
        if options["run_async"]:
            # Chain: UAH prices can only be converted once the NBU rate is known.
            chain(update_exchange_rate.si(), refresh_market_listings.si(options["limit"])).delay()
            self.stdout.write("Queued update_exchange_rate → refresh_market_listings.")
            return

        fetcher = Fetcher()
        rate = ExchangeRate.latest_uah_rate()
        if rate is None:
            try:
                update_exchange_rate()
                rate = ExchangeRate.latest_uah_rate()
            except IntegrationError as exc:
                self.stdout.write(self.style.WARNING(f"NBU rate unavailable: {exc}"))
        if rate is None:
            self.stdout.write(
                self.style.WARNING("No USD/UAH rate yet: UAH prices will not be applied.")
            )
        listings = listings_due(stale_hours=0 if options["all"] else None)[: options["limit"]]
        for listing in listings:
            status = refresh_listing(listing, fetcher, rate)
            price = f"{listing.low_price} {listing.currency}" if listing.low_price else "—"
            self.stdout.write(f"{status:9} {listing.component!s:50.50} {price}")
