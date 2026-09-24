import django_filters
from django.db.models import Exists, OuterRef

from .models import Build, BuildComponent


class BuildFilter(django_filters.FilterSet):
    mine = django_filters.BooleanFilter(method="filter_mine")
    owner = django_filters.CharFilter(field_name="owner__username")
    component = django_filters.NumberFilter(
        method="filter_component", label="Only builds that contain this component id."
    )
    min_total = django_filters.NumberFilter(field_name="total_price", lookup_expr="gte")
    max_total = django_filters.NumberFilter(field_name="total_price", lookup_expr="lte")

    class Meta:
        model = Build
        fields = ["is_public"]

    def filter_mine(self, queryset, name, value):
        user = self.request.user
        if value and user.is_authenticated:
            return queryset.filter(owner=user)
        return queryset

    def filter_component(self, queryset, name, value):
        # EXISTS instead of .filter(build_components__component=value):
        # a plain join filter would be reused by the total_price Sum()
        # annotation, and the "total" would become the price of this one
        # component. See test_total_price_not_affected_by_component_filter.
        return queryset.filter(
            Exists(BuildComponent.objects.filter(build=OuterRef("pk"), component_id=value))
        )
