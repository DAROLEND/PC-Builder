"""Minimal Telegram Bot API client (only the calls the bot uses)."""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

API = "https://api.telegram.org"
TIMEOUT = 15


class TelegramError(Exception):
    def __init__(self, code: int, description: str):
        super().__init__(f"{code}: {description}")
        self.code = code
        self.description = description

    @property
    def chat_gone(self) -> bool:
        """The user blocked the bot or deleted the chat: stop writing to it."""
        return self.code == 403 or "chat not found" in self.description.lower()


def configured() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN)


def call(method: str, *, http_timeout: float = TIMEOUT, **params: Any) -> Any:
    if not configured():
        raise TelegramError(0, "TELEGRAM_BOT_TOKEN is not set")
    url = f"{API}/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"
    try:
        response = requests.post(url, json=params, timeout=http_timeout)
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        # Never log the URL: it contains the token.
        raise TelegramError(0, f"{method}: {type(exc).__name__}") from exc
    if not payload.get("ok"):
        raise TelegramError(
            payload.get("error_code", response.status_code), payload.get("description", "")
        )
    return payload.get("result")


def send_message(chat_id: int, text: str, buttons: list[list[dict]] | None = None) -> Any:
    params: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }
    if buttons:
        params["reply_markup"] = {"inline_keyboard": buttons}
    return call("sendMessage", **params)


def bot_username() -> str | None:
    """The bot's @username, from settings or ``getMe`` (cached for a day)."""
    if settings.TELEGRAM_BOT_USERNAME:
        return settings.TELEGRAM_BOT_USERNAME
    if not configured():
        return None
    name = cache.get("telegram:bot_username")
    if name is None:
        try:
            name = call("getMe")["username"]
        except TelegramError as exc:
            logger.warning("getMe failed: %s", exc)
            return None
        cache.set("telegram:bot_username", name, 24 * 60 * 60)
    return name
