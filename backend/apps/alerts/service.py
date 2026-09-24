"""Deciding when a watch fires and what the message says."""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import datetime, time
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from apps.builds.models import Build
from apps.catalog.models import ExchangeRate

from . import telegram
from .models import TelegramLink, Watch

logger = logging.getLogger(__name__)

KYIV = ZoneInfo("Europe/Kyiv")
QUIET_FROM, QUIET_TO = time(22, 0), time(8, 0)


# --- Prices -----------------------------------------------------------------------------


def current_price(watch: Watch) -> Decimal | None:
    """USD price now: the component's, or the sum of the build's lines."""
    if watch.component_id:
        component = watch.component
        return component.price if component.is_active else None
    build = Build.objects.with_total_price().filter(pk=watch.build_id).first()
    return build.total_price if build else None


@dataclass(frozen=True)
class Trigger:
    kind: str  # "target" | "drop" | "rise"
    price: Decimal
    previous: Decimal
    percent: Decimal


def evaluate(watch: Watch, price: Decimal | None) -> Trigger | None:
    """Does the move from the baseline deserve a message?"""
    baseline = watch.baseline_price
    if price is None or not baseline:
        return None
    percent = ((price - baseline) / baseline * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)
    target = watch.target_price
    # Crossing the target is news even if the move is smaller than the threshold.
    if target is not None and price <= target < baseline:
        return Trigger("target", price, baseline, percent)
    if abs(percent) >= watch.threshold_percent:
        return Trigger("drop" if percent < 0 else "rise", price, baseline, percent)
    return None


def in_quiet_hours(moment: datetime) -> bool:
    local = timezone.localtime(moment, KYIV).time()
    return local >= QUIET_FROM or local < QUIET_TO


# --- Messages ----------------------------------------------------------------------------

TEXTS = {
    "uk": {
        "drop": "📉 <b>{name}</b> подешевша{ending} на {percent}%\n{price} (було {previous})",
        "rise": "📈 <b>{name}</b> подорожча{ending} на {percent}%\n{price} (було {previous})",
        "target": (
            "🎯 <b>{name}</b> досяг{reached} бажаної ціни\n"
            "{price} (ціль — {target}, було {previous})"
        ),
        "build": "Збірка «{name}»",
        "open": "Відкрити на сайті",
        "unwatch": "Більше не стежити",
    },
    "en": {
        "drop": "📉 <b>{name}</b> got {percent}% cheaper\n{price} (was {previous})",
        "rise": "📈 <b>{name}</b> got {percent}% more expensive\n{price} (was {previous})",
        "target": (
            "🎯 <b>{name}</b> reached your target price\n{price} (target {target}, was {previous})"
        ),
        "build": "Build “{name}”",
        "open": "Open on the site",
        "unwatch": "Stop watching",
    },
}


def money(usd: Decimal, language: str, uah_rate: Decimal | None) -> str:
    if language == "uk" and uah_rate:
        value = (usd * uah_rate).quantize(Decimal(1), ROUND_HALF_UP)
        return f"{value:,.0f} ₴".replace(",", " ")
    return f"${usd:,.2f}"


def percent_text(percent: Decimal, language: str) -> str:
    """10.0 -> "10", 7.5 -> "7.5" / "7,5" (Decimal.normalize() would give "1E+1")."""
    text = f"{abs(percent):.1f}".removesuffix(".0")
    return text.replace(".", ",") if language == "uk" else text


def site_url(path: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}{path}"


def public(url: str) -> bool:
    """Telegram refuses buttons that point at localhost; show the link as text then."""
    host = urlsplit(url).hostname or ""
    return host not in {"localhost", "127.0.0.1", "0.0.0.0"} and not host.endswith(".local")


def watch_title(watch: Watch, language: str) -> str:
    if watch.component_id:
        return f"{watch.component.manufacturer.name} {watch.component.name}"
    return TEXTS[language]["build"].format(name=watch.build.name)


def watch_path(watch: Watch) -> str:
    if watch.component_id:
        return f"/catalog/{watch.component.slug}"
    return f"/builds/{watch.build_id}"


def render(watch: Watch, trigger: Trigger, language: str, uah_rate: Decimal | None):
    texts = TEXTS[language]
    title = watch_title(watch, language)
    # "Процесор подешевшав" / "Збірка подешевшала": Ukrainian past tense agrees in gender.
    feminine = language == "uk" and bool(watch.build_id)
    ending, reached = ("ла", "ла") if feminine else ("в", "")
    text = texts[trigger.kind].format(
        name=html.escape(title),
        ending=ending,
        reached=reached,
        percent=percent_text(trigger.percent, language),
        price=money(trigger.price, language, uah_rate),
        previous=money(trigger.previous, language, uah_rate),
        target=money(watch.target_price, language, uah_rate) if watch.target_price else "",
    )
    url = site_url(watch_path(watch))
    buttons: list[list[dict]] = []
    if public(url):
        buttons.append([{"text": texts["open"], "url": url}])
    else:
        text += f"\n{html.escape(url)}"
    buttons.append([{"text": texts["unwatch"], "callback_data": f"unwatch:{watch.pk}"}])
    return text, buttons


# --- The periodic check ---------------------------------------------------------------------


def check_watches(now: datetime | None = None) -> dict[str, int]:
    """Send alerts for watches whose price moved enough. Returns counters.

    Runs after every market refresh. The baseline moves only when a message is
    actually delivered, so an alert held back by quiet hours or a Telegram
    outage is sent on a later run instead of being lost.
    """
    now = now or timezone.now()
    stats = {"checked": 0, "sent": 0, "held": 0, "failed": 0}
    if not telegram.configured():
        return stats
    uah_rate = ExchangeRate.latest_uah_rate()
    watches = (
        Watch.objects.filter(user__telegram__chat_id__isnull=False, user__telegram__enabled=True)
        .select_related("user__telegram", "component__manufacturer", "build")
        .order_by("user_id", "id")
    )
    gone: set[int] = set()  # users who blocked the bot during this run
    for watch in watches:
        if watch.user_id in gone:
            continue
        stats["checked"] += 1
        link: TelegramLink = watch.user.telegram
        trigger = evaluate(watch, current_price(watch))
        if trigger is None:
            continue
        if link.quiet_hours and in_quiet_hours(now):
            stats["held"] += 1
            continue
        text, buttons = render(watch, trigger, link.language, uah_rate)
        try:
            telegram.send_message(link.chat_id, text, buttons)
        except telegram.TelegramError as exc:
            stats["failed"] += 1
            if exc.chat_gone:
                # Blocked the bot: stop trying until they reconnect on the site.
                TelegramLink.objects.filter(pk=link.pk).update(enabled=False)
                gone.add(watch.user_id)
            logger.warning("Alert for watch %s not sent: %s", watch.pk, exc)
            continue
        watch.baseline_price, watch.last_notified_at = trigger.price, now
        watch.save(update_fields=["baseline_price", "last_notified_at"])
        stats["sent"] += 1
    return stats
