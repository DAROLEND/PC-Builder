import logging

from celery import shared_task

from .service import check_watches

logger = logging.getLogger(__name__)


@shared_task(soft_time_limit=10 * 60)
def check_price_watches() -> dict[str, int]:
    """Send Telegram price alerts. Queued after each market refresh and hourly
    (so alerts held back by quiet hours go out in the morning)."""
    stats = check_watches()
    logger.info("Price watches: %s", stats)
    return stats
