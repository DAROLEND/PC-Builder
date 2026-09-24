from django.contrib import admin, messages

from .market import FETCH_DISABLED, Fetcher, fetching_enabled
from .market_service import refresh_listing
from .models import Category, Component, ExchangeRate, Manufacturer, MarketListing, PriceHistory


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "position"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = ["name", "website"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}


class PriceHistoryInline(admin.TabularInline):
    model = PriceHistory
    extra = 0
    readonly_fields = ["price", "source", "recorded_at"]
    can_delete = False


class MarketListingInline(admin.TabularInline):
    model = MarketListing
    extra = 0
    fields = [
        "url",
        "status",
        "low_price",
        "high_price",
        "currency",
        "offer_count",
        "in_stock",
        "checked_at",
    ]
    readonly_fields = [
        "status",
        "low_price",
        "high_price",
        "currency",
        "offer_count",
        "in_stock",
        "checked_at",
    ]


@admin.register(MarketListing)
class MarketListingAdmin(admin.ModelAdmin):
    list_display = [
        "component",
        "source",
        "status",
        "low_price",
        "currency",
        "offer_count",
        "checked_at",
    ]
    list_filter = ["status", "source", "in_stock"]
    search_fields = ["component__name", "title", "url"]
    readonly_fields = ["title", "images", "last_error", "checked_at"]
    actions = ["refresh_now"]

    @admin.action(description="Refresh selected listings now")
    def refresh_now(self, request, queryset):
        if not fetching_enabled():
            self.message_user(request, FETCH_DISABLED, level=messages.WARNING)
            return
        fetcher, rate = Fetcher(), ExchangeRate.latest_uah_rate()
        for listing in queryset.select_related("component__manufacturer"):
            refresh_listing(listing, fetcher, rate)
        self.message_user(request, f"Refreshed {queryset.count()} listing(s).")


@admin.register(Component)
class ComponentAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "manufacturer", "price", "is_active"]
    list_filter = ["category", "manufacturer", "is_active"]
    search_fields = ["name", "sku"]
    list_select_related = ["category", "manufacturer"]
    prepopulated_fields = {"slug": ["name"]}
    inlines = [MarketListingInline, PriceHistoryInline]


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ["currency", "rate", "rate_date", "fetched_at"]
