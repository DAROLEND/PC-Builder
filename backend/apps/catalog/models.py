from decimal import Decimal
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from .models_enums import CategoryKind
from .specs import is_complete, validate_specs

__all__ = [
    "Category",
    "CategoryKind",
    "Component",
    "ExchangeRate",
    "Manufacturer",
    "MarketListing",
    "PriceHistory",
]


class Category(models.Model):
    kind = models.CharField(max_length=20, choices=CategoryKind.choices, unique=True)
    name = models.CharField(max_length=64)
    slug = models.SlugField(unique=True)
    # Order in which slots are shown in the configurator.
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "name"]
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name


class Manufacturer(models.Model):
    name = models.CharField(max_length=64, unique=True)
    slug = models.SlugField(unique=True)
    website = models.URLField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ComponentQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def listed(self):
        """Parts shown in the catalog: enough shops sell them to trust the price.

        Parts without market data (no listing yet) are kept. Hidden parts stay
        reachable by URL and valid in existing builds.
        """
        return self.filter(
            Q(shop_count__isnull=True) | Q(shop_count__gte=settings.MARKET_MIN_SHOPS)
        )

    def buildable(self):
        """Parts the compatibility engine can reason about and people can buy."""
        return self.filter(is_active=True, specs_complete=True).listed()

    def with_related(self):
        return self.select_related("category", "manufacturer")

    def with_market(self):
        """Related rows plus market listings (photos, live prices) in one extra query."""
        return self.with_related().prefetch_related("listings", "photos")


class Component(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="components")
    manufacturer = models.ForeignKey(
        Manufacturer, on_delete=models.PROTECT, related_name="components"
    )
    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=160, unique=True)
    # Supplier SKU used to match rows from the external price feed.
    sku = models.CharField(max_length=64, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price in USD")
    specs = models.JSONField(default=dict)
    # Derived from ``specs`` on save. Incomplete parts (e.g. freshly imported
    # ones) are shown in the catalog but cannot be added to builds.
    specs_complete = models.BooleanField(default=True, db_index=True, editable=False)
    # Market statistics, recomputed in batches by market_stats.update_market_stats()
    # so the catalog can sort by them with a plain indexed query.
    popularity = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_index=True,
        editable=False,
        help_text="Interest index from the source (hotline.ua), 7-day average.",
    )
    popularity_rank = models.PositiveIntegerField(
        null=True, blank=True, editable=False, help_text="1 = most popular in its category."
    )
    price_change_30d = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        null=True,
        blank=True,
        db_index=True,
        editable=False,
        help_text="Change of the average market price over 30 days, %.",
    )
    shop_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_index=True,
        editable=False,
        help_text="Shops selling it now (best listing); null = no market data.",
    )
    at_year_low = models.BooleanField(
        default=False, editable=False, help_text="Price is at its lowest of the last 12 months."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ComponentQuerySet.as_manager()

    class Meta:
        ordering = ["category__position", "price"]
        constraints = [
            models.CheckConstraint(condition=Q(price__gte=0), name="component_price_non_negative"),
            models.UniqueConstraint(
                fields=["manufacturer", "name"], name="component_unique_name_per_manufacturer"
            ),
        ]
        indexes = [
            # jsonb_path_ops is smaller and faster than the default opclass
            # for the containment queries we run: specs @> '{"socket": "AM5"}'.
            GinIndex(fields=["specs"], name="component_specs_gin", opclasses=["jsonb_path_ops"]),
            models.Index(fields=["category", "price"], name="component_category_price_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.manufacturer} {self.name}"

    def save(self, *args, **kwargs):
        if self.category_id is not None:
            self.specs_complete = is_complete(self.category.kind, self.specs)
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = {*kwargs["update_fields"], "specs_complete"}
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        if self.category_id is None:
            return
        # Missing fields are allowed (the part is then catalog-only); wrong
        # types or values never are.
        errors = validate_specs(self.category.kind, self.specs, partial=True)
        if errors:
            raise ValidationError(
                {"specs": [f"{field}: {msg}" for field, msgs in errors.items() for msg in msgs]}
            )

    @property
    def kind(self) -> str:
        return self.category.kind

    def primary_listing(self) -> "MarketListing | None":
        """The listing to show: verified and in stock first, then the cheapest.

        Works on the prefetch cache (``with_market()``), so serializing a page of
        components does not issue a query per row.
        """
        listings = list(self.listings.all())
        if not listings:
            return None

        def rank(listing):
            ok = listing.status == MarketListing.Status.OK
            return (
                not ok,
                listing.in_stock is False,
                listing.low_price is None,
                listing.low_price or 0,
            )

        return sorted(listings, key=rank)[0]

    @property
    def image_url(self) -> str | None:
        """Our own thumbnail when mirrored; the source image until then."""
        photos = list(self.photos.all())
        if photos:
            return photos[0].thumb.url
        for listing in self.listings.all():
            if listing.images:
                return listing.images[0]
        return None

    @property
    def gallery(self) -> list[str]:
        photos = list(self.photos.all())
        if photos:
            return [p.large.url for p in photos]
        listing = self.primary_listing()
        return list(listing.images) if listing else []


class PriceHistory(models.Model):
    """Price of a component over time, in USD.

    The market refresh writes one row per component per day (the last check of
    the day wins), so charts have a point for every day even when nothing
    changed. ``low_price``/``high_price`` are the cheapest and dearest shop
    offers of that day; ``price`` is the typical (median) one. The supplier
    feed task appends a row whenever its price changes.
    """

    component = models.ForeignKey(Component, on_delete=models.CASCADE, related_name="price_history")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    low_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    high_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=32, default="feed")
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-recorded_at"]
        verbose_name_plural = "price history"
        indexes = [
            models.Index(fields=["component", "recorded_at"], name="pricehistory_comp_time_idx")
        ]

    def __str__(self) -> str:
        return f"{self.component_id}: {self.price} at {self.recorded_at:%Y-%m-%d %H:%M}"


class MarketListing(models.Model):
    """The same product on an external site (aggregator or shop).

    Refreshed by ``apps.catalog.tasks.refresh_market_listings``; the lowest
    in-stock price of a verified listing becomes the component's price, the
    first image becomes its photo. See ``apps/catalog/market.py``.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Not checked yet"
        OK = "ok", "Up to date"
        NO_OFFERS = "no_offers", "No offers on the page"
        MISMATCH = "mismatch", "Page shows a different product"
        ERROR = "error", "Fetch failed"

    component = models.ForeignKey(Component, on_delete=models.CASCADE, related_name="listings")
    url = models.URLField(max_length=500, unique=True)
    source = models.CharField(max_length=64, help_text="Host name, e.g. hotline.ua")
    title = models.CharField(max_length=300, blank=True, help_text="Product name on the source")
    low_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    high_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # Median of the shop offers, when the source lists them individually.
    median_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    offer_count = models.PositiveIntegerField(null=True, blank=True)
    in_stock = models.BooleanField(null=True)
    rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    review_count = models.PositiveIntegerField(null=True, blank=True)
    images = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    last_error = models.CharField(max_length=500, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["component_id", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(low_price__isnull=True)
                | Q(high_price__isnull=True)
                | Q(low_price__lte=F("high_price")),
                name="listing_low_le_high",
            ),
            models.CheckConstraint(
                condition=Q(low_price__isnull=True) | Q(low_price__gte=0),
                name="listing_price_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source}: {self.title or self.url}"

    def save(self, *args, **kwargs):
        if not self.source:
            self.source = urlsplit(self.url).netloc.removeprefix("www.")
        super().save(*args, **kwargs)


class ExchangeRate(models.Model):
    """USD→UAH rate from the National Bank of Ukraine, refreshed by Celery beat."""

    currency = models.CharField(max_length=3)
    rate = models.DecimalField(max_digits=12, decimal_places=4)
    rate_date = models.DateField()
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["currency", "rate_date"], name="unique_rate_per_day"),
            models.CheckConstraint(condition=Q(rate__gt=0), name="exchange_rate_positive"),
        ]
        ordering = ["-rate_date"]

    def __str__(self) -> str:
        return f"{self.currency} {self.rate} ({self.rate_date})"

    @classmethod
    def latest_uah_rate(cls) -> Decimal | None:
        row = cls.objects.filter(currency="USD").order_by("-rate_date").first()
        return row.rate if row else None


class ProductImage(models.Model):
    """A product photo mirrored from a market listing and resized by us.

    Hot-linking the aggregator's originals was slow (up to 700 KB each) and
    fragile (their CDN rejects some clients), so the worker downloads each
    photo once and stores a small thumbnail and a large WebP next to it.
    """

    component = models.ForeignKey(Component, on_delete=models.CASCADE, related_name="photos")
    source_url = models.URLField(max_length=500)
    position = models.PositiveSmallIntegerField(default=0)
    thumb = models.ImageField(upload_to="products/thumbs/")
    large = models.ImageField(upload_to="products/large/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["component_id", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["component", "source_url"], name="product_image_unique_source"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.component_id} #{self.position}"
