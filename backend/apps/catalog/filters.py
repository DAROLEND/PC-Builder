import django_filters
from rest_framework.exceptions import ValidationError

from apps.builds.compatibility import MAX_QUANTITY, Part

from .compat_query import compatible_q
from .models import CategoryKind, Component


def parse_id_list(raw: str, param: str) -> list[int]:
    try:
        return [int(x) for x in raw.split(",") if x.strip()]
    except ValueError as exc:
        raise ValidationError({param: "Expected a comma-separated list of ids."}) from exc


class ComponentFilter(django_filters.FilterSet):
    category = django_filters.ChoiceFilter(
        field_name="category__kind", choices=CategoryKind.choices
    )
    manufacturer = django_filters.CharFilter(field_name="manufacturer__slug")
    min_price = django_filters.NumberFilter(field_name="price", lookup_expr="gte")
    max_price = django_filters.NumberFilter(field_name="price", lookup_expr="lte")
    socket = django_filters.CharFilter(method="filter_spec")
    memory_type = django_filters.CharFilter(method="filter_spec")
    form_factor = django_filters.CharFilter(method="filter_spec")
    buildable = django_filters.BooleanFilter(
        field_name="specs_complete",
        label="Only parts with complete specs (usable in the configurator).",
    )
    compatible_with = django_filters.CharFilter(
        method="filter_compatible_with",
        label="Comma-separated component ids; requires `category`.",
    )

    class Meta:
        model = Component
        fields = ["category", "manufacturer", "is_active"]

    def filter_spec(self, queryset, name, value):
        # Containment query → uses the GIN index on specs.
        return queryset.filter(specs__contains={name: value})

    def filter_compatible_with(self, queryset, name, value):
        kind = self.data.get("category")
        if not kind:
            raise ValidationError({"compatible_with": "The `category` parameter is required."})
        ids = parse_id_list(value, "compatible_with")
        selected = Component.objects.with_related().filter(id__in=ids)
        parts = [
            Part(id=comp.id, kind=comp.kind, name=str(comp), specs=comp.specs)
            for comp in selected
            # When choosing a CPU, the currently selected CPU is being replaced,
            # so it must not constrain the result. Multi-unit slots (RAM, GPU,
            # storage) keep their siblings: new RAM must match existing RAM.
            if comp.kind != kind or MAX_QUANTITY[kind] > 1
        ]
        return queryset.filter(specs_complete=True).filter(compatible_q(kind, parts))
