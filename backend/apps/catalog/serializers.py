from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import (
    Category,
    CategoryKind,
    Component,
    ExchangeRate,
    Manufacturer,
    MarketListing,
    PriceHistory,
)
from .specs import missing_fields, validate_specs


@extend_schema_field(OpenApiTypes.OBJECT)
class SpecsField(serializers.JSONField):
    """JSONB specs. Documented as an object (not "any") for the generated TS types."""


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "kind", "name", "slug", "position"]


class ManufacturerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Manufacturer
        fields = ["id", "name", "slug", "website"]


class MarketSerializer(serializers.ModelSerializer):
    """Live market data of the component's primary listing."""

    class Meta:
        model = MarketListing
        fields = [
            "source",
            "url",
            "low_price",
            "high_price",
            "median_price",
            "currency",
            "offer_count",
            "in_stock",
            "rating",
            "review_count",
            "status",
            "checked_at",
        ]


class MarketMixin(serializers.Serializer):
    image = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    market = serializers.SerializerMethodField()

    def get_image(self, obj: Component) -> str | None:
        return obj.image_url

    def get_images(self, obj: Component) -> list[str]:
        return obj.gallery

    @extend_schema_field(MarketSerializer(allow_null=True))
    def get_market(self, obj: Component) -> dict | None:
        listing = obj.primary_listing()
        return MarketSerializer(listing).data if listing else None


class ComponentSerializer(MarketMixin, serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    manufacturer = ManufacturerSerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        source="category", queryset=Category.objects.all(), write_only=True
    )
    manufacturer_id = serializers.PrimaryKeyRelatedField(
        source="manufacturer", queryset=Manufacturer.objects.all(), write_only=True
    )
    price_uah = serializers.SerializerMethodField()
    specs = SpecsField()
    specs_complete = serializers.BooleanField(read_only=True)
    missing_specs = serializers.SerializerMethodField()
    listed = serializers.SerializerMethodField(
        help_text="False when fewer than MARKET_MIN_SHOPS shops sell it (hidden from the catalog)."
    )

    class Meta:
        model = Component
        fields = [
            "id",
            "name",
            "slug",
            "sku",
            "price",
            "price_uah",
            "specs",
            "specs_complete",
            "missing_specs",
            "popularity",
            "popularity_rank",
            "shop_count",
            "listed",
            "price_change_30d",
            "at_year_low",
            "image",
            "images",
            "market",
            "is_active",
            "category",
            "manufacturer",
            "category_id",
            "manufacturer_id",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=0, allow_null=True))
    def get_price_uah(self, obj: Component) -> str | None:
        # The rate is resolved once per request by the view and passed in the
        # context, otherwise every row would hit the ExchangeRate table.
        rate = self.context.get("uah_rate")
        if rate is None:
            return None
        # str(): keep money as a decimal string like every other price field.
        return str((obj.price * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    def get_listed(self, obj: Component) -> bool:
        return obj.shop_count is None or obj.shop_count >= settings.MARKET_MIN_SHOPS

    def get_missing_specs(self, obj: Component) -> list[str]:
        return missing_fields(obj.category.kind, obj.specs)

    def validate(self, attrs):
        category = attrs.get("category") or getattr(self.instance, "category", None)
        specs = attrs.get("specs", getattr(self.instance, "specs", None))
        if category is not None and specs is not None:
            errors = validate_specs(category.kind, specs, partial=True)
            if errors:
                raise serializers.ValidationError({"specs": errors})
        return attrs


class ComponentBriefSerializer(MarketMixin, serializers.ModelSerializer):
    """Compact representation used inside builds and orders."""

    kind = serializers.ChoiceField(
        source="category.kind", choices=CategoryKind.choices, read_only=True
    )
    manufacturer = serializers.CharField(source="manufacturer.name", read_only=True)
    specs = SpecsField(read_only=True)

    class Meta:
        model = Component
        fields = [
            "id",
            "name",
            "slug",
            "kind",
            "manufacturer",
            "price",
            "specs",
            "image",
            "market",
            "is_active",
        ]


class PriceHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceHistory
        fields = ["price", "low_price", "high_price", "source", "recorded_at"]


class ExchangeRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExchangeRate
        fields = ["currency", "rate", "rate_date", "fetched_at"]


class ListingCreateSerializer(serializers.Serializer):
    url = serializers.URLField(max_length=500)

    def validate_url(self, value: str) -> str:
        if MarketListing.objects.filter(url=value).exists():
            raise serializers.ValidationError("This URL is already attached to a component.")
        return value


class ListingSerializer(MarketSerializer):
    class Meta(MarketSerializer.Meta):
        fields = ["id", "title", "images", "last_error", *MarketSerializer.Meta.fields]
