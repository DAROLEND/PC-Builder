import json
from datetime import date
from decimal import Decimal

import pytest
import responses

from apps.catalog.integrations import IntegrationError, fetch_nbu_rate
from apps.catalog.models import Component, ExchangeRate, PriceHistory
from apps.catalog.tasks import sync_component_prices, update_exchange_rate

pytestmark = pytest.mark.django_db

NBU_URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"


@responses.activate
def test_update_exchange_rate_stores_nbu_rate():
    responses.get(
        NBU_URL,
        json=[
            {
                "r030": 840,
                "txt": "Долар США",
                "rate": 41.4567,
                "cc": "USD",
                "exchangedate": "23.09.2026",
            }
        ],
    )
    update_exchange_rate()
    update_exchange_rate()  # same day again → update, not a duplicate row
    rate = ExchangeRate.objects.get()
    assert rate.rate == Decimal("41.4567")
    assert rate.rate_date == date(2026, 9, 23)


@responses.activate
@pytest.mark.parametrize(
    "mock_kwargs",
    [{"status": 503}, {"json": []}, {"json": [{"cc": "USD"}]}, {"body": "not json"}],
)
def test_nbu_errors_raise_integration_error(mock_kwargs):
    responses.get(NBU_URL, **mock_kwargs)
    with pytest.raises(IntegrationError):
        fetch_nbu_rate()


@responses.activate
def test_price_sync_updates_changed_prices_and_logs_history(settings, comp):
    settings.PRICE_FEED_URL = "https://supplier.example/feed.json"
    cpu, gpu = comp("Ryzen 5 7600"), comp("PULSE Radeon RX 7600 8GB")
    responses.get(
        settings.PRICE_FEED_URL,
        body=json.dumps(
            {
                "items": [
                    {"sku": cpu.sku, "price": "170.00"},  # changed
                    {"sku": gpu.sku, "price": str(gpu.price)},  # unchanged
                    {"sku": "UNKNOWN", "price": "1.00"},
                    {"sku": "BROKEN", "price": "abc"},  # malformed row is skipped
                ]
            }
        ),
    )
    stats = sync_component_prices()
    assert stats == {"seen": 3, "updated": 1, "unknown_sku": 1}

    cpu.refresh_from_db()
    assert cpu.price == Decimal("170.00")
    assert list(PriceHistory.objects.values_list("component_id", "price")) == [
        (cpu.id, Decimal("170.00"))
    ]


def test_price_sync_from_bundled_fixture(settings):
    settings.PRICE_FEED_URL = "fixture"
    stats = sync_component_prices()
    assert stats["updated"] > 0
    assert stats["unknown_sku"] == 1
    assert PriceHistory.objects.count() == stats["updated"]
    assert not Component.objects.filter(price__lt=0).exists()
