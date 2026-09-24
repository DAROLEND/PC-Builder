from rest_framework.filters import OrderingFilter


class NullsLastOrderingFilter(OrderingFilter):
    """``?ordering=-popularity`` with parts that have no data at the end.

    PostgreSQL sorts NULL as the largest value, so a plain descending order
    would put every part without market statistics first.
    """

    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)
        if not ordering:
            return queryset
        from django.db.models import F

        terms = [
            F(field[1:]).desc(nulls_last=True)
            if field.startswith("-")
            else F(field).asc(nulls_last=True)
            for field in ordering
        ]
        return queryset.order_by(*terms, "id")
