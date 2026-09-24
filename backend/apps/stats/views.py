"""Read-only analytics endpoints.

Each view is one query built with annotate/aggregate or window functions;
nothing is computed in Python loops.
"""

from django.db.models import Avg, Count, Exists, F, Max, Min, OuterRef, Q, Window
from django.db.models.functions import DenseRank, PercentRank, Rank, Round
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.builds.models import Build, BuildComponent
from apps.builds.serializers import BuildListSerializer
from apps.catalog.models import CategoryKind, Component

PUBLIC_USE = Q(build_components__build__is_public=True)


class CategoryStatsSerializer(serializers.Serializer):
    kind = serializers.CharField()
    name = serializers.CharField(source="category_name")
    components = serializers.IntegerField()
    avg_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    min_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    max_price = serializers.DecimalField(max_digits=10, decimal_places=2)


class PopularComponentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    kind = serializers.CharField()
    manufacturer = serializers.CharField()
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    build_count = serializers.IntegerField()
    rank = serializers.IntegerField(required=False)


class PricePositionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    price_rank = serializers.IntegerField()
    percentile = serializers.FloatField()


def popular_components():
    return (
        Component.objects.active()
        .annotate(
            build_count=Count("build_components__build", filter=PUBLIC_USE, distinct=True),
            # Not "kind": Component.kind is a read-only property.
            category_kind=F("category__kind"),
            manufacturer_name=F("manufacturer__name"),
        )
        .filter(build_count__gt=0)
    )


def serialize_popular(rows):
    return [
        {
            "id": c.id,
            "name": c.name,
            "slug": c.slug,
            "kind": c.category_kind,
            "manufacturer": c.manufacturer_name,
            "price": c.price,
            "build_count": c.build_count,
            "rank": getattr(c, "rank", None),
        }
        for c in rows
    ]


class CategoryStatsView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=CategoryStatsSerializer(many=True))
    def get(self, request):
        rows = (
            Component.objects.active()
            .values(kind=F("category__kind"), category_name=F("category__name"))
            .annotate(
                components=Count("id"),
                avg_price=Round(Avg("price"), 2),
                min_price=Min("price"),
                max_price=Max("price"),
            )
            .order_by("category__position")
        )
        return Response(CategoryStatsSerializer(rows, many=True).data)


class PopularComponentsView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter("limit", OpenApiTypes.INT, description="Default 10, max 50")],
        responses=PopularComponentSerializer(many=True),
    )
    def get(self, request):
        try:
            limit = min(int(request.query_params.get("limit", 10)), 50)
        except ValueError as exc:
            raise ValidationError({"limit": "Must be an integer."}) from exc
        rows = popular_components().order_by("-build_count", "price")[:limit]
        return Response(PopularComponentSerializer(serialize_popular(rows), many=True).data)


class TopPerCategoryView(APIView):
    """Top-N most used components *within each category* — a window function.

    ``RANK() OVER (PARTITION BY category ORDER BY build_count DESC)`` and then a
    filter on the window result (supported since Django 4.2, compiled into a
    subquery because SQL does not allow WHERE on window functions directly).
    """

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter("top", OpenApiTypes.INT, description="Default 3, max 10")],
        responses=PopularComponentSerializer(many=True),
    )
    def get(self, request):
        try:
            top = min(int(request.query_params.get("top", 3)), 10)
        except ValueError as exc:
            raise ValidationError({"top": "Must be an integer."}) from exc
        rows = (
            popular_components()
            .annotate(
                rank=Window(
                    Rank(),
                    partition_by=F("category_id"),
                    order_by=F("build_count").desc(),
                )
            )
            .filter(rank__lte=top)
            .order_by("category__position", "rank", "price")
        )
        return Response(PopularComponentSerializer(serialize_popular(rows), many=True).data)


class PricePositionView(APIView):
    """Where each component sits on the price ladder of its category."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter("category", OpenApiTypes.STR, required=True, enum=CategoryKind.values)
        ],
        responses=PricePositionSerializer(many=True),
    )
    def get(self, request):
        kind = request.query_params.get("category")
        if kind not in CategoryKind.values:
            raise ValidationError({"category": f"One of: {', '.join(CategoryKind.values)}."})
        rows = (
            Component.objects.active()
            .filter(category__kind=kind)
            .annotate(
                price_rank=Window(DenseRank(), order_by=F("price").asc()),
                percentile=Window(PercentRank(), order_by=F("price").asc()),
            )
            .order_by("price")
            .values("id", "name", "price", "price_rank", "percentile")
        )
        return Response(PricePositionSerializer(rows, many=True).data)


class CheapestBuildWithGpuView(APIView):
    """The cheapest public build that contains the given GPU."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter("gpu", OpenApiTypes.INT, required=True)],
        responses={200: BuildListSerializer, 404: None},
    )
    def get(self, request):
        try:
            gpu_id = int(request.query_params["gpu"])
        except (KeyError, ValueError) as exc:
            raise ValidationError({"gpu": "Component id is required."}) from exc

        # EXISTS keeps the total_price SUM over *all* lines of the build.
        has_gpu = Exists(
            BuildComponent.objects.filter(
                build=OuterRef("pk"), component_id=gpu_id, component__category__kind="gpu"
            )
        )
        build = (
            Build.objects.filter(is_public=True)
            .filter(has_gpu)
            .with_total_price()
            .select_related("owner")
            .order_by("total_price", "id")
            .first()
        )
        if build is None:
            return Response({"detail": "No public build uses this GPU."}, status=404)
        build.parts_count = sum(line.quantity for line in build.build_components.all())
        build.comments_count = build.comments.count()
        return Response(BuildListSerializer(build).data)
