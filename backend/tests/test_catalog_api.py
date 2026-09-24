from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import Category, Component, ExchangeRate, Manufacturer
from apps.catalog.specs import validate_specs

pytestmark = pytest.mark.django_db


def names(resp):
    return {row["name"] for row in resp.data["results"]}


def test_list_is_public_and_paginated(api):
    resp = api.get("/api/components/")
    assert resp.status_code == 200
    assert resp.data["count"] == Component.objects.count()
    assert len(resp.data["results"]) == 20


def test_filter_by_category_and_price(api):
    resp = api.get("/api/components/?category=gpu&max_price=450&page_size=100")
    expected = set(
        Component.objects.filter(category__kind="gpu", price__lte=450).values_list(
            "name", flat=True
        )
    )
    assert expected  # the fixture has budget GPUs
    assert names(resp) == expected
    assert all(Decimal(r["price"]) <= 450 for r in resp.data["results"])


def test_spec_filter_uses_jsonb_containment(api):
    with CaptureQueriesContext(connection) as ctx:
        resp = api.get("/api/components/?category=motherboard&socket=AM4")
    assert names(resp) == {"MAG B550 TOMAHAWK", "B450M Pro4"}
    # @> is what the GIN jsonb_path_ops index can serve.
    assert any("@>" in q["sql"] for q in ctx.captured_queries)


def test_compatible_with_filters_motherboards(api, comp):
    cpu, case = comp("Ryzen 7 9800X3D"), comp("MasterBox NR200P")
    resp = api.get(f"/api/components/?category=motherboard&compatible_with={cpu.id},{case.id}")
    # AM5, a chipset the 9800X3D supports (not A620), and Mini-ITX for the NR200P.
    assert names(resp) == {"B650I Lightning WiFi"}


def test_compatible_with_filters_gpus_by_case_length(api, comp):
    case = comp("CH370")
    resp = api.get(f"/api/components/?category=gpu&compatible_with={case.id}")
    lengths = [Component.objects.get(id=r["id"]).specs["length_mm"] for r in resp.data["results"]]
    assert lengths and max(lengths) <= 320
    assert "TUF Gaming GeForce RTX 5070 Ti 16GB" not in names(resp)


def test_compatible_with_psu_covers_estimated_power(api, comp):
    gpu, cpu = comp("ROG Astral GeForce RTX 5090 32GB"), comp("Ryzen 9 9950X")
    resp = api.get(f"/api/components/?category=psu&compatible_with={gpu.id},{cpu.id}")
    # ~770 W estimated load: 750 W units are errors and filtered out. The 850 W
    # unit stays: it works, the engine flags low headroom as a *warning*.
    assert names(resp) == {"RM850x", "Focus GX-1000 ATX 3.1", "Dark Power Pro 13 1300W"}


def test_compatible_with_requires_category(api, comp):
    case = comp("CH370")
    assert api.get(f"/api/components/?compatible_with={case.id}").status_code == 400
    assert api.get("/api/components/?category=gpu&compatible_with=abc").status_code == 400


def test_price_in_uah_uses_latest_rate(api, comp):
    ExchangeRate.objects.create(currency="USD", rate=Decimal("41.5000"), rate_date=date(2026, 9, 1))
    ExchangeRate.objects.create(currency="USD", rate=Decimal("42.0000"), rate_date=date(2026, 9, 2))
    part = comp("Ryzen 5 7600")
    resp = api.get(f"/api/components/{part.slug}/")
    assert Decimal(resp.data["price_uah"]) == (part.price * 42).quantize(Decimal("1"))


def test_only_staff_can_write(api, user):
    api.force_authenticate(user)
    assert api.post("/api/components/", {}).status_code == 403


def test_staff_create_validates_specs(api, user):
    user.is_staff = True
    user.save()
    api.force_authenticate(user)
    payload = {
        "name": "Test CPU",
        "slug": "test-cpu",
        "sku": "TEST-CPU",
        "price": "100.00",
        "category_id": Category.objects.get(kind="cpu").id,
        "manufacturer_id": Manufacturer.objects.get(name="AMD").id,
        "specs": {"socket": "AM5", "cores": "eight"},
    }
    resp = api.post("/api/components/", payload, format="json")
    assert resp.status_code == 400
    assert "cores" in resp.data["specs"]


def test_staff_can_create_incomplete_part_as_catalog_only(api, user):
    user.is_staff = True
    user.save()
    api.force_authenticate(user)
    payload = {
        "name": "Test CPU",
        "slug": "test-cpu",
        "sku": "TEST-CPU",
        "price": "100.00",
        "category_id": Category.objects.get(kind="cpu").id,
        "manufacturer_id": Manufacturer.objects.get(name="AMD").id,
        "specs": {"socket": "AM5", "cores": 8},
    }
    resp = api.post("/api/components/", payload, format="json")
    assert resp.status_code == 201
    assert resp.data["specs_complete"] is False
    assert "tdp_w" in resp.data["missing_specs"]


def test_negative_price_blocked_by_db_constraint(comp):
    part = comp("Ryzen 5 7600")
    with pytest.raises(IntegrityError), transaction.atomic():
        Component.objects.filter(pk=part.pk).update(price=Decimal("-1"))


def test_model_clean_rejects_bad_specs(comp):
    part = comp("Ryzen 5 7600")
    part.specs = {**part.specs, "threads": 2}
    with pytest.raises(ValidationError):
        part.full_clean()


@pytest.mark.parametrize(
    ("kind", "specs", "field"),
    [
        ("gpu", {"chipset": "x", "vram_gb": 8, "length_mm": True, "tdp_w": 100}, "length_mm"),
        (
            "ram",
            {"memory_type": "DDR3", "modules": 2, "module_size_gb": 8, "speed_mhz": 1600},
            "memory_type",
        ),
        ("storage", {"interface": "SATA", "capacity_gb": 500, "rpm": 7200}, "specs"),
        ("cooler", {"type": "air", "sockets": ["AM5"], "tdp_rating_w": 100}, "height_mm"),
    ],
)
def test_spec_schema_errors(kind, specs, field):
    assert field in validate_specs(kind, specs)
