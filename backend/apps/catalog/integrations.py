"""Clients for external data sources used by the catalog.

Each function does one HTTP call and returns plain data; persisting it is the
job of the Celery tasks. That split lets the tests mock HTTP with ``responses``
and assert on the database separately.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests
from django.conf import settings

TIMEOUT = 10
FIXTURE_FEED = Path(__file__).parent / "fixtures" / "price_feed.json"


class IntegrationError(Exception):
    pass


@dataclass(frozen=True)
class Rate:
    currency: str
    rate: Decimal
    rate_date: date


def fetch_nbu_rate(currency: str = "USD") -> Rate:
    """Official UAH exchange rate from the National Bank of Ukraine.

    Docs: https://bank.gov.ua/ua/open-data/api-dev
    Response: ``[{"r030": 840, "rate": 41.2, "cc": "USD", "exchangedate": "23.09.2026"}]``
    """
    try:
        response = requests.get(
            settings.NBU_EXCHANGE_URL,
            params={"valcode": currency, "json": ""},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        rows = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise IntegrationError(f"NBU request failed: {exc}") from exc

    if not rows:
        raise IntegrationError(f"NBU returned no rate for {currency}")
    row = rows[0]
    try:
        return Rate(
            currency=row["cc"],
            rate=Decimal(str(row["rate"])),
            rate_date=datetime.strptime(row["exchangedate"], "%d.%m.%Y").date(),
        )
    except (KeyError, InvalidOperation, ValueError) as exc:
        raise IntegrationError(f"Unexpected NBU payload: {row!r}") from exc


def fetch_price_feed() -> dict[str, Decimal]:
    """Supplier price list as ``{sku: price_usd}``.

    ``PRICE_FEED_URL=fixture`` reads a bundled JSON file (useful for demos and
    tests); an http(s) URL is fetched and must return
    ``{"items": [{"sku": "...", "price": "123.45"}]}``.
    """
    source = settings.PRICE_FEED_URL
    try:
        if source == "fixture":
            payload = json.loads(FIXTURE_FEED.read_text(encoding="utf-8"))
        else:
            response = requests.get(source, timeout=TIMEOUT)
            response.raise_for_status()
            payload = response.json()
    except (requests.RequestException, ValueError, OSError) as exc:
        raise IntegrationError(f"Price feed failed: {exc}") from exc

    prices: dict[str, Decimal] = {}
    for item in payload.get("items", []):
        try:
            price = Decimal(str(item["price"]))
        except (KeyError, InvalidOperation):
            continue  # skip malformed rows instead of failing the whole sync
        if price >= 0:
            prices[item["sku"]] = price
    return prices
