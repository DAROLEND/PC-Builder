"""MARKET_FETCH_ENABLED=0 stops every request to external sites and keeps stored data."""

from io import StringIO

import pytest
import responses
from django.core.management import call_command

from apps.catalog.importer import import_category
from apps.catalog.market import Fetcher, MarketError
from apps.catalog.market_service import refresh_due_listings, refresh_listing
from apps.catalog.models import MarketListing
from apps.catalog.price_history import sync_listing_history


@pytest.fixture
def disabled(settings):
    settings.MARKET_FETCH_ENABLED = False


@pytest.fixture
def listing(comp):
    return MarketListing.objects.create(
        component=comp("Ryzen 5 7600"),
        url="https://hotline.ua/ua/computer-processory/amd-ryzen-5-7600/",
        status="ok",
        offer_count=40,
    )


@responses.activate  # any real request would fail loudly: nothing is registered
def test_nothing_is_requested_and_nothing_changes(disabled, listing, api, user):
    with pytest.raises(MarketError, match="disabled"):
        Fetcher(min_interval=0).get("https://hotline.ua/")
    assert refresh_listing(listing, Fetcher(min_interval=0), None) == "ok"
    listing.refresh_from_db()
    assert (listing.status, listing.offer_count, listing.checked_at) == ("ok", 40, None)
    assert refresh_due_listings() == {}
    assert import_category("gpu").errors and sync_listing_history(listing, Fetcher()) is None
    assert len(responses.calls) == 0

    for command in ("refresh_market", "import_hotline", "sync_price_history"):
        out = StringIO()
        call_command(command, stdout=out)
        assert "disabled" in out.getvalue()

    user.is_staff = True
    user.save()
    api.force_authenticate(user)
    resp = api.post(
        f"/api/components/{listing.component.slug}/listings/", {"url": "https://x.example/p"}
    )
    assert resp.status_code == 503
