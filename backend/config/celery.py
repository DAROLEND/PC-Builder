import logging
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("pcbuilder")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

logger = logging.getLogger(__name__)


def enqueue_best_effort(task, *args, **kwargs) -> bool:
    """Queue a fire-and-forget task (e-mails, notifications) without letting a
    broker outage fail the request that triggered it.

    Typical call site is ``transaction.on_commit``: by then the payment or the
    comment is already committed, so raising here would turn a successful
    operation into a 500 for the client. Only use this for tasks whose loss is
    acceptable; anything that must happen belongs in the same transaction or in
    an outbox table.
    """
    try:
        task.apply_async(args=args, kwargs=kwargs, retry=False)
        return True
    except Exception:  # kombu, redis and socket errors share no common base class
        logger.exception("Could not enqueue %s%s", task.name, args)
        return False
