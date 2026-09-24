import logging
import time

from django.core.management.base import BaseCommand, CommandError

from apps.alerts import telegram
from apps.alerts.bot import handle_update

logger = logging.getLogger(__name__)

COMMANDS = {
    "uk": [
        {"command": "list", "description": "За чим я стежу"},
        {"command": "stop", "description": "Вимкнути сповіщення"},
        {"command": "on", "description": "Увімкнути сповіщення"},
    ],
    "en": [
        {"command": "list", "description": "What I watch"},
        {"command": "stop", "description": "Pause alerts"},
        {"command": "on", "description": "Resume alerts"},
    ],
}


class Command(BaseCommand):
    help = (
        "Run the Telegram bot with long polling: links chats to accounts (/start <token>) and "
        "answers /list, /stop, /on and the 'stop watching' buttons. No public URL is needed."
    )

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process one batch and exit.")

    def handle(self, *args, once=False, **options):
        if not telegram.configured():
            # Without a token the bot is simply off. Idle instead of exiting, so the
            # container counts as running (docker compose up --wait, restarts).
            self.stdout.write("TELEGRAM_BOT_TOKEN is not set; the Telegram bot is disabled.")
            if once:
                return
            while True:
                time.sleep(3600)
        # Polling and a webhook are mutually exclusive in the Bot API.
        telegram.call("deleteWebhook")
        telegram.call("setMyCommands", commands=COMMANDS["en"])
        telegram.call("setMyCommands", commands=COMMANDS["uk"], language_code="uk")
        self.stdout.write(f"@{telegram.bot_username()} is listening. Ctrl+C to stop.")
        offset = None
        while True:
            try:
                updates = telegram.call(
                    "getUpdates",
                    http_timeout=40,  # must outlast the 25 s long poll
                    timeout=0 if once else 25,
                    offset=offset,
                    allowed_updates=["message", "callback_query"],
                )
            except telegram.TelegramError as exc:
                logger.warning("getUpdates failed: %s", exc)
                if once:
                    raise CommandError(str(exc)) from exc
                time.sleep(10 if exc.code == 409 else 3)  # 409: another instance is polling
                continue
            for update in updates or []:
                offset = update["update_id"] + 1
                try:
                    handle_update(update)
                except Exception:  # one bad update must not stop the bot
                    logger.exception("Update %s failed", update.get("update_id"))
            if once:
                return
