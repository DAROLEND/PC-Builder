"""Import products from hotline.ua category pages.

Why the hand-picked catalog is small and how this extends it
--------------------------------------------------------------
The compatibility engine needs *exact* specs: socket, chipset, GPU length, TDP,
case clearances. The aggregator publishes prices, photos and names in reliable
structured data (schema.org), but the full spec sheet only exists inside its
front-end JavaScript state. Executing third-party JS on our server is not an
option, and scraping its layout would break on the next redesign.

So an imported product gets:
* name, brand, price, stock and photos from the structured data (reliable);
* the spec sheet from the page state when the source ships it (see
  ``source_specs.py``; read without executing any JavaScript);
* where that is missing, specs derived from the title with certainty:
  - memory: everything is in the title ("32 GB (2x16GB) DDR5 6000 MHz");
  - graphics cards: chipset and VRAM from the title, board power and the
    vendor's PSU recommendation from the chip reference table below
    (length is optional — the engine then asks to check the case);
  - SSDs: capacity from the title, interface from the title or from product
    lines that exist in one form factor only (990 PRO, NV3 → M.2 NVMe);
  - other categories: nothing, the part is catalog-only.
Parts with complete specs are immediately usable in the configurator; the rest
are shown in the catalog with a "specs not filled in" badge and can be
completed in the admin, which flips them to buildable automatically.

Politeness: robots.txt, per-host throttling and an honest User-Agent come from
``Fetcher``; listing pages are fetched on demand only (management command), not
on a schedule.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from urllib.parse import urljoin

from django.conf import settings
from django.db import transaction
from django.utils.text import slugify

from .market import FETCH_DISABLED, Fetcher, MarketError, ProductData, fetching_enabled
from .market_service import apply_product_data, record_daily_price, to_usd, update_shop_count
from .models import Category, Component, ExchangeRate, Manufacturer, MarketListing

logger = logging.getLogger(__name__)

HOTLINE = "https://hotline.ua"
IMPORT_PHOTOS = 2
CATEGORY_PAGES = {
    "cpu": "/ua/computer/processory/",
    "motherboard": "/ua/computer/materinskie-platy/",
    "ram": "/ua/computer/moduli-pamyati-dlya-pk-i-noutbukov/",
    "gpu": "/ua/computer/videokarty/",
    "storage": "/ua/computer/diski-ssd/",
    "psu": "/ua/computer/bloki-pitaniya/",
    "case": "/ua/computer/korpusa/",
    "cooler": "/ua/computer/kulery-i-radiatory/",
}
PRODUCT_PATH = {
    "cpu": "computer-processory",
    "motherboard": "computer-materinskie-platy",
    "ram": "computer-moduli-pamyati-dlya-pk-i-noutbukov",
    "gpu": "computer-videokarty",
    "storage": "computer-diski-ssd",
    "psu": "computer-bloki-pitaniya",
    "case": "computer-korpusa",
    "cooler": "computer-kulery-i-radiatory",
}

# Reference board power (W) and the chip vendor's minimum PSU (W).
# Approximate reference values; partner cards with factory overclocks draw a bit
# more, which the 30 % PSU headroom in the engine absorbs.
GPU_CHIPS: dict[str, tuple[int, int]] = {
    "GeForce RTX 5090": (575, 1000),
    "GeForce RTX 5080": (360, 850),
    "GeForce RTX 5070 Ti": (300, 750),
    "GeForce RTX 5070": (250, 650),
    "GeForce RTX 5060 Ti": (180, 600),
    "GeForce RTX 5060": (145, 550),
    "GeForce RTX 5050": (130, 550),
    "GeForce RTX 4090": (450, 850),
    "GeForce RTX 4080 SUPER": (320, 750),
    "GeForce RTX 4080": (320, 750),
    "GeForce RTX 4070 Ti SUPER": (285, 700),
    "GeForce RTX 4070 Ti": (285, 700),
    "GeForce RTX 4070 SUPER": (220, 650),
    "GeForce RTX 4070": (200, 650),
    "GeForce RTX 4060 Ti": (160, 550),
    "GeForce RTX 4060": (115, 550),
    "GeForce RTX 3060": (170, 550),
    "GeForce RTX 3050": (130, 550),
    "Radeon RX 9070 XT": (304, 750),
    "Radeon RX 9070": (220, 650),
    "Radeon RX 9060 XT": (160, 550),
    "Radeon RX 7900 XTX": (355, 800),
    "Radeon RX 7900 XT": (315, 750),
    "Radeon RX 7900 GRE": (260, 700),
    "Radeon RX 7800 XT": (263, 700),
    "Radeon RX 7700 XT": (245, 700),
    "Radeon RX 7600 XT": (190, 600),
    "Radeon RX 7600": (165, 550),
    "Radeon RX 6600": (132, 500),
    "Arc B580": (190, 600),
    "Arc B570": (150, 500),
    "Arc A770": (225, 650),
    "Arc A750": (225, 650),
}
# Chips sold with exactly one memory size, so a title without "12G" is still exact.
SINGLE_VRAM = {
    "GeForce RTX 5090": 32,
    "GeForce RTX 5080": 16,
    "GeForce RTX 5070 Ti": 16,
    "GeForce RTX 5070": 12,
    "GeForce RTX 5060": 8,
    "GeForce RTX 5050": 8,
    "GeForce RTX 4090": 24,
    "GeForce RTX 4080 SUPER": 16,
    "GeForce RTX 4080": 16,
    "GeForce RTX 4070 Ti SUPER": 16,
    "GeForce RTX 4070 Ti": 12,
    "GeForce RTX 4070 SUPER": 12,
    "GeForce RTX 4060": 8,
    "Radeon RX 9070 XT": 16,
    "Radeon RX 9070": 16,
    "Radeon RX 7900 XTX": 24,
    "Radeon RX 7900 XT": 20,
    "Radeon RX 7900 GRE": 16,
    "Radeon RX 7800 XT": 16,
    "Radeon RX 7700 XT": 12,
    "Radeon RX 7600 XT": 16,
    "Radeon RX 7600": 8,
    "Radeon RX 6600": 8,
    "Arc B580": 12,
    "Arc B570": 10,
    "Arc A750": 8,
}
# Longest names first, so "RTX 5070 Ti" is not matched as "RTX 5070".
_CHIP_PATTERNS = [
    (name, re.compile(r"\b" + r"\s*".join(map(re.escape, name.split())) + r"\b", re.I))
    for name in sorted(GPU_CHIPS, key=len, reverse=True)
]
_SHORT_CHIP = re.compile(r"\b(RTX|RX)\s*(\d{4})\s*(Ti\s*SUPER|Ti|SUPER|XTX|XT|GRE)?\b", re.I)


def gpu_specs(title: str) -> dict:
    specs: dict = {}
    chip = next((name for name, pattern in _CHIP_PATTERNS if pattern.search(title)), None)
    if chip is None:
        # "TUF-RTX5070TI-O16G-GAMING" style part numbers.
        short = _SHORT_CHIP.search(title.replace("-", " "))
        if short:
            family = "GeForce RTX" if short.group(1).upper() == "RTX" else "Radeon RX"
            suffix = (short.group(3) or "").upper().replace("TI", "Ti").replace("  ", " ")
            candidate = f"{family} {short.group(2)} {suffix}".strip()
            chip = candidate if candidate in GPU_CHIPS else None
    if chip:
        specs["chipset"] = chip
        specs["tdp_w"], specs["recommended_psu_w"] = GPU_CHIPS[chip]
    vram = re.search(r"(?<![\dx])(\d{1,2})\s*G(?:B)?\b", title, re.I) or re.search(
        r"O?(\d{1,2})G\b", title
    )
    if vram and 2 <= int(vram.group(1)) <= 48:
        specs["vram_gb"] = int(vram.group(1))
    elif chip in SINGLE_VRAM:
        specs["vram_gb"] = SINGLE_VRAM[chip]
    return specs


_RAM_KIT = re.compile(r"(\d+)\s*GB\s*\((\d+)\s*x\s*(\d+)\s*GB\)\s*(DDR[45])\s*(\d{4})", re.I)
_RAM_SINGLE = re.compile(r"(\d+)\s*GB\s*(DDR[45])\s*(\d{4})", re.I)


def ram_specs(title: str) -> dict:
    if re.search(r"SO-?DIMM", title, re.I):
        return {}  # laptop memory never fits a desktop board
    kit = _RAM_KIT.search(title)
    if kit:
        return {
            "memory_type": kit.group(4).upper(),
            "modules": int(kit.group(2)),
            "module_size_gb": int(kit.group(3)),
            "speed_mhz": int(kit.group(5)),
        }
    single = _RAM_SINGLE.search(title)
    if single:
        return {
            "memory_type": single.group(2).upper(),
            "modules": 1,
            "module_size_gb": int(single.group(1)),
            "speed_mhz": int(single.group(3)),
        }
    return {}


# Titles rarely name the interface, but these product lines exist in one form
# only. Lines sold both as M.2 and 2.5" (e.g. WD Red SA500) are left out.
_NVME_LINES = re.compile(
    r"\b(9100 PRO|990 (PRO|EVO)|980 PRO|970 EVO|SN\d{3,4}X?|KC3000|NV[123]|P310|P3 Plus|"
    r"P5 Plus|T500|T700|P400 Lite|AS2280P4|FURY Renegade|MP[67]00)\b",
    re.I,
)
_SATA_LINES = re.compile(
    r"\b(A400|KC600|870 EVO|860 EVO|MX500|BX500|Burst Elite|CX400|P210)\b", re.I
)


def storage_specs(title: str) -> dict:
    specs: dict = {}
    size = re.search(r"(\d+(?:[.,]\d+)?)\s*(TB|GB)\b", title, re.I)
    if size:
        value = float(size.group(1).replace(",", "."))
        specs["capacity_gb"] = int(value * 1000) if size.group(2).upper() == "TB" else int(value)
    m2 = re.search(r"\bM\.?2\b", title, re.I)
    if m2 and re.search(r"NVMe|PCIe", title, re.I):
        specs["interface"] = "M.2 NVMe"
    elif m2 and re.search(r"SATA", title, re.I):
        specs["interface"] = "M.2 SATA"
    elif re.search(r"2\.5\"?|SATA", title, re.I):
        specs["interface"] = "SATA"
    elif _NVME_LINES.search(title):
        specs["interface"] = "M.2 NVMe"
    elif _SATA_LINES.search(title):
        specs["interface"] = "SATA"
    return specs


SPEC_EXTRACTORS = {"gpu": gpu_specs, "ram": ram_specs, "storage": storage_specs}


# The aggregator's "coolers and radiators" category also lists case fans and
# thermal paste; they are not CPU coolers. Fans are recognised by their model
# lines (Arctic P12, Noctua NF-A12x25, be quiet! Pure Wings, 3-Pack ...).
_NOT_CPU_COOLER = re.compile(
    r"термопаст|thermal (paste|compound)|вентилятор|\bfan\b|\d-Pack|"
    r"\bNF-[A-Z]\d|Pure Wings|Arctic P\d{1,2}\b|\b\d{5} PWM|Apolar|\bM120D\b",
    re.I,
)


# External USB drives share the SSD category (Kingston XS2000, Samsung T7 ...).
_EXTERNAL_DRIVE = re.compile(
    r"portable|external|зовнішн|docking|\bUSB\b|\bXS\d{4}\b|Samsung T\d\b|\bExtreme Pro\b", re.I
)


def is_desktop_part(kind: str, title: str) -> bool:
    """Skip obvious non-matches the category page lists (laptop RAM, fans, USB drives)."""
    if kind == "ram" and re.search(r"SO-?DIMM", title, re.I):
        return False
    if kind == "storage" and _EXTERNAL_DRIVE.search(title):
        return False
    return not (kind == "cooler" and _NOT_CPU_COOLER.search(title))


# --- Crawling --------------------------------------------------------------------


def product_urls(fetcher: Fetcher, kind: str, pages: int) -> list[str]:
    """Product page URLs from the first ``pages`` pages of a category."""
    base = urljoin(HOTLINE, CATEGORY_PAGES[kind])
    pattern = re.compile(rf'href="(/ua/{PRODUCT_PATH[kind]}/[a-z0-9-]+/)"')
    seen: dict[str, None] = {}
    for page in range(1, pages + 1):
        url = base if page == 1 else f"{base}?p={page}"
        try:
            html = fetcher.get(url)
        except MarketError as exc:
            logger.warning("Category page %s failed: %s", url, exc)
            break
        found = pattern.findall(html)
        if not found:
            break
        for path in found:
            seen.setdefault(urljoin(HOTLINE, path), None)
    return list(seen)


def derive_specs(kind: str, title: str, raw_specs: list[tuple[str, str]] | None = None) -> dict:
    """Best specs we can vouch for: the source's spec sheet, then the title.

    Values that fail validation are dropped rather than stored, so a surprise
    on the source page makes a part catalog-only instead of wrong.
    """
    from .source_specs import specs_from_rows
    from .specs import validate_specs

    extractor = SPEC_EXTRACTORS.get(kind)
    specs = extractor(title) if extractor else {}
    if raw_specs:
        specs.update(specs_from_rows(kind, raw_specs, gpu_chips=list(GPU_CHIPS)))
    if kind == "gpu" and specs.get("chipset") in GPU_CHIPS:
        tdp, psu = GPU_CHIPS[specs["chipset"]]
        specs.setdefault("tdp_w", tdp)
        specs.setdefault("recommended_psu_w", psu)
    errors = validate_specs(kind, specs, partial=True)
    for key in errors:
        specs.pop(key, None)
    if "specs" in errors:  # unknown keys
        from .specs import SCHEMAS

        specs = {k: v for k, v in specs.items() if k in SCHEMAS.get(kind, {})}
    return specs


# "... Beast Black (KF560C36BBE2K2-32)", "... King 95 Pro Black (KING 95 PRO (B))"
_PART_NUMBER = re.compile(r"\s*\(((?:[^()]|\([^()]*\))*)\)\s*$")


def split_part_number(name: str) -> tuple[str, str]:
    """("Ryzen 5 5500", "100-100000457BOX") from "Ryzen 5 5500 (100-100000457BOX)"."""
    match = _PART_NUMBER.search(name)
    if not match or match.start() == 0:
        return name.strip(), ""
    part = match.group(1).split(",")[0].strip()
    return name[: match.start()].strip(), part


@dataclass
class ImportStats:
    seen: int = 0
    created: int = 0
    buildable: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _split_brand(title: str, brand: str) -> tuple[str, str]:
    if brand and title.lower().startswith(brand.lower()):
        return brand, title[len(brand) :].strip() or title
    first, _, rest = title.partition(" ")
    return (brand or first), (rest.strip() if not brand else title)


def _unique(field: str, base: str, max_length: int) -> str:
    """``base`` cut to the column length, with -2, -3 ... on collision.

    Long titles that differ only at the end ("... Beast Black (KF560C36BBE2K2-32)")
    would otherwise collide once truncated.
    """
    value, n = base[:max_length], 2
    while Component.objects.filter(**{field: value}).exists():
        suffix = f"-{n}"
        value, n = f"{base[: max_length - len(suffix)]}{suffix}", n + 1
    return value


@transaction.atomic
def create_component(
    kind: str, url: str, data: ProductData, rate: Decimal | None
) -> Component | None:
    """Create the part with its listing; None when the catalog already has it."""
    category = Category.objects.get(kind=kind)
    brand, full_name = _split_brand(data.title, data.brand)
    # The part number goes to the SKU; it also merges box/tray variants that
    # the source lists separately ("Ryzen 7 9700X (100-000001404)" / "(...WOF)").
    name, part_number = split_part_number(full_name)
    name = name[:128]
    manufacturer = Manufacturer.objects.filter(name__iexact=brand[:64]).first()
    if manufacturer is None:
        manufacturer = Manufacturer.objects.create(
            name=brand[:64], slug=_unique_manufacturer_slug(brand)
        )
    if Component.objects.filter(manufacturer=manufacturer, name=name).exists():
        return None  # e.g. a curated part tracked under another URL

    typical = data.median_price or data.low_price
    price = to_usd(typical, data.currency or "UAH", rate) if typical else None
    specs = derive_specs(kind, data.title, data.raw_specs)
    slug = _unique("slug", slugify(f"{brand} {name}") or "part", 150)
    component = Component(
        category=category,
        manufacturer=manufacturer,
        name=name,
        slug=slug,
        sku=_unique("sku", part_number or f"HL-{slug.upper()}", 64),
        price=price or Decimal("0.00"),
        specs=specs,
        is_active=price is not None,
    )
    # "specs" is excluded from the field checks only: an empty dict counts as
    # "blank" there, yet it is a valid catalog-only part. clean() still
    # validates the keys that are present.
    component.full_clean(exclude=["slug", "sku", "specs"])
    component.save()
    listing = MarketListing(component=component, url=url)
    apply_product_data(listing, data)
    listing.save()
    update_shop_count(component)
    if price is not None:
        low = to_usd(data.low_price, data.currency or "UAH", rate) if data.low_price else None
        high = to_usd(data.high_price, data.currency or "UAH", rate) if data.high_price else None
        record_daily_price(component, price, low, high, source=listing.source[:32])
    return component


def _unique_manufacturer_slug(name: str) -> str:
    base = slugify(name) or "brand"
    slug, n = base, 2
    while Manufacturer.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def import_category(
    kind: str, pages: int = 1, limit: int | None = None, fetcher: Fetcher | None = None
) -> ImportStats:
    from .images import mirror_images
    from .price_history import sync_listing_history

    stats = ImportStats()
    if not fetching_enabled():
        stats.errors.append(FETCH_DISABLED)
        return stats
    fetcher = fetcher or Fetcher()
    rate = ExchangeRate.latest_uah_rate()
    known = set(MarketListing.objects.values_list("url", flat=True))
    for url in product_urls(fetcher, kind, pages):
        if limit is not None and stats.created >= limit:
            break
        stats.seen += 1
        if url in known:
            stats.skipped += 1
            continue
        try:
            data = fetcher.fetch_product(url)
        except MarketError as exc:
            stats.errors.append(f"{url}: {exc}")
            continue
        if not data.title or not is_desktop_part(kind, data.title):
            stats.skipped += 1
            continue
        if not data.images:
            stats.skipped += 1  # not even the source has a photo: not worth listing
            continue
        shops = len(data.offer_prices) or data.offer_count or 0
        if shops < settings.MARKET_MIN_SHOPS:
            stats.skipped += 1  # one or two shops: no real market price
            continue
        try:
            component = create_component(kind, url, data, rate)
        except Exception as exc:  # one bad product must not stop the import
            logger.exception("Import of %s failed", url)
            stats.errors.append(f"{url}: {exc}")
            continue
        if component is None:
            stats.skipped += 1
            continue
        # Two photos keep a bulk import light; the regular refresh adds the rest.
        mirror_images(component, data.images, fetcher, limit=IMPORT_PHOTOS)
        sync_listing_history(component.listings.get(), fetcher)
        stats.created += 1
        stats.buildable += int(component.specs_complete)
        logger.info("Imported %s (buildable=%s)", component, component.specs_complete)
    return stats
