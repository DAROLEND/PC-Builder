"""What the bot does with incoming Telegram updates.

Kept free of any polling/webhook code so it can be tested with plain dicts and
reused by either delivery method.
"""

from __future__ import annotations

import contextlib
import html
import logging

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import ExchangeRate

from . import telegram
from .models import TelegramLink, Watch
from .service import current_price, money, public, site_url, watch_path, watch_title

logger = logging.getLogger(__name__)

TEXTS = {
    "uk": {
        "linked": (
            "✅ Готово, {user}! Тепер я писатиму сюди, коли товари й збірки, за якими ти "
            "стежиш на PC Builder, подешевшають або подорожчають.\n\n"
            "/list — за чим стежиш\n/stop — вимкнути сповіщення\n/on — увімкнути знову"
        ),
        "hello": (
            "👋 Я повідомляю про зміну цін на PC Builder.\n\n"
            "Щоб підключити сповіщення, відкрий на сайті профіль і натисни "
            "«Підключити Telegram»:\n{url}"
        ),
        "expired": (
            "⌛ Посилання застаріло. Натисни «Підключити Telegram» у профілі ще раз:\n{url}"
        ),
        "not_linked": "Цей чат ще не підключено. Відкрий профіль на сайті:\n{url}",
        "empty": (
            "Ти поки ні за чим не стежиш. Натисни «Стежити за ціною» на сторінці товару або збірки."
        ),
        "list_head": "👀 Стежу за ціною ({count}):",
        "list_item": "• <b>{name}</b> — {price}{target}",
        "target": ", ціль {target}",
        "stopped": "🔕 Сповіщення вимкнено. /on — увімкнути знову.",
        "resumed": "🔔 Сповіщення знову увімкнено.",
        "unwatched": "Більше не стежу",
        "unknown": "Не зрозумів. Є команди /list, /stop, /on.",
    },
    "en": {
        "linked": (
            "✅ Done, {user}! I will message you here when parts and builds you watch on "
            "PC Builder get cheaper or more expensive.\n\n"
            "/list — what you watch\n/stop — pause alerts\n/on — resume"
        ),
        "hello": (
            "👋 I send price alerts for PC Builder.\n\n"
            "To connect, open your profile on the site and press “Connect Telegram”:\n{url}"
        ),
        "expired": (
            "⌛ The link has expired. Press “Connect Telegram” in your profile again:\n{url}"
        ),
        "not_linked": "This chat is not connected yet. Open your profile on the site:\n{url}",
        "empty": "You are not watching anything yet. Press “Watch price” on a part or build page.",
        "list_head": "👀 Watching ({count}):",
        "list_item": "• <b>{name}</b> — {price}{target}",
        "target": ", target {target}",
        "stopped": "🔕 Alerts paused. /on to resume.",
        "resumed": "🔔 Alerts are on again.",
        "unwatched": "Stopped watching",
        "unknown": "Sorry, I don't get it. Try /list, /stop or /on.",
    },
}


def language_of(user_language: str | None) -> str:
    """Telegram's language_code of the sender -> our message language."""
    return "uk" if (user_language or "").lower().startswith(("uk", "ru")) else "en"


def handle_update(update: dict) -> None:
    if "callback_query" in update:
        handle_callback(update["callback_query"])
        return
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    text = (message.get("text") or "").strip()
    if chat.get("type") != "private" or not text.startswith("/"):
        return  # only direct chats; ignore groups and plain text
    chat_id = chat["id"]
    sender = message.get("from") or {}
    command, _, argument = text.partition(" ")
    command = command.split("@")[0].lower()  # "/list@pcbuilder_bot" in some clients
    link = TelegramLink.objects.select_related("user").filter(chat_id=chat_id).first()
    language = link.language if link else language_of(sender.get("language_code"))
    texts = TEXTS[language]
    profile = site_url("/profile")

    if command == "/start":
        if argument:
            reply = link_chat(argument.strip(), chat_id, sender)
        else:
            reply = texts["hello"].format(url=profile) if not link else texts["resumed"]
            if link and not link.enabled:
                TelegramLink.objects.filter(pk=link.pk).update(enabled=True)
    elif link is None:
        reply = texts["not_linked"].format(url=profile)
    elif command == "/list":
        reply = watch_list(link)
    elif command == "/stop":
        TelegramLink.objects.filter(pk=link.pk).update(enabled=False)
        reply = texts["stopped"]
    elif command == "/on":
        TelegramLink.objects.filter(pk=link.pk).update(enabled=True)
        reply = texts["resumed"]
    else:
        reply = texts["unknown"]
    telegram.send_message(chat_id, reply)


@transaction.atomic
def link_chat(token: str, chat_id: int, sender: dict) -> str:
    link = (
        TelegramLink.objects.select_for_update()
        .select_related("user")
        .filter(link_token=token)
        .first()
    )
    fallback = TEXTS[language_of(sender.get("language_code"))]
    if link is None:
        return fallback["expired"].format(url=site_url("/profile"))
    if not link.token_valid():
        return TEXTS[link.language]["expired"].format(url=site_url("/profile"))
    # One chat belongs to one account: re-linking moves it here.
    TelegramLink.objects.filter(chat_id=chat_id).exclude(pk=link.pk).update(chat_id=None)
    link.chat_id = chat_id
    link.username = (sender.get("username") or sender.get("first_name") or "")[:64]
    link.enabled = True
    link.linked_at = timezone.now()
    link.link_token = None
    link.token_created_at = None
    link.save()
    return TEXTS[link.language]["linked"].format(user=html.escape(link.user.username))


def watch_list(link: TelegramLink) -> str:
    texts = TEXTS[link.language]
    watches = list(
        Watch.objects.filter(user=link.user).select_related("component__manufacturer", "build")
    )
    if not watches:
        return texts["empty"]
    rate = ExchangeRate.latest_uah_rate()
    lines = [texts["list_head"].format(count=len(watches))]
    for watch in watches[:30]:
        price = current_price(watch)
        target = (
            texts["target"].format(target=money(watch.target_price, link.language, rate))
            if watch.target_price
            else ""
        )
        name = html.escape(watch_title(watch, link.language))
        url = site_url(watch_path(watch))
        if public(url):
            name = f'<a href="{html.escape(url)}">{name}</a>'
        lines.append(
            texts["list_item"].format(
                name=name,
                price=money(price, link.language, rate) if price is not None else "—",
                target=target,
            )
        )
    return "\n".join(lines)


def handle_callback(query: dict) -> None:
    data = query.get("data") or ""
    chat_id = ((query.get("message") or {}).get("chat") or {}).get("id")
    link = TelegramLink.objects.filter(chat_id=chat_id).first() if chat_id else None
    language = link.language if link else "en"
    if data.startswith("unwatch:") and link is not None:
        watch_id = data.split(":", 1)[1]
        if watch_id.isdigit():
            # Only the chat's own account can drop its watches.
            Watch.objects.filter(pk=int(watch_id), user_id=link.user_id).delete()
        telegram.call(
            "answerCallbackQuery",
            callback_query_id=query["id"],
            text=TEXTS[language]["unwatched"],
        )
        message = query.get("message") or {}
        if message.get("message_id"):
            # The message may be too old to edit; the watch is gone anyway.
            with contextlib.suppress(telegram.TelegramError):
                telegram.call(
                    "editMessageReplyMarkup",
                    chat_id=chat_id,
                    message_id=message["message_id"],
                    reply_markup={"inline_keyboard": []},
                )
        return
    telegram.call("answerCallbackQuery", callback_query_id=query["id"])
