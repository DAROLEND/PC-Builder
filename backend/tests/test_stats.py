from decimal import Decimal

import pytest
from django.db.models import Max, Min

from apps.catalog.models import Component
from tests.factories import make_build

pytestmark = pytest.mark.django_db


@pytest.fixture
def usage(user, comp):
    ssd, cpu_a, cpu_b = comp("P3 Plus 1TB"), comp("Ryzen 5 7600"), comp("Ryzen 5 5600")
    make_build(user, [ssd, cpu_a], name="a")
    make_build(user, [ssd, cpu_a], name="b")
    make_build(user, [ssd, cpu_b], name="c")
    make_build(user, [cpu_b], name="private", is_public=False)  # must not count
    return ssd, cpu_a, cpu_b


def test_popular_components(api, usage):
    ssd, cpu_a, cpu_b = usage
    rows = api.get("/api/stats/popular-components/?limit=3").data
    assert [(r["name"], r["build_count"]) for r in rows] == [
        (ssd.name, 3),
        (cpu_a.name, 2),
        (cpu_b.name, 1),
    ]


def test_top_per_category_window(api, usage):
    rows = api.get("/api/stats/top-per-category/?top=1").data
    by_kind = {r["kind"]: r for r in rows}
    assert by_kind["cpu"]["name"] == "Ryzen 5 7600"
    assert by_kind["cpu"]["rank"] == 1
    assert by_kind["storage"]["build_count"] == 3
    assert len(rows) == 2  # only categories that appear in public builds


def test_category_stats(api):
    rows = api.get("/api/stats/categories/").data
    gpu = next(r for r in rows if r["kind"] == "gpu")
    expected = Component.objects.filter(category__kind="gpu").aggregate(
        lo=Min("price"), hi=Max("price")
    )
    assert gpu["components"] == 9
    assert Decimal(gpu["min_price"]) == expected["lo"]
    assert Decimal(gpu["max_price"]) == expected["hi"]


def test_price_position(api):
    rows = api.get("/api/stats/price-position/?category=case").data
    assert rows[0]["price_rank"] == 1
    assert rows[0]["percentile"] == 0.0
    assert rows[-1]["percentile"] == 1.0
    assert api.get("/api/stats/price-position/?category=nope").status_code == 400


def test_cheapest_build_with_gpu(api, user, comp):
    gpu, cheap_cpu = comp("PULSE Radeon RX 7600 8GB"), comp("Ryzen 5 5600")
    make_build(user, [gpu, comp("Ryzen 9 9950X")], name="expensive")
    cheap = make_build(user, [gpu, cheap_cpu], name="cheap")
    make_build(user, [cheap_cpu], name="no gpu")

    resp = api.get(f"/api/stats/cheapest-build/?gpu={gpu.id}")
    assert resp.status_code == 200
    assert resp.data["id"] == cheap.id
    # The whole build, not just the GPU line.
    assert Decimal(resp.data["total_price"]) == gpu.price + cheap_cpu.price


def test_cheapest_build_not_found(api, comp):
    gpu = comp("Intel Arc B580 Challenger 12GB OC")
    assert api.get(f"/api/stats/cheapest-build/?gpu={gpu.id}").status_code == 404
