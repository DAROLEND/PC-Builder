"""Page state parser, spec mapping, typical price, daily history, cooling rules."""

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
import responses
from django.utils import timezone

from apps.builds import compatibility as c
from apps.catalog.market import Fetcher, extract_product
from apps.catalog.market_service import record_daily_price, refresh_listing
from apps.catalog.models import Component, ExchangeRate, MarketListing, PriceHistory
from apps.catalog.nuxt_state import NuxtStateError, extract_nuxt_state
from apps.catalog.source_specs import read_page_state, specs_from_rows

# --- The Nuxt state parser (no JavaScript is executed) ----------------------------------


def test_parses_parameters_assignments_and_literals():
    html = (
        '<script>window.__NUXT__=(function(a,b,c,d){d[0]="x";c.flag=true;'
        'return {title:"Ryzen \\u002F 5",price:a,tags:b,obj:c,list:d,'
        "none:void 0,made:new Date(1700000000),created:Object.create(null),"
        '"quoted key":-1.5}}(19299,["a","b"],{},Array(2)));</script>'
    )
    state = extract_nuxt_state(html)
    assert state == {
        "title": "Ryzen / 5",
        "price": 19299,
        "tags": ["a", "b"],
        "obj": {"flag": True},
        "list": ["x", None],
        "none": None,
        "made": 1700000000,
        "created": {},
        "quoted key": -1.5,
    }


@pytest.mark.parametrize(
    "script",
    [
        "window.__NUXT__=(function(a){return {x:fetch(a)}}(1));",  # a call: code, not data
        "window.__NUXT__=(function(a){alert(1);return {x:a}}(1));",
        "window.__NUXT__=(function(a){return {x:a}; b()}(1));",
        "window.__NUXT__=(function(a){return {x:Array(1e9)}}(1));",
        "window.__NUXT__=(function(a){return {x:[[[[" + "[" * 5000 + "}}(1));",
        "window.__NUXT__=(function(a){return {x:unknown}}(1));",
    ],
)
def test_anything_but_plain_data_is_refused(script):
    with pytest.raises(NuxtStateError):
        extract_nuxt_state(f"<script>{script}</script>")


# --- hotline page state -> specs and offers ------------------------------------------------


def nuxt_page(rows: list[tuple[str, str]], offers: list[tuple[float, str]]) -> str:
    """A product page state in the shape hotline ships (built with our own parser's grammar)."""
    values = [{"node": {"isHeader": False, "title": t, "value": v}} for t, v in rows]
    values.insert(0, {"node": {"isHeader": True, "title": "# Heading", "value": None}})
    product = {
        "productValues": {"edges": values},
        "offers": {"edges": [{"node": {"price": p, "condition": cond}} for p, cond in offers]},
    }
    body = json.dumps({"state": {"product": product}}, ensure_ascii=False)
    return f"<script>window.__NUXT__=(function(a){{return {body}}}(null));</script>"


CPU_ROWS = [
    ("vendor", "Intel"),
    ("Тип роз'єму", "Socket 1700"),
    ("Базова частота продуктивних ядер, ГГц", "3,5"),
    ("Максимальна частота продуктивних ядер, ГГц", "5,3"),
    ("Загальна кількість ядер", "14"),
    ("Кількість потоків", "20"),
    ("Базове тепловиділення TDP, Вт", "125"),
    ("Максимальне тепловиділення TDP, Вт", "181"),
    ("Тип пам'яті", "DDR5-5600/DDR4-3200"),
    ("Інтегрована графіка", "немає"),
    ("Кулер в комплекті", "немає"),
]


def test_offers_median_ignores_used_offers():
    state = read_page_state(
        nuxt_page(CPU_ROWS, [(4499, "новый"), (4166, "новый"), (5000, "новый"), (2000, "б/у")])
    )
    assert state.offer_prices == [Decimal("4166"), Decimal("4499"), Decimal("5000")]
    assert state.median_price == Decimal("4499.00")


@pytest.mark.parametrize(
    ("kind", "rows", "expected"),
    [
        (
            "cpu",
            CPU_ROWS,
            {
                "socket": "LGA1700",
                "cores": 14,
                "threads": 20,
                "base_clock_ghz": 3.5,
                "boost_clock_ghz": 5.3,
                "tdp_w": 125,
                "max_power_w": 181,
                "memory_types": ["DDR4", "DDR5"],
                "integrated_graphics": False,
                "boxed_cooler": False,
                "supported_chipsets": ["H610", "B660", "H670", "Z690", "B760", "H770", "Z790"],
            },
        ),
        (
            "motherboard",
            [
                ("Тип роз'єму CPU", "Socket AM5"),
                ("Чіпсет", "AMD B650"),
                ("DIMM", "4xDDR5 6400+ МГц, до 128 ГБ"),
                ("Кількість M.2", "3"),
                ("SATA Revision 3.0", "4"),
                ("Форм-фактор", "microATX, 244х244 мм"),
            ],
            {
                "socket": "AM5",
                "chipset": "B650",
                "form_factor": "Micro-ATX",
                "memory_type": "DDR5",
                "memory_slots": 4,
                "max_memory_gb": 128,
                "m2_slots": 3,
                "sata_ports": 4,
            },
        ),
        (
            "psu",
            [
                ("Форм-фактор БЖ", "SFX"),
                ("Потужність сумарна, Вт", "750"),
                ("Сертифікат 80 PLUS", "80 PLUS Platinum"),
            ],
            {"wattage": 750, "form_factor": "SFX", "efficiency": "80+ Platinum"},
        ),
        (
            "case",
            [
                ("Форм-фактор материнської плати", "E-ATX / ATX / MicroATX / Mini-ITX"),
                ("Максимальна довжина відеокарти, мм", "до 410 мм"),
                ("Максимальна висота процесорного кулера, мм", "76/153/170"),
            ],
            {
                "supported_form_factors": ["E-ATX", "ATX", "Micro-ATX", "Mini-ITX"],
                "max_gpu_length_mm": 410,
                "max_cooler_height_mm": 170,
                "psu_form_factors": ["ATX"],
            },
        ),
        (
            "cooler",
            [
                ("Тип", "Повітряне охолодження"),
                ("Призначення", "для процесора"),
                ("Socket 1700, 1851", "є"),
                ("Socket AM5", "є"),
                ("Socket AM4", "немає"),
                ("Розміри кулера, мм", "127x97x155"),
                ("Розсіювана потужність, Вт", "220"),
            ],
            {
                "type": "air",
                "sockets": ["LGA1700", "LGA1851", "AM5"],
                "height_mm": 155,
                "tdp_rating_w": 220,
            },
        ),
        (
            "cooler",
            [
                ("Тип", "Водяне охолодження"),
                ("Призначення", "для процесора"),
                ("Socket AM5", "є"),
                ("Кількість вентиляторів", "3"),
                ("Розміри вентилятора, мм", "120"),
            ],
            {"type": "liquid", "sockets": ["AM5"], "radiator_mm": 360},
        ),
        ("cooler", [("Тип", "Вентилятор"), ("Призначення", "для корпусу")], {}),
        (
            "gpu",
            [
                ("GPU", "Radeon RX 9070 XT"),
                ("Об'єм пам'яті, ГБ", "16"),
                ("Розміри, мм", "320 x 120.25 x 61.6"),
                ("Рекомендована потужність блоку живлення, Вт", "750"),
            ],
            {
                "chipset": "Radeon RX 9070 XT",
                "vram_gb": 16,
                "length_mm": 320,
                "recommended_psu_w": 750,
            },
        ),
        (
            "storage",
            [("Об'єм, ГБ", "1000"), ("Інтерфейс", "M.2 (PCI-E 4.0 x4)")],
            {"capacity_gb": 1000, "interface": "M.2 NVMe"},
        ),
        ("storage", [("Об'єм, ГБ", "1000"), ("Інтерфейс", "USB 3.2 Gen 2 Type-C")], {}),
        (
            "ram",
            [
                ("Обсяг, ГБ", "32"),
                ("Кількість планок в комплекті", "2"),
                ("Тип", "DDR5"),
                ("Ефективна частота, МТ/с", "6000"),
                ("Формфактор пам'яті", "288-pin DIMM"),
            ],
            {"modules": 2, "module_size_gb": 16, "memory_type": "DDR5", "speed_mhz": 6000},
        ),
    ],
)
def test_spec_sheet_mapping(kind, rows, expected):
    assert specs_from_rows(kind, rows, gpu_chips=["Radeon RX 9070 XT"]) == expected


def test_product_data_carries_offers_and_specs():
    ld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Intel Core i5-14600KF",
        "offers": {"@type": "AggregateOffer", "lowPrice": 4166, "priceCurrency": "UAH"},
    }
    html = f'<script type="application/ld+json">{json.dumps(ld)}</script>' + nuxt_page(
        CPU_ROWS, [(4499, "новый"), (4166, "новый"), (5000, "новый")]
    )
    data = extract_product(html, "https://hotline.example/x/")
    assert data.low_price == Decimal("4166")
    assert data.median_price == Decimal("4499.00")
    assert ("Тип роз'єму", "Socket 1700") in data.raw_specs


# --- Refresh: typical price, daily history, specs filled in -------------------------------


@pytest.fixture
def rate(db):
    return ExchangeRate.objects.create(
        currency="USD", rate=Decimal("40.0000"), rate_date=date(2026, 9, 1)
    ).rate


def refresh(listing, rate, html):
    with responses.RequestsMock() as mocked:
        mocked.get("https://hotline.example/robots.txt", status=404)
        mocked.get(listing.url, body=html)
        return refresh_listing(listing, Fetcher(user_agent="TestBot", min_interval=0), rate)


def cpu_page(name: str, offers: list[tuple[float, str]], rows=CPU_ROWS) -> str:
    ld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name,
        "offers": {
            "@type": "AggregateOffer",
            "lowPrice": min(p for p, _ in offers),
            "highPrice": max(p for p, _ in offers),
            "priceCurrency": "UAH",
            "offerCount": len(offers),
            "availability": "https://schema.org/InStock",
        },
    }
    return f'<script type="application/ld+json">{json.dumps(ld)}</script>' + nuxt_page(rows, offers)


def test_refresh_uses_median_and_records_one_point_per_day(comp, rate):
    cpu = comp("Core i5-14600K")
    listing = MarketListing.objects.create(
        component=cpu, url="https://hotline.example/intel-core-i5-14600k/"
    )
    offers = [(8000, "новый"), (10000, "новый"), (12000, "новый"), (20000, "новый")]
    assert refresh(listing, rate, cpu_page("Intel Core i5-14600K", offers)) == "ok"

    cpu.refresh_from_db()
    assert cpu.price == Decimal("275.00")  # median 11 000 UAH / 40, not the 8 000 minimum
    point = PriceHistory.objects.get(component=cpu)
    assert (point.price, point.low_price, point.high_price) == (
        Decimal("275.00"),
        Decimal("200.00"),
        Decimal("500.00"),
    )
    # A second check the same day updates today's point instead of adding one.
    refresh(listing, rate, cpu_page("Intel Core i5-14600K", offers[:3]))
    assert PriceHistory.objects.filter(component=cpu).count() == 1
    assert PriceHistory.objects.get(component=cpu).price == Decimal("250.00")


def test_refresh_fills_missing_specs_but_never_overwrites(comp, rate):
    cpu = comp("Core i5-14600K")
    curated = dict(cpu.specs)
    listing = MarketListing.objects.create(
        component=cpu, url="https://hotline.example/intel-core-i5-14600k/"
    )
    rows = [*CPU_ROWS[:6], ("Базове тепловиділення TDP, Вт", "999")]  # a wrong value upstream
    refresh(listing, rate, cpu_page("Intel Core i5-14600K", [(10000, "новый")], rows=rows))

    cpu.refresh_from_db()
    assert {k: cpu.specs[k] for k in curated} == curated  # hand-checked data untouched
    assert cpu.specs["tdp_w"] == curated["tdp_w"]


def test_catalog_only_part_becomes_buildable_when_the_source_has_specs(db, rate):
    part = Component.objects.create(
        category_id=Component.objects.filter(category__kind="cpu").first().category_id,
        manufacturer=Component.objects.filter(category__kind="cpu").first().manufacturer,
        name="Core i5-14600KF",
        slug="core-i5-14600kf",
        sku="BX8071514600KF",
        price=Decimal("300.00"),
        specs={},
    )
    assert not part.specs_complete
    listing = MarketListing.objects.create(
        component=part, url="https://hotline.example/intel-core-i5-14600kf/"
    )
    refresh(listing, rate, cpu_page("Intel Core i5-14600KF", [(10000, "новый")]))

    part.refresh_from_db()
    assert part.specs_complete
    assert part.specs["max_power_w"] == 181 and part.specs["boxed_cooler"] is False


def test_price_history_endpoint_filters_by_days(api, comp):
    cpu = comp("Ryzen 5 7600")
    now = timezone.now()
    for days_ago, price in ((200, "180.00"), (40, "190.00"), (5, "185.00")):
        PriceHistory.objects.create(
            component=cpu, price=Decimal(price), recorded_at=now - timedelta(days=days_ago)
        )
    rows = api.get(f"/api/components/{cpu.slug}/price-history/?days=30").json()
    assert [r["price"] for r in rows] == ["185.00"]
    rows = api.get(f"/api/components/{cpu.slug}/price-history/").json()
    assert [r["price"] for r in rows] == ["180.00", "190.00", "185.00"]  # oldest first
    assert {"low_price", "high_price", "recorded_at"} <= set(rows[0])


def test_record_daily_price_keeps_separate_days(comp):
    cpu = comp("Ryzen 5 7600")
    yesterday = PriceHistory.objects.create(
        component=cpu,
        price=Decimal("100.00"),
        source="hotline.ua",
        recorded_at=timezone.now() - timedelta(days=1),
    )
    record_daily_price(cpu, Decimal("110.00"), source="hotline.ua")
    assert PriceHistory.objects.filter(component=cpu).count() == 2
    yesterday.refresh_from_db()
    assert yesterday.price == Decimal("100.00")


# --- Cooling capacity ------------------------------------------------------------------------


def cpu_part(**specs):
    base = {
        "socket": "LGA1700",
        "tdp_w": 125,
        "cores": 20,
        "threads": 28,
        "integrated_graphics": True,
    }
    return c.Part(1, c.CPU, "Core i7-14700K", {**base, **specs})


def cooler_part(rating=None):
    specs = {"type": "air", "sockets": ["LGA1700", "AM5"], "height_mm": 150}
    if rating is not None:
        specs["tdp_rating_w"] = rating
    return c.Part(2, c.COOLER, "Tower 150", specs)


def codes(parts):
    report = c.check(parts)
    return {i.code: i for i in report.warnings + report.errors}


def test_cooler_below_tdp_warns_with_a_recommendation():
    issue = codes([cpu_part(max_power_w=253), cooler_part(100)])["COOLER_UNDERRATED"]
    assert issue.params["recommended"] == 260
    assert issue.severity == "warning"


def test_cooler_above_tdp_but_below_load_power_warns():
    # A 150 W cooler passes the 125 W TDP, but the chip draws 253 W under load.
    found = codes([cpu_part(max_power_w=253), cooler_part(150)])
    assert "COOLER_UNDERRATED" not in found
    assert found["COOLER_LOW_HEADROOM"].params == {
        "cooler": "Tower 150",
        "rating": 150,
        "cpu": "Core i7-14700K",
        "tdp": 125,
        "load": 253,
        "recommended": 260,
    }


def test_amd_load_power_is_the_ppt():
    ryzen = c.Part(
        1, c.CPU, "Ryzen 9 9950X", {"socket": "AM5", "tdp_w": 170, "integrated_graphics": True}
    )
    assert c.cpu_load_power(ryzen) == 230  # 1.35 × 170
    assert "COOLER_LOW_HEADROOM" in codes([ryzen, cooler_part(220)])
    assert not {"COOLER_LOW_HEADROOM", "COOLER_UNDERRATED"} & set(codes([ryzen, cooler_part(250)]))


def test_unknown_cooler_rating_warns():
    assert "COOLER_RATING_UNKNOWN" in codes([cpu_part(), cooler_part(None)])


def test_cpu_without_boxed_cooler_needs_one():
    found = codes([cpu_part(boxed_cooler=False, max_power_w=253)])
    assert found["COOLER_REQUIRED"].params["recommended"] == 260
    assert "NO_COOLER" not in found
    assert not {"COOLER_REQUIRED", "NO_COOLER"} & set(codes([cpu_part(boxed_cooler=True)]))


def test_air_cooler_without_height_warns_instead_of_crashing():
    cooler = c.Part(2, c.COOLER, "Mystery", {"type": "air", "sockets": ["LGA1700"]})
    case = c.Part(
        3,
        c.CASE,
        "Case",
        {
            "supported_form_factors": ["ATX"],
            "max_gpu_length_mm": 330,
            "max_cooler_height_mm": 160,
            "psu_form_factors": ["ATX"],
        },
    )
    assert "COOLER_HEIGHT_UNKNOWN" in codes([cpu_part(), cooler, case])
