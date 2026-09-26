import hmac
import json
import logging

from django.conf import settings
from django.core.cache import cache
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from . import telegram
from .bot import handle_update
from .models import LINK_TOKEN_TTL, TelegramLink, Watch
from .serializers import (
    TelegramLinkRequestSerializer,
    TelegramLinkResponseSerializer,
    TelegramStatusSerializer,
    WatchSerializer,
)

logger = logging.getLogger(__name__)


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("component", OpenApiTypes.INT, description="Only this part."),
            OpenApiParameter("build", OpenApiTypes.INT, description="Only this build."),
        ]
    )
)
class WatchViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """The user's own price watches. Filter with ``?component=<id>`` or ``?build=<id>``."""

    serializer_class = WatchSerializer
    queryset = Watch.objects.none()  # for the schema; get_queryset() scopes to the user
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        qs = (
            Watch.objects.filter(user=self.request.user)
            .select_related("component__manufacturer", "component__category", "build")
            .prefetch_related("component__photos", "component__listings")
        )
        for field in ("component", "build"):
            value = self.request.query_params.get(field)
            if value and value.isdigit():
                qs = qs.filter(**{f"{field}_id": int(value)})
        return qs


def _link_for(user) -> TelegramLink:
    link, _ = TelegramLink.objects.get_or_create(user=user)
    return link


class TelegramView(APIView):
    """Connection of the account to the Telegram bot."""

    permission_classes = [permissions.IsAuthenticated]

    def _response(self, link: TelegramLink, code=status.HTTP_200_OK) -> Response:
        context = {"bot_username": telegram.bot_username()}
        return Response(TelegramStatusSerializer(link, context=context).data, status=code)

    @extend_schema(responses=TelegramStatusSerializer)
    def get(self, request):
        return self._response(_link_for(request.user))

    @extend_schema(request=TelegramStatusSerializer, responses=TelegramStatusSerializer)
    def patch(self, request):
        link = _link_for(request.user)
        serializer = TelegramStatusSerializer(link, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self._response(link)

    @extend_schema(responses={204: None})
    def delete(self, request):
        """Disconnect the chat (the watches stay)."""
        TelegramLink.objects.filter(user=request.user).update(
            chat_id=None, username="", linked_at=None, link_token=None, token_created_at=None
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class TelegramLinkView(APIView):
    """Issue a one-time ``t.me/<bot>?start=<code>`` link (valid for 30 minutes)."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=TelegramLinkRequestSerializer, responses=TelegramLinkResponseSerializer)
    def post(self, request):
        name = telegram.bot_username()
        if not name:
            return Response(
                {"detail": "The Telegram bot is not configured on this server."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        serializer = TelegramLinkRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        link = _link_for(request.user)
        link.language = serializer.validated_data["language"]
        link.save(update_fields=["language"])
        token = link.issue_token()
        return Response(
            {
                "url": f"https://t.me/{name}?start={token}",
                "expires_in": int(LINK_TOKEN_TTL.total_seconds()),
            }
        )


class TelegramWebhookView(APIView):
    """Telegram → us: the webhook alternative to ``run_telegram_bot``'s long polling.

    Authenticated by the secret registered with ``setWebhook``, not by a user.
    Always answers 200 once the secret matches: Telegram retries anything else,
    and a retried update that failed once would fail again.
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    @extend_schema(exclude=True)
    def post(self, request):
        if not (settings.TELEGRAM_WEBHOOK and telegram.configured()):
            return Response(status=status.HTTP_404_NOT_FOUND)
        received = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(received, telegram.webhook_secret()):
            return Response(status=status.HTTP_403_FORBIDDEN)
        try:
            update = json.loads(request.body)
        except ValueError:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        # A cold start can outlast Telegram's timeout, and then the same update
        # arrives twice; answer it once.
        update_id = update.get("update_id")
        if update_id is not None and not cache.add(f"telegram:update:{update_id}", 1, 24 * 3600):
            return Response({"ok": True})
        try:
            handle_update(update)
        except Exception:
            logger.exception("Update %s failed", update_id)
        return Response({"ok": True})
