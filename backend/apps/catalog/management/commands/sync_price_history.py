from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.catalog.market import FETCH_DISABLED, Fetcher, fetching_enabled
from apps.catalog.market_stats import update_market_stats
from apps.catalog.models import MarketListing
from apps.catalog.price_history import product_path, sync_listing_history

MISSING_BELOW = 5


class Command(BaseCommand):
    help = (
        "Load the price history the source keeps for each listing (hotline.ua: daily for the "
        "last year, twice a month before). Safe to re-run; rows are upserted per day."
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, help="Only the first N listings.")
        parser.add_argument(
            "--missing",
            action="store_true",
            help="Only parts without a history yet (resumes an interrupted run).",
        )

    def handle(self, *args, limit=None, missing=False, **options):
        if not fetching_enabled():
            self.stdout.write(self.style.WARNING(FETCH_DISABLED))
            return
        fetcher = Fetcher()
        listings = MarketListing.objects.select_related("component").order_by("id")
        if missing:
            # Our own daily checks add a point or two; a synced chart adds hundreds.
            listings = listings.annotate(points=Count("component__price_history")).filter(
                points__lt=MISSING_BELOW
            )
        listings = [item for item in listings if product_path(item.url)][:limit]
        synced = rows = 0
        for i, listing in enumerate(listings, 1):
            count = sync_listing_history(listing, fetcher)
            if count is not None:
                synced += 1
                rows += count
            self.stdout.write(f"{i}/{len(listings)} {listing.component}: {count}")
        self.stdout.write(f"History for {synced} of {len(listings)} listings, {rows} rows written.")
        self.stdout.write(f"Market stats updated for {update_market_stats()} parts.")
