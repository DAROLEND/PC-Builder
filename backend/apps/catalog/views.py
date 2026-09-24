from datetime import timedelta

from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.response import Response

from .filters import ComponentFilter
from .market import FETCH_DISABLED, Fetcher, fetching_enabled
from .market_service import refresh_listing
from .models import Category, Component, ExchangeRate, Manufacturer, MarketListing
from .ordering import NullsLastOrderingFilter
from .serializers import (
    CategorySerializer,
    ComponentSerializer,
    ExchangeRateSerializer,
    ListingCreateSerializer,
    ListingSerializer,
    ManufacturerSerializer,
    PriceHistorySerializer,
)


class IsStaffOrReadOnly(permissions.BasePermission):
    """Anyone can browse the catalog; only staff can change it."""

    def has_permission(self, request, view):
        return request.method in permissions.SAFE_METHODS or bool(
            request.user and request.user.is_staff
        )


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    pagination_class = None
    lookup_field = "slug"


class ManufacturerViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Manufacturer.objects.all()
    serializer_class = ManufacturerSerializer
    pagination_class = None
    lookup_field = "slug"


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                "compatible_with",
                OpenApiTypes.STR,
                description=(
                    "Comma-separated ids of already selected components. Only parts "
                    "compatible with them are returned. Requires `category`."
                ),
            )
        ]
    )
)
class ComponentViewSet(viewsets.ModelViewSet):
    serializer_class = ComponentSerializer
    permission_classes = [IsStaffOrReadOnly]
    filterset_class = ComponentFilter
    search_fields = ["name", "manufacturer__name", "sku"]
    ordering_fields = ["price", "name", "updated_at", "popularity", "price_change_30d"]
    filter_backends = [DjangoFilterBackend, SearchFilter, NullsLastOrderingFilter]
    lookup_field = "slug"

    def get_queryset(self):
        qs = Component.objects.with_market()
        if not (self.request.user and self.request.user.is_staff):
            qs = qs.active()
            # Browsing shows only parts with a real market; a part page stays
            # reachable (existing builds link to it).
            if self.action == "list":
                qs = qs.listed()
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["uah_rate"] = ExchangeRate.latest_uah_rate()
        return context

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "days",
                OpenApiTypes.INT,
                description="Only the last N days (e.g. 30, 90, 180, 365). Default: everything.",
            )
        ],
        responses=PriceHistorySerializer(many=True),
    )
    @action(detail=True, methods=["get"], url_path="price-history", pagination_class=None)
    def price_history(self, request, slug=None):
        """Daily price points, oldest first: typical (median) price and the day's range."""
        component = self.get_object()
        rows = component.price_history.order_by("recorded_at")
        days = request.query_params.get("days")
        if days:
            try:
                days = max(1, min(int(days), 3660))
            except ValueError:
                return Response({"days": ["Must be a whole number of days."]}, status=400)
            rows = rows.filter(recorded_at__gte=timezone.now() - timedelta(days=days))
        return Response(PriceHistorySerializer(rows[:1000], many=True).data)

    @extend_schema(request=ListingCreateSerializer, responses={201: ListingSerializer})
    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAdminUser])
    def listings(self, request, slug=None):
        """Staff: attach a product page URL. It is fetched right away, so the
        response already contains the title, price and photos found there."""
        if not fetching_enabled():
            return Response({"detail": FETCH_DISABLED}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        component = self.get_object()
        serializer = ListingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        listing = MarketListing.objects.create(
            component=component, url=serializer.validated_data["url"]
        )
        refresh_listing(listing, Fetcher(min_interval=0), ExchangeRate.latest_uah_rate())
        return Response(ListingSerializer(listing).data, status=status.HTTP_201_CREATED)


class ExchangeRateViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ExchangeRate.objects.all()
    serializer_class = ExchangeRateSerializer

    @extend_schema(responses=ExchangeRateSerializer)
    @action(detail=False, methods=["get"])
    def latest(self, request):
        row = ExchangeRate.objects.filter(currency="USD").order_by("-rate_date").first()
        if row is None:
            return Response({"detail": "No exchange rate loaded yet."}, status=404)
        return Response(ExchangeRateSerializer(row).data)
