import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.alerts import telegram
from apps.alerts.bot import COMMANDS

WEBHOOK_PATH = "/api/telegram/webhook/"


class Command(BaseCommand):
    help = (
        "Point the Telegram bot at this site's webhook (TELEGRAM_WEBHOOK=1) instead of "
        "long polling. The URL defaults to Render's RENDER_EXTERNAL_URL; safe to rerun."
    )

    def add_arguments(self, parser):
        parser.add_argument("--url", help=f"Public base URL of the API (…{WEBHOOK_PATH} is added).")

    def handle(self, *args, url=None, **options):
        if not telegram.configured():
            self.stdout.write("TELEGRAM_BOT_TOKEN is not set; nothing to do.")
            return
        if not settings.TELEGRAM_WEBHOOK:
            raise CommandError("Set TELEGRAM_WEBHOOK=1, or the site will refuse the updates.")
        base = url or os.environ.get("RENDER_EXTERNAL_URL")
        if not base:
            raise CommandError("Pass --url https://<api host>.")
        if not base.startswith("https://"):
            raise CommandError("Telegram delivers webhooks over HTTPS only.")
        telegram.call(
            "setWebhook",
            url=base.rstrip("/") + WEBHOOK_PATH,
            secret_token=telegram.webhook_secret(),
            allowed_updates=["message", "callback_query"],
        )
        telegram.call("setMyCommands", commands=COMMANDS["en"])
        telegram.call("setMyCommands", commands=COMMANDS["uk"], language_code="uk")
        self.stdout.write(f"@{telegram.bot_username()} receives updates at {base}{WEBHOOK_PATH}")
