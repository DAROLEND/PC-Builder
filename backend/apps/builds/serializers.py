from collections import Counter

from django.db import transaction
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.models import Component
from apps.catalog.serializers import ComponentBriefSerializer

from . import compatibility
from .models import Build, BuildComponent, Comment

# --- Compatibility report (read-only, documented for OpenAPI) -------------------


class IssueSerializer(serializers.Serializer):
    code = serializers.CharField()
    severity = serializers.ChoiceField(choices=["error", "warning"])
    message = serializers.CharField()
    component_ids = serializers.ListField(child=serializers.IntegerField())
    params = serializers.DictField(help_text="Values for rendering a localised message by `code`.")


class CompatibilityReportSerializer(serializers.Serializer):
    is_compatible = serializers.BooleanField()
    is_complete = serializers.BooleanField()
    errors = IssueSerializer(many=True)
    warnings = IssueSerializer(many=True)
    missing = serializers.ListField(child=serializers.CharField())
    estimated_wattage = serializers.IntegerField()
    recommended_psu_wattage = serializers.IntegerField()


# --- Write side -------------------------------------------------------------------


class BuildItemWriteSerializer(serializers.Serializer):
    component = serializers.PrimaryKeyRelatedField(
        queryset=Component.objects.active().with_related()
    )
    quantity = serializers.IntegerField(min_value=1, max_value=8, default=1)

    def validate_component(self, component: Component) -> Component:
        if not component.specs_complete:
            raise serializers.ValidationError(
                f"{component} is catalog-only: its specifications are not complete yet, "
                "so compatibility cannot be checked."
            )
        return component


def items_to_parts(items: list[dict]) -> list[compatibility.Part]:
    return [
        compatibility.Part(
            id=item["component"].id,
            kind=item["component"].kind,
            name=str(item["component"]),
            specs=item["component"].specs,
            quantity=item["quantity"],
        )
        for item in items
    ]


class CompatibilityCheckSerializer(serializers.Serializer):
    """Input of the stateless ``POST /compatibility/check/`` endpoint."""

    items = BuildItemWriteSerializer(many=True)

    def validate_items(self, items):
        return validate_unique_components(items)


def validate_unique_components(items: list[dict]) -> list[dict]:
    counts = Counter(item["component"].id for item in items)
    duplicates = sorted(cid for cid, n in counts.items() if n > 1)
    if duplicates:
        raise serializers.ValidationError(
            f"Components {duplicates} are listed more than once; use `quantity` instead."
        )
    return items


class BuildWriteSerializer(serializers.ModelSerializer):
    """Create/update a build together with its component list.

    Validation is layered on purpose:
    * field level  – each item references an active component, quantity 1..8;
    * ``validate_items`` – no duplicate components in one request;
    * ``validate`` – cross-field domain rules via the compatibility engine.
      This is the place for them: they depend on *all* items at once, which
      no single field validator can see;
    * database – unique (build, component) and the quantity range are also
      constraints, so a bug in this serializer cannot corrupt data.
    """

    items = BuildItemWriteSerializer(many=True, required=False)

    class Meta:
        model = Build
        fields = ["name", "description", "is_public", "items"]

    def validate_name(self, value: str) -> str:
        owner = self.context["request"].user
        qs = Build.objects.filter(owner=owner, name=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("You already have a build with this name.")
        return value

    def validate_items(self, items):
        return validate_unique_components(items)

    def validate(self, attrs):
        items = attrs.get("items")
        if items is not None:
            report = compatibility.check(items_to_parts(items))
            if not report.is_compatible:
                raise serializers.ValidationError(
                    {
                        "items": [issue.message for issue in report.errors],
                        "compatibility": report.as_dict(),
                    }
                )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])
        build = Build.objects.create(owner=self.context["request"].user, **validated_data)
        self._replace_items(build, items)
        return build

    @transaction.atomic
    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if items is not None:
            self._replace_items(instance, items)
        return instance

    @staticmethod
    def _replace_items(build: Build, items: list[dict]) -> None:
        build.build_components.all().delete()
        BuildComponent.objects.bulk_create(
            BuildComponent(build=build, component=item["component"], quantity=item["quantity"])
            for item in items
        )

    def to_representation(self, instance):
        fresh = Build.objects.with_parts().with_total_price().get(pk=instance.pk)
        return BuildDetailSerializer(fresh, context=self.context).data


# --- Read side --------------------------------------------------------------------


# Money is always a decimal *string* in the API (DRF's DecimalField default).
# A SerializerMethodField returning Decimal would be rendered as a JSON float,
# so the same "total_price" would be "735.00" in the list and 735.0 in the
# detail view. Found when the generated TypeScript types disagreed.


class BuildItemSerializer(serializers.ModelSerializer):
    component = ComponentBriefSerializer(read_only=True)
    line_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = BuildComponent
        fields = ["id", "component", "quantity", "line_total"]


class BuildListSerializer(serializers.ModelSerializer):
    owner = serializers.CharField(source="owner.username", read_only=True)
    total_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    parts_count = serializers.IntegerField(read_only=True)
    comments_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Build
        fields = [
            "id",
            "name",
            "description",
            "owner",
            "is_public",
            "total_price",
            "parts_count",
            "comments_count",
            "created_at",
            "updated_at",
        ]


class BuildDetailSerializer(serializers.ModelSerializer):
    owner = serializers.CharField(source="owner.username", read_only=True)
    items = BuildItemSerializer(source="build_components", many=True, read_only=True)
    # Requires Build.objects.with_total_price(); every detail queryset uses it.
    total_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    compatibility = serializers.SerializerMethodField()

    class Meta:
        model = Build
        fields = [
            "id",
            "name",
            "description",
            "owner",
            "is_public",
            "items",
            "total_price",
            "compatibility",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(CompatibilityReportSerializer)
    def get_compatibility(self, obj: Build) -> dict:
        return obj.compatibility_report().as_dict()


class CommentSerializer(serializers.ModelSerializer):
    author = serializers.CharField(source="author.username", read_only=True)

    class Meta:
        model = Comment
        fields = ["id", "build", "author", "text", "created_at"]
        read_only_fields = ["build"]

    def validate_text(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Comment cannot be empty.")
        return value
