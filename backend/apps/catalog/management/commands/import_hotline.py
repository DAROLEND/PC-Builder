from django.core.management.base import BaseCommand, CommandError

from apps.catalog.importer import CATEGORY_PAGES, import_category
from apps.catalog.market import FETCH_DISABLED, fetching_enabled
from apps.catalog.market_stats import update_market_stats
from apps.catalog.tasks import import_catalog


class Command(BaseCommand):
    help = (
        "Import new products from hotline.ua category pages (name, brand, price, photos; "
        "specs where they can be derived reliably). Existing listings are skipped."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--category",
            action="append",
            choices=sorted(CATEGORY_PAGES),
            help="Category kind; repeat for several. Default: all.",
        )
        parser.add_argument("--pages", type=int, default=1, help="Listing pages per category.")
        parser.add_argument("--limit", type=int, help="Max new products per category.")
        parser.add_argument(
            "--async", action="store_true", dest="run_async", help="Queue it for the worker."
        )

    def handle(self, *args, category=None, pages=1, limit=None, run_async=False, **options):
        if not fetching_enabled():
            self.stdout.write(self.style.WARNING(FETCH_DISABLED))
            return
        if pages < 1:
            raise CommandError("--pages must be >= 1")
        kinds = category or sorted(CATEGORY_PAGES)
        if run_async:
            import_catalog.delay(kinds, pages)
            self.stdout.write(f"Queued import of {', '.join(kinds)} ({pages} page(s) each).")
            return
        for kind in kinds:
            stats = import_category(kind, pages=pages, limit=limit)
            self.stdout.write(
                f"{kind}: seen {stats.seen}, created {stats.created} "
                f"({stats.buildable} buildable), skipped {stats.skipped}, "
                f"errors {len(stats.errors)}"
            )
            for error in stats.errors[:5]:
                self.stderr.write(f"  {error}")
        update_market_stats()
