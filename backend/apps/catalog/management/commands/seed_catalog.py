"""Load the demo catalog and a few public demo builds.

Idempotent: safe to run on every container start. Every component goes through
``full_clean()``, so the seed file is validated against the spec schemas.
"""

import json
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from apps.builds.models import Build, BuildComponent
from apps.catalog.models import Category, Component, Manufacturer, MarketListing

SEED_FILE = Path(__file__).resolve().parents[2] / "fixtures" / "catalog_seed.json"
DEMO_USERNAME = "demo"


def make_sku(manufacturer: str, name: str) -> str:
    return slugify(f"{manufacturer} {name}").upper()[:64]


class Command(BaseCommand):
    help = "Seed the catalog with demo components and public demo builds."

    def add_arguments(self, parser):
        parser.add_argument("--no-builds", action="store_true", help="Skip demo builds.")
        parser.add_argument("--file", default=str(SEED_FILE), help="Seed JSON to load.")

    @transaction.atomic
    def handle(self, *args, **options):
        data = json.loads(Path(options["file"]).read_text(encoding="utf-8"))

        categories = {}
        for row in data["categories"]:
            category, _ = Category.objects.update_or_create(
                kind=row["kind"],
                defaults={"name": row["name"], "slug": row["slug"], "position": row["position"]},
            )
            categories[row["kind"]] = category

        created = 0
        by_name: dict[str, Component] = {}
        for row in data["components"]:
            manufacturer, _ = Manufacturer.objects.get_or_create(
                name=row["manufacturer"], defaults={"slug": slugify(row["manufacturer"])}
            )
            component = Component.objects.filter(
                manufacturer=manufacturer, name=row["name"]
            ).first()
            if component is None:
                component = Component(
                    manufacturer=manufacturer,
                    name=row["name"],
                    slug=slugify(f"{manufacturer.name} {row['name']}")[:160],
                    sku=make_sku(manufacturer.name, row["name"]),
                    price=Decimal(row["price"]),
                )
                created += 1
            component.category = categories[row["kind"]]
            component.specs = row["specs"]
            component.full_clean()
            component.save()
            by_name[row["name"]] = component
            if row.get("listing_url"):
                # Prices and photos for this listing are filled in by
                # `manage.py refresh_market` / the Celery beat task.
                MarketListing.objects.get_or_create(
                    url=row["listing_url"], defaults={"component": component}
                )

        self.stdout.write(f"Components: {created} created, {len(by_name) - created} updated.")

        if not options["no_builds"]:
            self._seed_builds(data["demo_builds"], by_name)

    def _seed_builds(self, builds, by_name):
        user, created = get_user_model().objects.get_or_create(
            username=DEMO_USERNAME, defaults={"email": "demo@pcbuilder.local"}
        )
        if created:
            user.set_password("demo12345")
            user.save()

        for row in builds:
            build, created = Build.objects.get_or_create(
                owner=user,
                name=row["name"],
                defaults={"description": row["description"], "is_public": True},
            )
            if not created:
                continue
            BuildComponent.objects.bulk_create(
                BuildComponent(build=build, component=by_name[name]) for name in row["components"]
            )
            report = build.compatibility_report()
            status = "OK" if report.is_compatible else f"ERRORS: {[e.code for e in report.errors]}"
            self.stdout.write(f"Demo build '{build.name}': {status}")
