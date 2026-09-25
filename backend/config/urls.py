from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from django.views.static import serve
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from apps.advisor.views import AdvisorView
from apps.alerts.views import TelegramLinkView, TelegramView, WatchViewSet
from apps.builds.views import BuildViewSet, CommentViewSet, CompatibilityCheckView
from apps.catalog.db_storage import serve_stored_file
from apps.catalog.views import (
    CategoryViewSet,
    ComponentViewSet,
    ExchangeRateViewSet,
    ManufacturerViewSet,
)
from apps.orders.views import OrderViewSet, StripeWebhookView

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("manufacturers", ManufacturerViewSet, basename="manufacturer")
router.register("components", ComponentViewSet, basename="component")
router.register("exchange-rates", ExchangeRateViewSet, basename="exchange-rate")
router.register("builds", BuildViewSet, basename="build")
router.register("comments", CommentViewSet, basename="comment")
router.register("orders", OrderViewSet, basename="order")
router.register("watches", WatchViewSet, basename="watch")


def health(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    # The React app is served separately; someone opening the API host sees the docs.
    path("", RedirectView.as_view(pattern_name="swagger-ui")),
    path("admin/", admin.site.urls),
    path("health/", health),
    path("api/", include(router.urls)),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/stats/", include("apps.stats.urls")),
    path("api/compatibility/check/", CompatibilityCheckView.as_view(), name="compatibility-check"),
    path("api/advisor/", AdvisorView.as_view(), name="advisor"),
    path("api/telegram/", TelegramView.as_view(), name="telegram"),
    path("api/telegram/link/", TelegramLinkView.as_view(), name="telegram-link"),
    path("api/payments/stripe/webhook/", StripeWebhookView.as_view(), name="stripe-webhook"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]


# Mirrored product photos. Served by Django here for simplicity: files are small
# (WebP thumbnails) and immutable. At scale they would go to S3 + a CDN.
if settings.MEDIA_STORAGE == "db":
    urlpatterns += [re_path(r"^media/(?P<path>.+)$", serve_stored_file, name="media")]
else:
    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$",
            serve,
            {"document_root": settings.MEDIA_ROOT},
            name="media",
        ),
    ]
