import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import InvalidTransition, Order, OrderStatus

logger = logging.getLogger(__name__)


@shared_task(autoretry_for=(OSError,), retry_backoff=30, retry_kwargs={"max_retries": 3})
def send_order_status_email(order_id: int) -> bool:
    order = Order.objects.select_related("user").filter(pk=order_id).first()
    if order is None or not order.user.email:
        return False
    send_mail(
        subject=f"Order #{order.pk}: {order.get_status_display()}",
        message=f"Your order #{order.pk} is now “{order.get_status_display()}”.\n"
        f"{settings.FRONTEND_URL}/orders/{order.pk}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[order.user.email],
    )
    return True


@shared_task
def expire_unpaid_orders() -> int:
    """Cancel orders that stayed unpaid longer than UNPAID_ORDER_TTL_HOURS."""
    from .services import change_status  # services imports this module

    cutoff = timezone.now() - timedelta(hours=settings.UNPAID_ORDER_TTL_HOURS)
    expired = 0
    for order_id in Order.objects.filter(
        status=OrderStatus.PENDING, created_at__lt=cutoff
    ).values_list("id", flat=True):
        try:
            change_status(order_id, OrderStatus.CANCELLED, expected=OrderStatus.PENDING)
            expired += 1
        except InvalidTransition:
            # Paid by a webhook between the SELECT and the lock — that's fine.
            continue
    if expired:
        logger.info("Cancelled %s unpaid orders", expired)
    return expired
