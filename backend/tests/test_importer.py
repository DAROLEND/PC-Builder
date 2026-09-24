"""Catalog import from the aggregator, photo mirroring and catalog-only parts."""

import io
import json
from datetime import date
from decimal import Decimal

import pytest
import responses
from PIL import Image

from apps.builds import compatibility as c
from apps.catalog.images import make_variants, mirror_images
from apps.catalog.importer import (
    gpu_specs,
    import_category,
    is_desktop_part,
    product_urls,
    ram_specs,
    storage_specs,
)
from apps.catalog.market import Fetcher
from apps.catalog.models import Category, Component, ExchangeRate, Manufacturer, MarketListing

HOTLINE = "https://hotline.ua"
GPU_PAGE = f"{HOTLINE}/ua/computer/videokarty/"
CARD_URL = f"{HOTLINE}/ua/computer-videokarty/gigabyte-geforce-rtx-5070-ti-gaming-oc-16g/"
PHOTO_URL = "https://img.hotline.example/photo/1.jpg"


def fetcher() -> Fetcher:
    return Fetcher(user_agent="TestBot", min_interval=0)


def png(size=(1600, 1200), mode="RGBA") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, (255, 0, 0, 128) if mode == "RGBA" else (255, 0, 0)).save(
        buffer, format="PNG"
    )
    return buffer.getvalue()


def product_page(
    name: str, brand: str, price: int, images: list[str] | None = None, shops: int = 12
) -> str:
    images = [PHOTO_URL] if images is None else images
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name,
        "brand": {"@type": "Brand", "name": brand},
        "image": images,
        "offers": {
            "@type": "AggregateOffer",
            "lowPrice": price,
            "highPrice": price + 1000,
            "priceCurrency": "UAH",
            "offerCount": shops,
            "availability": "https://schema.org/InStock",
        },
    }
    return f'<html><script type="application/ld+json">{json.dumps(product)}</script></html>'


def hotline_mock() -> responses.RequestsMock:
    """Hotline pages plus its image CDN (photos are required for an import)."""
    mocked = responses.RequestsMock(assert_all_requests_are_fired=False)
    mocked.get(f"{HOTLINE}/robots.txt", status=404)
    mocked.get("https://img.hotline.example/robots.txt", status=404)
    mocked.get(PHOTO_URL, body=png((400, 300), "RGB"), content_type="image/png")
    return mocked


# --- specs derived from titles (no database) -----------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (
            "GIGABYTE GeForce RTX 5070 Ti GAMING OC 16G (GV-N507TGAMING OC-16GD)",
            {"chipset": "GeForce RTX 5070 Ti", "vram_gb": 16, "tdp_w": 300},
        ),
        (
            "ASUS DUAL-RTX5070-O12G (90YV0M17-M0NA00)",
            {"chipset": "GeForce RTX 5070", "vram_gb": 12, "tdp_w": 250},
        ),
        # No memory size in the title, but the chip only exists with 12 GB.
        (
            "Zotac GAMING GeForce RTX 5070 Twin Edge OC (ZT-B50700H-10P)",
            {"chipset": "GeForce RTX 5070", "vram_gb": 12},
        ),
        (
            "Sapphire PULSE Radeon RX 9070 XT 16GB (11348-03-20G)",
            {"chipset": "Radeon RX 9070 XT", "vram_gb": 16},
        ),
        # Chip with two memory sizes and none in the title: VRAM stays unknown.
        ("MSI GeForce RTX 5060 Ti VENTUS 2X OC", {"chipset": "GeForce RTX 5060 Ti"}),
    ],
)
def test_gpu_specs_from_title(title, expected):
    specs = gpu_specs(title)
    assert expected.items() <= specs.items()
    if "vram_gb" not in expected:
        assert "vram_gb" not in specs


def test_gpu_specs_prefers_the_longest_chip_name():
    assert gpu_specs("MSI GeForce RTX 4070 Ti SUPER 16G")["chipset"] == "GeForce RTX 4070 Ti SUPER"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (
            "Kingston FURY 32 GB (2x16GB) DDR5 6000 MHz Beast EXPO (KF560C30BBEK2-32)",
            {"memory_type": "DDR5", "modules": 2, "module_size_gb": 16, "speed_mhz": 6000},
        ),
        (
            "GOODRAM 16 GB DDR4 3200 MHz IRDM X (IR-X3200D464L16/16G)",
            {"memory_type": "DDR4", "modules": 1, "module_size_gb": 16, "speed_mhz": 3200},
        ),
        ("Crucial 16 GB SO-DIMM DDR5 5600 MHz (CT16G56C46S5)", {}),  # laptop memory
    ],
)
def test_ram_specs_from_title(title, expected):
    assert ram_specs(title) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (
            "Samsung 990 PRO 2 TB M.2 NVMe (MZ-V9P2T0BW)",
            {"capacity_gb": 2000, "interface": "M.2 NVMe"},
        ),
        (
            'Kingston A400 960 GB 2.5" SATA (SA400S37/960G)',
            {"capacity_gb": 960, "interface": "SATA"},
        ),
        # Interface not in the title, but the product line only exists as NVMe / SATA.
        ("Kingston NV3 1 TB (SNV3S-1000G)", {"capacity_gb": 1000, "interface": "M.2 NVMe"}),
        ("WD Black SN850X 1 TB (WDS100T2X0E)", {"capacity_gb": 1000, "interface": "M.2 NVMe"}),
        ("Kingston A400 480 GB (SA400S37-480G)", {"capacity_gb": 480, "interface": "SATA"}),
        # Line sold in several form factors: stays unknown rather than guessed.
        ("WD Red SA500 4 TB (WDS400T2R0A)", {"capacity_gb": 4000}),
    ],
)
def test_storage_specs_from_title(title, expected):
    assert storage_specs(title) == expected


@pytest.mark.parametrize(
    ("kind", "title", "keep"),
    [
        ("cooler", "DeepCool AK620 Digital SE Black (R-AK620-BKADMN-GJD)", True),
        ("cooler", "Arctic Liquid Freezer III Pro 360 (ACFRE00180A)", True),
        ("cooler", "Arctic P12 Pro PST Black (ACFAN00306A)", False),
        ("cooler", "Noctua NF-A12x25 G2 PWM chromax.black", False),
        ("cooler", "be quiet! Pure Wings 3 140 PWM (BL108)", False),
        ("cooler", "Arctic P12 Pro Reverse A-RGB 3-Pack White (ACFAN00334A)", False),
        ("cooler", "Vinga 14025 PWM 4pin Black", False),
        ("ram", "Crucial 16 GB SO-DIMM DDR5 5600 MHz (CT16G56C46S5)", False),
        ("ram", "Crucial 16 GB DDR5 5600 MHz (CT16G56C46U5)", True),
        ("storage", "Kingston XS2000 2 TB (SXS2000-2000GA)", False),
        ("storage", "Samsung T7 Shield 2 TB (MU-PE2T0S/EU)", False),
        ("storage", "Kingston KC3000 2048 GB (SKC3000D-2048G)", True),
    ],
)
def test_non_desktop_parts_are_skipped(kind, title, keep):
    assert is_desktop_part(kind, title) is keep


# --- crawling and import ----------------------------------------------------------------


@pytest.fixture
def rate(db):
    return ExchangeRate.objects.create(
        currency="USD", rate=Decimal("40.0000"), rate_date=date(2026, 9, 1)
    ).rate


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def test_product_urls_are_collected_across_pages_and_deduplicated():
    page1 = '<a href="/ua/computer-videokarty/a-1/">A</a><a href="/ua/computer-videokarty/b-2/">'
    page2 = '<a href="/ua/computer-videokarty/b-2/">B</a><a href="/ua/other/c/">no</a>'
    with hotline_mock() as mocked:
        mocked.get(GPU_PAGE, body=page1)
        mocked.get(f"{GPU_PAGE}?p=2", body=page2)
        mocked.get(f"{GPU_PAGE}?p=3", body="<html>nothing</html>")
        urls = product_urls(fetcher(), "gpu", pages=5)
    assert urls == [
        f"{HOTLINE}/ua/computer-videokarty/a-1/",
        f"{HOTLINE}/ua/computer-videokarty/b-2/",
    ]


def test_import_creates_buildable_gpu_with_listing_and_photos(db, rate, media):
    known = f"{HOTLINE}/ua/computer-videokarty/already-tracked/"
    MarketListing.objects.create(component=Component.objects.first(), url=known)
    category_html = (
        f'<a href="{CARD_URL[len(HOTLINE) :]}"></a><a href="{known[len(HOTLINE) :]}"></a>'
    )

    with hotline_mock() as mocked:
        mocked.get(GPU_PAGE, body=category_html)
        mocked.get(
            CARD_URL,
            body=product_page(
                "GIGABYTE GeForce RTX 5070 Ti GAMING OC 16G (GV-N507TGAMING OC-16GD)",
                "GIGABYTE",
                62_000,
            ),
        )
        stats = import_category("gpu", pages=1, fetcher=fetcher())

    assert (stats.seen, stats.created, stats.buildable, stats.skipped) == (2, 1, 1, 1)
    part = Component.objects.get(listings__url=CARD_URL)
    # The part number moves from the name to the SKU.
    assert (part.name, part.sku) == ("GeForce RTX 5070 Ti GAMING OC 16G", "GV-N507TGAMING OC-16GD")
    # The seed has "Gigabyte"; the aggregator's "GIGABYTE" must not duplicate it.
    assert part.manufacturer.name.lower() == "gigabyte"
    assert Manufacturer.objects.filter(name__iexact="gigabyte").count() == 1
    assert part.price == Decimal("1550.00")  # 62 000 UAH / 40
    assert part.specs_complete and part.specs["chipset"] == "GeForce RTX 5070 Ti"
    assert part.listings.get().status == MarketListing.Status.OK
    photo = part.photos.get()
    assert photo.thumb.url.startswith("/media/products/thumbs/")
    assert part.image_url == photo.thumb.url


def test_import_of_a_part_with_unknown_specs_is_catalog_only(db, rate, media):
    url = f"{HOTLINE}/ua/computer-diski-ssd/wd-red-sa500-4-tb/"
    with hotline_mock() as mocked:
        mocked.get(f"{HOTLINE}/ua/computer/diski-ssd/", body=f'<a href="{url[len(HOTLINE) :]}">')
        mocked.get(url, body=product_page("WD Red SA500 4 TB (WDS400T2R0A)", "WD", 12000))
        stats = import_category("storage", pages=1, fetcher=fetcher())

    assert (stats.created, stats.buildable) == (1, 0)
    part = Component.objects.get(listings__url=url)
    assert part.specs == {"capacity_gb": 4000}
    assert not part.specs_complete


def test_import_of_a_category_without_title_specs(db, rate, media):
    """Cases get no specs from the title at all; an empty dict is still valid."""
    url = f"{HOTLINE}/ua/computer-korpusa/jonsbo-c6-max-black/"
    with hotline_mock() as mocked:
        mocked.get(f"{HOTLINE}/ua/computer/korpusa/", body=f'<a href="{url[len(HOTLINE) :]}">')
        mocked.get(url, body=product_page("Jonsbo C6 MAX Black", "Jonsbo", 2213))
        stats = import_category("case", pages=1, fetcher=fetcher())

    assert stats.errors == [] and stats.created == 1
    part = Component.objects.get(listings__url=url)
    assert (part.name, part.specs, part.specs_complete) == ("C6 MAX Black", {}, False)


# --- photos --------------------------------------------------------------------------------


def test_make_variants_produces_small_webp_on_white():
    thumb, large = make_variants(png())
    for data, bound in ((thumb, 360), (large, 1000)):
        image = Image.open(io.BytesIO(data))
        assert image.format == "WEBP"
        assert max(image.size) <= bound
        assert image.mode == "RGB"  # transparency flattened


def test_make_variants_rejects_non_images():
    with pytest.raises(ValueError):
        make_variants(b"<html>not an image</html>")


def test_mirror_images_respects_limit_and_skips_known_and_broken(comp, media):
    part = comp("Ryzen 5 7600")
    urls = [f"https://img.example/{i}.jpg" for i in range(4)]
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mocked:
        mocked.get("https://img.example/robots.txt", status=404)
        mocked.get(urls[0], body=b"broken", content_type="image/jpeg")
        for url in urls[1:]:
            mocked.get(url, body=png((400, 300), "RGB"), content_type="image/png")
        assert mirror_images(part, urls, fetcher(), limit=2) == 1  # 0 broken, 1 ok
        assert mirror_images(part, urls, fetcher(), limit=3) == 1  # 1 known, 2 new
    assert list(part.photos.values_list("source_url", "position")) == [(urls[1], 0), (urls[2], 1)]


# --- catalog-only parts stay out of builds -----------------------------------------------


@pytest.fixture
def catalog_only_gpu(db):
    return Component.objects.create(
        category=Category.objects.get(kind="gpu"),
        manufacturer=Manufacturer.objects.first(),
        name="Mystery GPU",
        slug="mystery-gpu",
        sku="MYSTERY-GPU",
        price=Decimal("300.00"),
        specs={"vram_gb": 8},  # no chipset / TDP
    )


def test_incomplete_specs_are_saved_but_flagged(catalog_only_gpu):
    assert not catalog_only_gpu.specs_complete
    catalog_only_gpu.specs.update(chipset="X", tdp_w=150)
    catalog_only_gpu.save()
    assert Component.objects.get(pk=catalog_only_gpu.pk).specs_complete


def test_api_exposes_missing_specs_and_filters_buildable(api, catalog_only_gpu):
    body = api.get(f"/api/components/{catalog_only_gpu.slug}/").json()
    assert body["specs_complete"] is False
    assert set(body["missing_specs"]) == {"chipset", "tdp_w"}

    names = {
        p["name"]
        for p in api.get("/api/components/?category=gpu&buildable=true&page_size=100").json()[
            "results"
        ]
    }
    assert "Mystery GPU" not in names and "PULSE Radeon RX 7600 8GB" in names


def test_catalog_only_part_cannot_be_checked_or_built(api, comp, catalog_only_gpu):
    response = api.post(
        "/api/compatibility/check/",
        {"items": [{"component": catalog_only_gpu.id, "quantity": 1}]},
        format="json",
    )
    assert response.status_code == 400
    assert "catalog-only" in json.dumps(response.json())

    cpu = comp("Ryzen 5 7600")
    compatible = api.get(f"/api/components/?category=gpu&compatible_with={cpu.id}&page_size=100")
    assert "Mystery GPU" not in {p["name"] for p in compatible.json()["results"]}


def test_unknown_gpu_length_is_a_warning_not_an_error():
    parts = [
        c.Part(1, c.GPU, "Card", {"chipset": "X", "vram_gb": 8, "tdp_w": 150}),
        c.Part(
            2,
            c.CASE,
            "Case",
            {
                "supported_form_factors": ["ATX"],
                "max_gpu_length_mm": 330,
                "max_cooler_height_mm": 160,
                "psu_form_factors": ["ATX"],
            },
        ),
    ]
    report = c.check(parts)
    codes = {i.code: i for i in report.warnings}
    assert "GPU_LENGTH_UNKNOWN" in codes
    assert codes["GPU_LENGTH_UNKNOWN"].params == {"gpu": "Card", "case": "Case", "limit": 330}
    assert not any(i.code.startswith("GPU_") for i in report.errors)


def test_part_already_in_the_catalog_is_not_duplicated(db, rate, media):
    url = f"{HOTLINE}/ua/computer-processory/amd-ryzen-5-7600/"
    with hotline_mock() as mocked:
        mocked.get(f"{HOTLINE}/ua/computer/processory/", body=f'<a href="{url[len(HOTLINE) :]}">')
        mocked.get(url, body=product_page("AMD Ryzen 5 7600", "AMD", 8000))
        stats = import_category("cpu", pages=1, fetcher=fetcher())

    assert (stats.created, stats.skipped) == (0, 1)
    assert Component.objects.filter(name="Ryzen 5 7600").count() == 1


def test_long_titles_that_differ_at_the_end_get_unique_skus(db, rate, media):
    base = "Kingston FURY 32 GB (2x16GB) DDR5 6000 MHz Beast Black Extra Long Edition Name Rev"
    urls = [f"{HOTLINE}/ua/computer-moduli-pamyati-dlya-pk-i-noutbukov/kit-{i}/" for i in (1, 2)]
    listing = "".join(f'<a href="{u[len(HOTLINE) :]}">' for u in urls)
    with hotline_mock() as mocked:
        mocked.get(f"{HOTLINE}/ua/computer/moduli-pamyati-dlya-pk-i-noutbukov/", body=listing)
        for i, url in enumerate(urls):
            mocked.get(url, body=product_page(f"{base} {i}", "Kingston FURY", 9000))
        stats = import_category("ram", pages=1, fetcher=fetcher())

    assert (stats.created, stats.errors) == (2, [])
    skus = list(Component.objects.filter(listings__url__in=urls).values_list("sku", flat=True))
    assert len(set(skus)) == 2 and all(len(sku) <= 64 for sku in skus)


def test_products_without_a_photo_are_not_imported(db, rate, media):
    url = f"{HOTLINE}/ua/computer-korpusa/no-photo/"
    with hotline_mock() as mocked:
        mocked.get(f"{HOTLINE}/ua/computer/korpusa/", body=f'<a href="{url[len(HOTLINE) :]}">')
        mocked.get(url, body=product_page("Nameless Case", "Nameless", 900, images=[]))
        stats = import_category("case", pages=1, fetcher=fetcher())

    assert (stats.created, stats.skipped) == (0, 1)
    assert not MarketListing.objects.filter(url=url).exists()


def test_box_and_tray_variants_become_one_part(db, rate, media):
    urls = [f"{HOTLINE}/ua/computer-processory/amd-ryzen-7-9700x-{v}/" for v in ("box", "tray")]
    listing = "".join(f'<a href="{u[len(HOTLINE) :]}">' for u in urls)
    with hotline_mock() as mocked:
        mocked.get(f"{HOTLINE}/ua/computer/processory/", body=listing)
        mocked.get(urls[0], body=product_page("AMD Ryzen 7 9700X (100-100001404WOF)", "AMD", 12000))
        mocked.get(urls[1], body=product_page("AMD Ryzen 7 9700X (100-000001404)", "AMD", 11500))
        stats = import_category("cpu", pages=1, fetcher=fetcher())

    assert (stats.created, stats.skipped) == (1, 1)
    part = Component.objects.get(name="Ryzen 7 9700X")
    assert part.sku == "100-100001404WOF"


def test_parts_sold_by_one_or_two_shops_are_not_imported(db, rate, media):
    url = f"{HOTLINE}/ua/computer-korpusa/rare-case/"
    with hotline_mock() as mocked:
        mocked.get(f"{HOTLINE}/ua/computer/korpusa/", body=f'<a href="{url[len(HOTLINE) :]}">')
        mocked.get(url, body=product_page("Rare Case X", "Rare", 3000, shops=2))
        stats = import_category("case", pages=1, fetcher=fetcher())
    assert (stats.created, stats.skipped) == (0, 1)
