from pathlib import Path

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.catalog.models import Component
from tests.factories import UserFactory

FIXTURE = Path(__file__).parent / "fixtures" / "catalog.json"


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Load a *frozen* catalog once per test session.

    Not the app's seed file: that one is refreshed with live market prices, and
    tests must not start failing because RAM got more expensive.
    """
    with django_db_blocker.unblock():
        call_command("seed_catalog", "--no-builds", "--file", str(FIXTURE), verbosity=0)


@pytest.fixture(autouse=True)
def _celery_eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.PAYMENT_PROVIDER = "fake"
    settings.ANTHROPIC_API_KEY = ""
    # backend/.env may hold a real bot token for local runs; tests must never use it.
    settings.TELEGRAM_BOT_TOKEN = "test-token"
    settings.TELEGRAM_BOT_USERNAME = "test_bot"
    settings.FRONTEND_URL = "https://pcbuilder.example"
    # Tests mock every HTTP call; the real default (off) is tested explicitly.
    settings.MARKET_FETCH_ENABLED = True


@pytest.fixture
def comp(db):
    """Look up a seeded component by its exact name: comp("Ryzen 5 7600")."""

    def get(name: str) -> Component:
        return Component.objects.with_related().get(name=name)

    return get


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def other_user(db):
    return UserFactory()


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def auth_api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def budget_gaming_ids(comp):
    names = [
        "Ryzen 5 5600",
        "B450M Pro4",
        "FURY Beast 16GB (2x8GB) DDR4-3200",
        "PULSE Radeon RX 7600 8GB",
        "P3 Plus 1TB",
        "AK400",
        "Pure Power 12 550W",
        "CH370",
    ]
    return [comp(n).id for n in names]
