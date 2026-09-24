from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.catalog.models import Component


class OrderStatus(models.TextChoices):
    PENDING = "pending", "Awaiting payment"
    PAID = "paid", "Paid"
    SHIPPED = "shipped", "Shipped"
    DELIVERED = "delivered", "Delivered"
    CANCELLED = "cancelled", "Cancelled"


# The only allowed moves. Everything else (e.g. delivered → pending) is rejected.
TRANSITIONS: dict[str, set[str]] = {
    OrderStatus.PENDING: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
}


class InvalidTransition(Exception):
    def __init__(self, current: str, target: str):
        super().__init__(f"Cannot change order status from '{current}' to '{target}'.")
        self.current, self.target = current, target


class Order(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders"
    )
    # The build may be edited or deleted later; the order keeps its own snapshot
    # of items and prices, so this link is informational only.
    build = models.ForeignKey(
        "builds.Build", on_delete=models.SET_NULL, null=True, blank=True, related_name="orders"
    )
    status = models.CharField(
        max_length=16, choices=OrderStatus.choices, default=OrderStatus.PENDING, db_index=True
    )
    total = models.DecimalField(max_digits=12, decimal_places=2)
    shipping_address = models.TextField()
    payment_provider = models.CharField(max_length=16, blank=True)
    payment_reference = models.CharField(max_length=255, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(total__gte=0), name="order_total_non_negative"),
            # A paid-ish order must have a payment timestamp.
            models.CheckConstraint(
                condition=Q(status__in=["pending", "cancelled"]) | Q(paid_at__isnull=False),
                name="order_paid_has_paid_at",
            ),
        ]

    def __str__(self) -> str:
        return f"Order #{self.pk} ({self.status})"

    def can_transition_to(self, target: str) -> bool:
        return target in TRANSITIONS[self.status]

    def transition_to(self, target: str) -> None:
        """Change status in memory; the caller saves inside a locked transaction."""
        if not self.can_transition_to(target):
            raise InvalidTransition(self.status, target)
        if target == OrderStatus.PAID:
            self.paid_at = timezone.now()
        self.status = target


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    component = models.ForeignKey(Component, on_delete=models.PROTECT, related_name="order_items")
    # Snapshot at checkout time: later price or name changes must not alter the order.
    component_name = models.CharField(max_length=200)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gte=1), name="order_item_quantity_positive"
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0), name="order_item_price_non_negative"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.quantity} × {self.component_name}"

    @property
    def line_total(self):
        return self.unit_price * self.quantity
