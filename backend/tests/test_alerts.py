"""Price watches, the Telegram link flow, the bot and the alert check."""

import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import responses
from django.utils import timezone

from apps.alerts.bot import handle_update
from apps.alerts.models import TelegramLink, Watch
from apps.alerts.service import check_watches, evaluate, render
from apps.catalog.models import Component, ExchangeRate
from config.settings import load_env_file
from tests.factories import UserFactory, make_build

API = "https://api.telegram.org/bottest-token"
KYIV = ZoneInfo("Europe/Kyiv")
NOON = datetime(2026, 9, 25, 12, 0, tzinfo=KYIV)
NIGHT = datetime(2026, 9, 25, 23, 30, tzinfo=KYIV)


def sent(mocked) -> list[dict]:
    return [
        json.loads(c.request.body) for c in mocked.calls if c.request.url.endswith("/sendMessage")
    ]


def linked_user(chat_id=1001, **fields):
    user = UserFactory()
    TelegramLink.objects.create(user=user, chat_id=chat_id, username="tester", **fields)
    return user


@pytest.fixture
def cpu(comp):
    return comp("Ryzen 5 7600")


@pytest.fixture
def rate(db):
    from datetime import date

    return ExchangeRate.objects.create(
        currency="USD", rate=Decimal("40.0000"), rate_date=date(2026, 9, 1)
    ).rate


# --- API ------------------------------------------------------------------------------------


def test_watching_a_part_records_the_current_price(auth_api, cpu):
    resp = auth_api.post("/api/watches/", {"component": cpu.id, "threshold_percent": 7})
    assert resp.status_code == 201, resp.data
    assert resp.data["baseline_price"] == f"{cpu.price:.2f}"
    assert resp.data["item"]["path"] == f"/catalog/{cpu.slug}"
    assert resp.data["change_percent"] == "0.0"

    again = auth_api.post("/api/watches/", {"component": cpu.id})
    assert again.status_code == 400
    assert auth_api.get(f"/api/watches/?component={cpu.id}").json()[0]["threshold_percent"] == 7


def test_watch_needs_exactly_one_target(auth_api, cpu, user):
    build = make_build(user, [cpu])
    assert auth_api.post("/api/watches/", {}).status_code == 400
    both = auth_api.post("/api/watches/", {"component": cpu.id, "build": build.id})
    assert both.status_code == 400


def test_private_builds_of_others_cannot_be_watched(auth_api, cpu, other_user):
    private = make_build(other_user, [cpu], is_public=False)
    public = make_build(other_user, [cpu], name="Shared")
    assert auth_api.post("/api/watches/", {"build": private.id}).status_code == 400
    resp = auth_api.post("/api/watches/", {"build": public.id})
    assert resp.status_code == 201
    assert resp.data["baseline_price"] == f"{cpu.price:.2f}"


def test_watches_are_private(api, auth_api, cpu, other_user):
    Watch.objects.create(user=other_user, component=cpu, baseline_price=cpu.price)
    assert auth_api.get("/api/watches/").json() == []
    assert api.get("/api/watches/").status_code == 401
    theirs = Watch.objects.get(user=other_user)
    assert auth_api.delete(f"/api/watches/{theirs.id}/").status_code == 404


def test_link_request_returns_a_one_time_deep_link(auth_api, user):
    status = auth_api.get("/api/telegram/").json()
    assert status["linked"] is False and status["bot_url"] == "https://t.me/test_bot"
    resp = auth_api.post("/api/telegram/link/", {"language": "en"})
    token = TelegramLink.objects.get(user=user).link_token
    assert resp.json()["url"] == f"https://t.me/test_bot?start={token}"
    assert TelegramLink.objects.get(user=user).language == "en"


# --- The bot ----------------------------------------------------------------------------------


def update(text, chat_id=555, chat_type="private", **sender):
    return {
        "update_id": 1,
        "message": {
            "message_id": 10,
            "chat": {"id": chat_id, "type": chat_type},
            "from": {"id": chat_id, "username": "slabi", "language_code": "uk", **sender},
            "text": text,
        },
    }


@responses.activate
def test_start_with_a_valid_code_links_the_chat(user):
    responses.post(f"{API}/sendMessage", json={"ok": True, "result": {}})
    link = TelegramLink.objects.create(user=user)
    token = link.issue_token()
    handle_update(update(f"/start {token}"))

    link.refresh_from_db()
    assert (link.chat_id, link.username, link.link_token) == (555, "slabi", None)
    assert "Готово" in sent(responses)[0]["text"]
    # The code is single-use.
    handle_update(update(f"/start {token}", chat_id=777))
    assert TelegramLink.objects.get(user=user).chat_id == 555
    assert "застаріло" in sent(responses)[1]["text"]


@responses.activate
def test_expired_code_is_refused(user):
    responses.post(f"{API}/sendMessage", json={"ok": True, "result": {}})
    link = TelegramLink.objects.create(user=user)
    token = link.issue_token()
    TelegramLink.objects.filter(pk=link.pk).update(
        token_created_at=timezone.now() - timedelta(hours=1)
    )
    handle_update(update(f"/start {token}"))
    assert TelegramLink.objects.get(pk=link.pk).chat_id is None


@responses.activate
def test_list_stop_and_on(cpu):
    responses.post(f"{API}/sendMessage", json={"ok": True, "result": {}})
    user = linked_user(chat_id=555, language="uk")
    Watch.objects.create(
        user=user, component=cpu, baseline_price=cpu.price, target_price=Decimal("150")
    )
    handle_update(update("/list"))
    listing = sent(responses)[-1]["text"]
    assert "Стежу за ціною (1)" in listing and cpu.name in listing and "ціль" in listing

    handle_update(update("/stop"))
    assert TelegramLink.objects.get(user=user).enabled is False
    handle_update(update("/on@test_bot"))
    assert TelegramLink.objects.get(user=user).enabled is True


@responses.activate
def test_groups_and_unknown_chats_are_handled_safely(db):
    responses.post(f"{API}/sendMessage", json={"ok": True, "result": {}})
    handle_update(update("/list", chat_type="group"))
    assert sent(responses) == []  # groups are ignored
    handle_update(update("/list"))  # a chat that was never linked
    assert "не підключено" in sent(responses)[0]["text"]


@responses.activate
def test_unwatch_button_removes_only_the_chats_own_watch(cpu, other_user):
    responses.post(f"{API}/answerCallbackQuery", json={"ok": True, "result": True})
    responses.post(f"{API}/editMessageReplyMarkup", json={"ok": True, "result": True})
    user = linked_user(chat_id=555)
    mine = Watch.objects.create(user=user, component=cpu, baseline_price=cpu.price)
    theirs = Watch.objects.create(user=other_user, component=cpu, baseline_price=cpu.price)

    def press(watch_id):
        handle_update(
            {
                "update_id": 2,
                "callback_query": {
                    "id": "q",
                    "data": f"unwatch:{watch_id}",
                    "message": {"message_id": 10, "chat": {"id": 555, "type": "private"}},
                },
            }
        )

    press(theirs.id)
    press(mine.id)
    assert list(Watch.objects.values_list("id", flat=True)) == [theirs.id]


# --- Deciding and sending ------------------------------------------------------------------------


def watch_at(cpu, user, baseline, **fields):
    return Watch.objects.create(
        user=user, component=cpu, baseline_price=Decimal(baseline), **fields
    )


def test_evaluate_thresholds_both_ways_and_the_target(cpu, user):
    watch = watch_at(cpu, user, "200", threshold_percent=5)
    assert evaluate(watch, Decimal("192")) is None  # -4 %
    assert evaluate(watch, Decimal("189")).kind == "drop"
    assert evaluate(watch, Decimal("211")).kind == "rise"
    watch.target_price = Decimal("195")
    assert evaluate(watch, Decimal("194")).kind == "target"  # only -3 %, but below the target
    assert evaluate(watch, None) is None


def test_message_in_hryvnias_with_buttons(cpu, user, rate):
    watch = watch_at(cpu, user, "200")
    text, buttons = render(watch, evaluate(watch, Decimal("180")), "uk", rate)
    assert "подешевшав на 10%" in text
    assert "7,5" in render(watch, evaluate(watch, Decimal("185")), "uk", rate)[0]  # -7.5 %
    assert "7 200 ₴" in text and "8 000 ₴" in text
    assert buttons[0][0]["url"] == f"https://pcbuilder.example/catalog/{cpu.slug}"
    assert buttons[1][0]["callback_data"] == f"unwatch:{watch.id}"


def test_build_message_agrees_in_gender(cpu, user, rate):
    build = make_build(user, [cpu], name="Ігровий")
    watch = Watch.objects.create(user=user, build=build, baseline_price=cpu.price * 2)
    text, _ = render(watch, evaluate(watch, cpu.price), "uk", rate)
    assert "<b>Збірка «Ігровий»</b> подешевшала на 50%" in text


@responses.activate
def test_check_sends_and_moves_the_baseline(cpu, rate):
    responses.post(f"{API}/sendMessage", json={"ok": True, "result": {}})
    user = linked_user()
    watch = watch_at(cpu, user, cpu.price * Decimal("1.2"))
    Watch.objects.create(user=linked_user(chat_id=2002), component=cpu, baseline_price=cpu.price)

    stats = check_watches(now=NOON)
    assert (stats["sent"], stats["checked"]) == (1, 2)
    watch.refresh_from_db()
    assert watch.baseline_price == cpu.price and watch.last_notified_at is not None
    assert check_watches(now=NOON)["sent"] == 0  # nothing new since


@responses.activate
def test_quiet_hours_hold_alerts_until_morning(cpu):
    responses.post(f"{API}/sendMessage", json={"ok": True, "result": {}})
    watch = watch_at(cpu, linked_user(), cpu.price * 2)
    assert check_watches(now=NIGHT)["held"] == 1
    watch.refresh_from_db()
    assert watch.baseline_price == cpu.price * 2  # still pending
    assert check_watches(now=NOON)["sent"] == 1


@responses.activate
def test_blocked_bot_disables_alerts(cpu):
    responses.post(
        f"{API}/sendMessage",
        status=403,
        json={
            "ok": False,
            "error_code": 403,
            "description": "Forbidden: bot was blocked by the user",
        },
    )
    user = linked_user()
    watch_at(cpu, user, cpu.price * 2)
    other = Component.objects.exclude(pk=cpu.pk).first()
    Watch.objects.create(user=user, component=other, baseline_price=other.price * 2)

    stats = check_watches(now=NOON)
    assert (stats["failed"], stats["sent"]) == (1, 0)  # the second one is not even tried
    assert TelegramLink.objects.get(user=user).enabled is False


def test_nothing_happens_without_a_token(settings, cpu):
    settings.TELEGRAM_BOT_TOKEN = ""
    watch_at(cpu, linked_user(), cpu.price * 2)
    assert check_watches(now=NOON)["checked"] == 0


# --- Local .env ---------------------------------------------------------------------


def test_env_file_never_overrides_real_environment(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        '# comment\nPCB_TEST_A="from file"\nexport PCB_TEST_B=2\nPCB_TEST_C=3\n', "utf-8"
    )
    monkeypatch.setenv("PCB_TEST_C", "real")
    monkeypatch.delenv("PCB_TEST_A", raising=False)
    monkeypatch.delenv("PCB_TEST_B", raising=False)
    load_env_file(env)
    assert (os.environ["PCB_TEST_A"], os.environ["PCB_TEST_B"]) == ("from file", "2")
    assert os.environ["PCB_TEST_C"] == "real"
    monkeypatch.delenv("PCB_TEST_A")
    monkeypatch.delenv("PCB_TEST_B")
