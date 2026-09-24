from decimal import ROUND_HALF_UP, Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.builds.models import Build
from apps.catalog.models import Component

from .models import TelegramLink, Watch
from .service import current_price


class WatchItemSerializer(serializers.Serializer):
    """What a watch points at, flattened for lists (profile page, bot)."""

    kind = serializers.ChoiceField(choices=["component", "build"])
    name = serializers.CharField()
    path = serializers.CharField(help_text="Site path, e.g. /catalog/<slug> or /builds/<id>.")
    image = serializers.CharField(allow_null=True)
    category = serializers.CharField(allow_null=True)


class WatchSerializer(serializers.ModelSerializer):
    component = serializers.PrimaryKeyRelatedField(
        queryset=Component.objects.active(), required=False, allow_null=True
    )
    build = serializers.PrimaryKeyRelatedField(
        queryset=Build.objects.all(), required=False, allow_null=True
    )
    item = serializers.SerializerMethodField()
    current_price = serializers.SerializerMethodField()
    change_percent = serializers.SerializerMethodField()

    class Meta:
        model = Watch
        fields = [
            "id",
            "component",
            "build",
            "item",
            "target_price",
            "threshold_percent",
            "baseline_price",
            "current_price",
            "change_percent",
            "last_notified_at",
            "created_at",
        ]
        read_only_fields = ["baseline_price", "last_notified_at", "created_at"]
        # Uniqueness per user is checked in validate(), with a readable message.
        validators = []

    def validate_build(self, build):
        user = self.context["request"].user
        if build is not None and not Build.objects.visible_to(user).filter(pk=build.pk).exists():
            raise serializers.ValidationError("Build not found.")
        return build

    def validate(self, attrs):
        if self.instance is not None:  # updates change only the conditions
            attrs.pop("component", None)
            attrs.pop("build", None)
            return attrs
        component, build = attrs.get("component"), attrs.get("build")
        if bool(component) == bool(build):
            raise serializers.ValidationError("Watch exactly one of `component` or `build`.")
        user = self.context["request"].user
        existing = Watch.objects.filter(user=user, component=component, build=build)
        if existing.exists():
            raise serializers.ValidationError("You are already watching this.")
        return attrs

    def create(self, validated_data):
        watch = Watch(user=self.context["request"].user, **validated_data)
        watch.baseline_price = current_price(watch) or Decimal("0.00")
        watch.save()
        return watch

    def _price(self, obj: Watch):
        cache = self.context.setdefault("_prices", {})
        if obj.pk not in cache:
            cache[obj.pk] = current_price(obj)
        return cache[obj.pk]

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True))
    def get_current_price(self, obj: Watch):
        price = self._price(obj)
        return None if price is None else f"{price:.2f}"

    @extend_schema_field(serializers.DecimalField(max_digits=6, decimal_places=1, allow_null=True))
    def get_change_percent(self, obj: Watch):
        price = self._price(obj)
        if price is None or not obj.baseline_price:
            return None
        change = (price - obj.baseline_price) / obj.baseline_price * 100
        return f"{change.quantize(Decimal('0.1'), ROUND_HALF_UP):.1f}"

    @extend_schema_field(WatchItemSerializer)
    def get_item(self, obj: Watch) -> dict:
        if obj.component_id:
            c = obj.component
            return {
                "kind": "component",
                "name": f"{c.manufacturer.name} {c.name}",
                "path": f"/catalog/{c.slug}",
                "image": c.image_url,
                "category": c.category.kind,
            }
        return {
            "kind": "build",
            "name": obj.build.name,
            "path": f"/builds/{obj.build_id}",
            "image": None,
            "category": None,
        }


class TelegramStatusSerializer(serializers.ModelSerializer):
    linked = serializers.BooleanField(read_only=True)
    bot_username = serializers.SerializerMethodField()
    bot_url = serializers.SerializerMethodField()

    class Meta:
        model = TelegramLink
        fields = [
            "linked",
            "username",
            "enabled",
            "quiet_hours",
            "language",
            "linked_at",
            "bot_username",
            "bot_url",
        ]
        read_only_fields = ["linked", "username", "linked_at"]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_bot_username(self, obj) -> str | None:
        return self.context.get("bot_username")

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_bot_url(self, obj) -> str | None:
        name = self.context.get("bot_username")
        return f"https://t.me/{name}" if name else None


class TelegramLinkRequestSerializer(serializers.Serializer):
    language = serializers.ChoiceField(choices=TelegramLink.Language.choices, default="uk")


class TelegramLinkResponseSerializer(serializers.Serializer):
    url = serializers.URLField(help_text="Open it: Telegram starts the bot with a one-time code.")
    expires_in = serializers.IntegerField(help_text="Seconds.")
