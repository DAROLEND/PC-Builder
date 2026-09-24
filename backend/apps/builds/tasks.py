import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from .models import Comment

logger = logging.getLogger(__name__)


@shared_task(autoretry_for=(OSError,), retry_backoff=30, retry_kwargs={"max_retries": 3})
def notify_build_owner_about_comment(comment_id: int) -> bool:
    comment = Comment.objects.select_related("build__owner", "author").filter(pk=comment_id).first()
    if comment is None:  # deleted before the worker got to it
        return False
    owner = comment.build.owner
    if not owner.email:
        return False
    send_mail(
        subject=f"New comment on your build “{comment.build.name}”",
        message=(
            f"{comment.author.username} wrote:\n\n{comment.text}\n\n"
            f"{settings.FRONTEND_URL}/builds/{comment.build_id}"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[owner.email],
    )
    logger.info("Notified %s about comment %s", owner.username, comment_id)
    return True
