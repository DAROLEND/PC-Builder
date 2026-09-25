"""Catalog operations shared by the advisor planners.

These are the same building blocks the public API uses: ``compatible_q`` is
what ``GET /components/?compatible_with=`` runs, and ``check_components`` is
what ``POST /compatibility/check/`` runs. The advisor therefore cannot
recommend something the API itself would reject.
"""

from decimal import Decimal
from typing import Any

from apps.builds import compatibility
from apps.catalog.compat_query import compatible_q
from apps.catalog.models import Component

# Warnings a person may accept in the configurator, but an advisor must never
# recommend: the build works on paper and disappoints in use. A cooler rated
# between the CPU's TDP and its real load (a 9950X3D is "170 W" on the box and
# draws 230 W) throttles under every long game or render.
BLOCKING_WARNINGS = frozenset(
    {
        "COOLER_UNDERRATED",
        "COOLER_LOW_HEADROOM",
        "COOLER_RATING_UNKNOWN",
        "PSU_LOW_HEADROOM",
        "PSU_BELOW_GPU_RECOMMENDATION",
    }
)

# Spec keys worth showing to the model when it browses the catalog.
KEY_SPECS = {
    "cpu": ["socket", "cores", "threads", "boost_clock_ghz", "tdp_w", "integrated_graphics"],
    "motherboard": ["socket", "chipset", "form_factor", "memory_type", "m2_slots"],
    "ram": ["memory_type", "modules", "module_size_gb", "speed_mhz"],
    "gpu": ["chipset", "vram_gb", "length_mm", "tdp_w"],
    "storage": ["interface", "capacity_gb"],
    "psu": ["wattage", "form_factor", "efficiency"],
    "case": ["supported_form_factors", "max_gpu_length_mm", "max_cooler_height_mm"],
    "cooler": ["type", "tdp_rating_w", "height_mm", "radiator_mm"],
}


def load_components(ids: list[int]) -> list[Component]:
    found = {c.id: c for c in Component.objects.buildable().with_market().filter(id__in=ids)}
    missing = [i for i in ids if i not in found]
    if missing:
        raise ValueError(f"Unknown or inactive component ids: {missing}")
    return [found[i] for i in ids]


def to_part(component: Component) -> compatibility.Part:
    return compatibility.Part(
        id=component.id, kind=component.kind, name=str(component), specs=component.specs
    )


def describe(component: Component) -> dict[str, Any]:
    specs = {k: component.specs[k] for k in KEY_SPECS[component.kind] if k in component.specs}
    if component.kind == "cpu":
        # What the cooler has to handle; the box TDP understates it.
        specs["load_power_w"] = compatibility.cpu_load_power(to_part(component))
    return {
        "id": component.id,
        "name": str(component),
        "category": component.kind,
        "price_usd": str(component.price),
        "specs": specs,
    }


def search_components(
    *,
    category: str,
    max_price: Decimal | float | None = None,
    compatible_with: list[int] | None = None,
    query: str | None = None,
    limit: int = 15,
) -> list[Component]:
    qs = Component.objects.buildable().with_related().filter(category__kind=category)
    if max_price is not None:
        qs = qs.filter(price__lte=max_price)
    if query:
        qs = qs.filter(name__icontains=query)
    if compatible_with:
        parts = [to_part(c) for c in load_components(compatible_with) if c.kind != category]
        qs = qs.filter(compatible_q(category, parts))
    return list(qs.order_by("-price")[:limit])


def check_components(ids: list[int]) -> tuple[compatibility.Report, Decimal]:
    components = load_components(ids)
    report = compatibility.check(to_part(c) for c in components)
    total = sum((c.price for c in components), Decimal("0"))
    return report, total
