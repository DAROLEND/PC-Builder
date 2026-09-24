import logging

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import InvalidTransition, Order, OrderStatus
from .payments import PaymentError, StripeProvider
from .serializers import (
    OrderCreateSerializer,
    OrderSerializer,
    PaymentSessionSerializer,
    StatusChangeSerializer,
)
from .services import change_status, create_order_from_build, start_payment

logger = logging.getLogger(__name__)


class OrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OrderSerializer
    filterset_fields = ["status"]

    def get_queryset(self):
        qs = Order.objects.prefetch_related("items")
        if getattr(self, "swagger_fake_view", False):  # schema generation, no real user
            return qs.none()
        if self.request.user.is_staff:
            return qs
        return qs.filter(user=self.request.user)

    @extend_schema(request=OrderCreateSerializer, responses={201: OrderSerializer})
    def create(self, request, *args, **kwargs):
        serializer = OrderCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        order = create_order_from_build(user=request.user, **serializer.validated_data)
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=PaymentSessionSerializer)
    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        order = self.get_object()
        try:
            session = start_payment(order)
        except PaymentError as exc:
            logger.warning("Payment for order %s failed: %s", order.pk, exc)
            raise ValidationError({"payment": str(exc)}) from exc
        order.refresh_from_db()
        return Response(
            PaymentSessionSerializer(
                {
                    "provider": session.provider,
                    "checkout_url": session.checkout_url,
                    "confirmed": session.confirmed,
                    "order": order,
                }
            ).data
        )

    @extend_schema(request=None, responses=OrderSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        return Response(OrderSerializer(self._transition(order, OrderStatus.CANCELLED)).data)

    @extend_schema(request=StatusChangeSerializer, responses=OrderSerializer)
    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAdminUser])
    def advance(self, request, pk=None):
        """Staff only: move the order along (paid → shipped → delivered)."""
        order = self.get_object()
        serializer = StatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            OrderSerializer(self._transition(order, serializer.validated_data["status"])).data
        )

    @staticmethod
    def _transition(order: Order, target: str) -> Order:
        try:
            change_status(order.pk, target)
        except InvalidTransition as exc:
            raise ValidationError({"status": str(exc)}) from exc
        return Order.objects.prefetch_related("items").get(pk=order.pk)


class StripeWebhookView(APIView):
    """Stripe → us. Authenticated by the signature header, not by a user."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    @extend_schema(exclude=True)
    def post(self, request):
        try:
            event = StripeProvider().parse_webhook(
                request.body, request.headers.get("Stripe-Signature", "")
            )
        except PaymentError:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            order_id = (session.get("metadata") or {}).get("order_id")
            if order_id and session.get("payment_status") == "paid":
                try:
                    change_status(int(order_id), OrderStatus.PAID)
                except (Order.DoesNotExist, InvalidTransition) as exc:
                    # Acknowledge anyway: retrying will not fix it, alert instead.
                    logger.error("Stripe webhook for order %s not applied: %s", order_id, exc)
        return Response({"received": True})
