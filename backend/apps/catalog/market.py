"""Live market data (prices, photos, availability) from product pages.

How it works
------------
Each component can have one or more ``MarketListing`` rows: a URL of the same
product on a price aggregator (hotline.ua) or a shop (rozetka, moyo, ...).
A Celery task periodically downloads those pages and reads the *structured
data* the sites publish for search engines — schema.org ``Product`` in JSON-LD
or microdata. Nothing site-specific is scraped out of the HTML layout, so a
redesign of a shop does not break us; a missing ``Product`` block is reported
as an error on the listing instead of silently producing garbage.

Being a good citizen
--------------------
* robots.txt is checked for every host (cached for a day) and respected;
* at most one request per host every ``MARKET_MIN_INTERVAL`` seconds;
* an honest User-Agent that says who we are;
* only product pages are fetched, never search or listing pages.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import time
import urllib.robotparser
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html import unescape
from statistics import median
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT = 20
ROBOTS_TTL = 24 * 3600


class MarketError(Exception):
    """A listing could not be refreshed. ``code`` is stored on the listing."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass
class ProductData:
    title: str = ""
    low_price: Decimal | None = None
    high_price: Decimal | None = None
    currency: str = ""
    offer_count: int | None = None
    in_stock: bool | None = None
    rating: Decimal | None = None
    review_count: int | None = None
    images: list[str] = field(default_factory=list)
    brand: str = ""
    # From the page state when available (see source_specs.py): prices of all
    # new-condition shop offers and the spec sheet as (title, value) rows.
    offer_prices: list[Decimal] = field(default_factory=list)
    raw_specs: list[tuple[str, str]] = field(default_factory=list)

    @property
    def has_price(self) -> bool:
        return self.low_price is not None

    @property
    def median_price(self) -> Decimal | None:
        """Typical price across shops: half of the offers are cheaper, half dearer.

        The aggregator's headline "from X" is the single cheapest offer, often a
        shop with no stock history; the median is what a buyer usually pays.
        """
        if not self.offer_prices:
            return None
        return Decimal(median(self.offer_prices)).quantize(Decimal("0.01"))


FETCH_DISABLED = (
    "Fetching from external sites is disabled (MARKET_FETCH_ENABLED=0). "
    "Data already in the database stays as it is."
)


def fetching_enabled() -> bool:
    """settings.MARKET_FETCH_ENABLED: may we contact shop / aggregator sites at all?"""
    return bool(settings.MARKET_FETCH_ENABLED)


# --- Parsing ----------------------------------------------------------------------

JSON_LD_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I
)
META_RE = re.compile(r"<meta\s+([^>]+)>", re.I)
ATTR_RE = re.compile(r"([\w:-]+)\s*=\s*([\"'])(.*?)\2", re.S)
ITEMPROP_RE = re.compile(r"<[^>]+itemprop=[\"'](\w+)[\"'][^>]*>", re.I)


def parse_decimal(value) -> Decimal | None:
    """'19 299,00' / '19299' / 19299.0 → Decimal('19299.00')."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(" ", "").replace(" ", "")
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    text = re.sub(r"[^\d.]", "", text)
    if not text:
        return None
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _find_products(node):
    """Yield every schema.org Product in a JSON-LD document (lists, @graph...)."""
    if isinstance(node, list):
        for item in node:
            yield from _find_products(item)
    elif isinstance(node, dict):
        types = _as_list(node.get("@type"))
        if "Product" in types or "ProductGroup" in types:
            yield node
        for key in ("@graph", "mainEntity", "itemListElement", "item"):
            if key in node:
                yield from _find_products(node[key])


def _availability(value) -> bool | None:
    if not value:
        return None
    text = str(value).lower()
    if any(s in text for s in ("instock", "in_stock", "limitedavailability", "presale")):
        return True
    if any(s in text for s in ("outofstock", "soldout", "discontinued")):
        return False
    return None


PLACEHOLDER_RE = re.compile(r"(no[-_]?(photo|image)|placeholder|/public/i/|\.gif$)", re.I)


def _images(value, base_url: str) -> list[str]:
    urls = []
    for item in _as_list(value):
        if isinstance(item, dict):
            item = item.get("url") or item.get("contentUrl")
        if isinstance(item, str) and item.strip():
            url = urljoin(base_url, item.strip())
            # Sites put a generic "no photo" picture into structured data too
            # (hotline: /public/i/img-265.gif); a missing photo is better.
            if not PLACEHOLDER_RE.search(url):
                urls.append(url)
    return urls


def _from_json_ld(product: dict, base_url: str) -> ProductData:
    data = ProductData(title=unescape(str(product.get("name") or "")).strip())
    data.images = _images(product.get("image"), base_url)
    brand = product.get("brand")
    data.brand = str((brand.get("name") if isinstance(brand, dict) else brand) or "").strip()

    offers = _as_list(product.get("offers"))
    prices: list[Decimal] = []
    highs: list[Decimal] = []
    stock: list[bool] = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        data.currency = data.currency or str(offer.get("priceCurrency") or "")
        low = parse_decimal(offer.get("lowPrice") or offer.get("price"))
        high = parse_decimal(offer.get("highPrice") or offer.get("price"))
        if low is not None:
            prices.append(low)
        if high is not None:
            highs.append(high)
        if offer.get("offerCount") is not None:
            with contextlib.suppress(TypeError, ValueError):
                data.offer_count = (data.offer_count or 0) + int(offer["offerCount"])
        avail = _availability(offer.get("availability"))
        if avail is not None:
            stock.append(avail)

    data.low_price = min(prices) if prices else None
    data.high_price = max(highs) if highs else None
    if data.offer_count is None and prices:
        data.offer_count = len(prices)
    data.in_stock = any(stock) if stock else None

    rating = product.get("aggregateRating")
    if isinstance(rating, dict):
        data.rating = parse_decimal(rating.get("ratingValue"))
        try:
            data.review_count = int(rating.get("reviewCount") or rating.get("ratingCount") or 0)
        except (TypeError, ValueError):
            data.review_count = None
    return data


def _meta(html: str) -> dict[str, str]:
    result = {}
    for match in META_RE.finditer(html):
        attrs = {k.lower(): unescape(v) for k, _, v in ATTR_RE.findall(match.group(1))}
        key = attrs.get("property") or attrs.get("name") or attrs.get("itemprop")
        if key and "content" in attrs:
            result.setdefault(key.lower(), attrs["content"])
    return result


def _microdata(html: str, base_url: str) -> ProductData:
    """Fallback for shops that use itemprop attributes or OpenGraph tags."""
    meta = _meta(html)
    props: dict[str, str] = {}
    for tag in ITEMPROP_RE.finditer(html):
        attrs = {k.lower(): unescape(v) for k, _, v in ATTR_RE.findall(tag.group(0))}
        name = attrs.get("itemprop", "").lower()
        value = attrs.get("content") or attrs.get("href") or attrs.get("src")
        if name and value:
            props.setdefault(name, value)

    price = parse_decimal(
        props.get("price") or props.get("lowprice") or meta.get("product:price:amount")
    )
    data = ProductData(
        title=(meta.get("og:title") or props.get("name") or "").strip(),
        low_price=price,
        high_price=parse_decimal(props.get("highprice")) or price,
        currency=props.get("pricecurrency") or meta.get("product:price:currency", ""),
        in_stock=_availability(props.get("availability") or meta.get("product:availability")),
    )
    image = props.get("image") or meta.get("og:image")
    data.images = _images(image, base_url) if image else []
    return data


def extract_product(html: str, base_url: str) -> ProductData | None:
    """Best structured product data found on the page, or None."""
    candidates: list[ProductData] = []
    for block in JSON_LD_RE.findall(html):
        try:
            document = json.loads(block.strip())
        except ValueError:
            continue  # some sites ship invalid JSON-LD; ignore that block
        candidates.extend(_from_json_ld(p, base_url) for p in _find_products(document))

    with_price = [c for c in candidates if c.has_price]
    if with_price:
        best = with_price[0]
        if not best.images:
            best.images = _microdata(html, base_url).images
        return _with_page_state(best, html)

    fallback = _microdata(html, base_url)
    if fallback.has_price:
        return _with_page_state(fallback, html)
    return candidates[0] if candidates else None


def _with_page_state(data: ProductData, html: str) -> ProductData:
    from .source_specs import read_page_state

    state = read_page_state(html)
    if state is not None:
        data.offer_prices = state.offer_prices
        data.raw_specs = state.specs
    return data


# --- Matching -----------------------------------------------------------------------

CAPACITY_RE = re.compile(r"^\d+(x\d+)?(gb|tb|mb|g|t|w|mhz|mm)$")


def model_tokens(name: str) -> list[str]:
    """Tokens that identify a model: contain a digit, 2+ chars, not a capacity."""
    tokens = re.split(r"[^0-9a-z]+", name.lower())
    return [
        t
        for t in tokens
        if len(t) >= 2 and any(ch.isdigit() for ch in t) and not CAPACITY_RE.match(t)
    ]


def titles_match(our_name: str, source_title: str) -> bool:
    """Sanity check that the page still shows *our* product.

    Every model token of our name (``9800x3d``, ``b650m``, ``rm850x``) must occur
    in the source title. Protects against a listing URL that starts redirecting
    to a different product. Names without model tokens cannot be verified and
    are accepted.
    """
    haystack = re.sub(r"[^0-9a-z]", "", source_title.lower())
    return all(token in haystack for token in model_tokens(our_name))


# --- Fetching ------------------------------------------------------------------------


class Fetcher:
    """HTTP client that honours robots.txt and throttles per host."""

    def __init__(self, user_agent: str | None = None, min_interval: float | None = None):
        self.user_agent = user_agent or settings.MARKET_USER_AGENT
        self.min_interval = settings.MARKET_MIN_INTERVAL if min_interval is None else min_interval
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.6",
            }
        )
        self._robots: dict[str, tuple[float, urllib.robotparser.RobotFileParser | None]] = {}
        self._last_request: dict[str, float] = {}

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        cached = self._robots.get(origin)
        if cached and time.monotonic() - cached[0] < ROBOTS_TTL:
            return cached[1]
        parser: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
        try:
            response = self.session.get(f"{origin}/robots.txt", timeout=TIMEOUT)
            if response.status_code >= 400:
                parser = None  # no robots.txt → everything allowed
            else:
                parser.parse(response.text.splitlines())
        except requests.RequestException:
            parser = None
        self._robots[origin] = (time.monotonic(), parser)
        return parser

    def _throttle(self, host: str) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request.get(host, -1e9))
        if wait > 0:
            time.sleep(wait)
        self._last_request[host] = time.monotonic()

    def _request(self, url: str, method: str = "GET", **kwargs) -> requests.Response:
        # Last line of defence: callers check fetching_enabled() and skip earlier.
        if not fetching_enabled():
            raise MarketError("fetch_disabled", FETCH_DISABLED)
        robots = self._robots_for(url)
        if robots is not None and not robots.can_fetch(self.user_agent, url):
            raise MarketError("robots_disallowed", url)
        self._throttle(urlsplit(url).netloc)
        try:
            response = self.session.request(method, url, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise MarketError("network_error", str(exc)) from exc
        if response.status_code == 404:
            raise MarketError("not_found", url)
        if response.status_code >= 400:
            raise MarketError("http_error", f"HTTP {response.status_code}")
        return response

    def post_json(self, url: str, payload: dict) -> Any:
        """JSON API call under the same robots.txt, throttling and User-Agent rules."""
        response = self._request(
            url, method="POST", json=payload, headers={"Accept": "application/json"}
        )
        try:
            return response.json()
        except ValueError as exc:
            raise MarketError("bad_json", f"{url} did not return JSON") from exc

    def get(self, url: str) -> str:
        response = self._request(url)
        response.encoding = response.encoding or "utf-8"
        return response.text

    def get_bytes(self, url: str, max_bytes: int) -> bytes:
        """Binary download (photos), streamed so a huge file is cut off early."""
        response = self._request(
            url, headers={"Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}, stream=True
        )
        chunks, size = [], 0
        for chunk in response.iter_content(64 * 1024):
            size += len(chunk)
            if size > max_bytes:
                response.close()
                raise MarketError("too_large", f"{url} is over {max_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks)

    def fetch_product(self, url: str) -> ProductData:
        data = extract_product(self.get(url), url)
        if data is None:
            raise MarketError("no_product_data", "no schema.org Product on the page")
        return data
