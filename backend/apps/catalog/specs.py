"""Per-category specification schemas for ``Component.specs`` (JSONB).

Different categories have different characteristics (a CPU has a socket and
TDP, a GPU has length and VRAM), so specs live in one JSONB column instead of
a wide table with dozens of nullable columns. The price of that flexibility is
that the database no longer guarantees the shape of the data, so the shape is
checked here, in ``Component.clean()`` and in the component serializer.

The compatibility engine relies on these keys being present. A component may
be saved with some of them missing (e.g. imported from a price aggregator), but
then ``specs_complete`` is false and the part is catalog-only: it is excluded
from builds, compatibility filters and the advisor until someone fills it in.
"""

from dataclasses import dataclass
from typing import Any

from .models_enums import CategoryKind

# Allowed enumerations shared with the compatibility engine.
MEMORY_TYPES = {"DDR4", "DDR5"}
BOARD_FORM_FACTORS = {"E-ATX", "ATX", "Micro-ATX", "Mini-ITX"}
PSU_FORM_FACTORS = {"ATX", "SFX", "SFX-L"}
STORAGE_INTERFACES = {"M.2 NVMe", "M.2 SATA", "SATA"}


@dataclass(frozen=True)
class Field:
    type: type | tuple[type, ...]
    required: bool = True
    choices: set[str] | None = None
    min_value: float | None = None
    list_of: type | None = None
    list_choices: set[str] | None = None


INT = int
NUM = (int, float)

SCHEMAS: dict[str, dict[str, Field]] = {
    CategoryKind.CPU: {
        "socket": Field(str),
        "cores": Field(INT, min_value=1),
        "threads": Field(INT, min_value=1),
        "base_clock_ghz": Field(NUM, min_value=0),
        "boost_clock_ghz": Field(NUM, min_value=0),
        "tdp_w": Field(INT, min_value=1),
        "integrated_graphics": Field(bool),
        "supported_chipsets": Field(list, list_of=str),
        "memory_types": Field(list, list_of=str, list_choices=MEMORY_TYPES),
        # Sustained power under load (Intel "maximum turbo power"). When absent
        # it is derived from the TDP; see compatibility.cpu_load_power().
        "max_power_w": Field(INT, min_value=1, required=False),
        "boxed_cooler": Field(bool, required=False),
    },
    CategoryKind.MOTHERBOARD: {
        "socket": Field(str),
        "chipset": Field(str),
        "form_factor": Field(str, choices=BOARD_FORM_FACTORS),
        "memory_type": Field(str, choices=MEMORY_TYPES),
        "memory_slots": Field(INT, min_value=1),
        "max_memory_gb": Field(INT, min_value=1),
        "m2_slots": Field(INT, min_value=0),
        "sata_ports": Field(INT, min_value=0),
    },
    CategoryKind.RAM: {
        "memory_type": Field(str, choices=MEMORY_TYPES),
        "modules": Field(INT, min_value=1),
        "module_size_gb": Field(INT, min_value=1),
        "speed_mhz": Field(INT, min_value=1),
    },
    CategoryKind.GPU: {
        "chipset": Field(str),
        "vram_gb": Field(INT, min_value=1),
        # Optional: board partners rarely publish it in structured form. When
        # unknown, the engine warns instead of checking the case clearance.
        "length_mm": Field(INT, min_value=1, required=False),
        "tdp_w": Field(INT, min_value=1),
        "recommended_psu_w": Field(INT, min_value=1, required=False),
    },
    CategoryKind.STORAGE: {
        "interface": Field(str, choices=STORAGE_INTERFACES),
        "capacity_gb": Field(INT, min_value=1),
    },
    CategoryKind.PSU: {
        "wattage": Field(INT, min_value=1),
        "form_factor": Field(str, choices=PSU_FORM_FACTORS),
        "efficiency": Field(str, required=False),
    },
    CategoryKind.CASE: {
        "supported_form_factors": Field(list, list_of=str, list_choices=BOARD_FORM_FACTORS),
        "max_gpu_length_mm": Field(INT, min_value=1),
        "max_cooler_height_mm": Field(INT, min_value=1),
        "psu_form_factors": Field(list, list_of=str, list_choices=PSU_FORM_FACTORS),
        "max_radiator_mm": Field(INT, min_value=0, required=False),
    },
    CategoryKind.COOLER: {
        "type": Field(str, choices={"air", "liquid"}),
        "sockets": Field(list, list_of=str),
        "height_mm": Field(INT, min_value=1, required=False),
        "radiator_mm": Field(INT, min_value=1, required=False),
        # Many liquid coolers publish no rating; the engine then warns.
        "tdp_rating_w": Field(INT, min_value=1, required=False),
    },
}


def validate_specs(kind: str, specs: Any, *, partial: bool = False) -> dict[str, list[str]]:
    """Return ``{field: [errors]}``; an empty dict means the specs are valid.

    ``partial=True`` accepts missing required fields but still checks the
    ones that are present. Imported products start like that: they can be
    browsed in the catalog, but only complete ones take part in builds.
    """
    if not isinstance(specs, dict):
        return {"specs": ["Specs must be a JSON object."]}

    schema = SCHEMAS.get(kind)
    if schema is None:
        return {"specs": [f"Unknown category kind '{kind}'."]}

    errors: dict[str, list[str]] = {}

    def add(field: str, message: str) -> None:
        errors.setdefault(field, []).append(message)

    for name, field in schema.items():
        if name not in specs:
            if field.required and not partial:
                add(name, "This field is required.")
            continue
        value = specs[name]
        # bool is a subclass of int: reject True/False where a number is expected.
        if isinstance(value, bool) and field.type is not bool:
            add(name, "Expected a number, got a boolean.")
            continue
        if not isinstance(value, field.type):
            add(name, f"Invalid type {type(value).__name__}.")
            continue
        if field.choices and value not in field.choices:
            add(name, f"Must be one of: {', '.join(sorted(field.choices))}.")
        if field.min_value is not None and value < field.min_value:
            add(name, f"Must be >= {field.min_value}.")
        if field.list_of is not None:
            if not value:
                add(name, "Must not be empty.")
            if any(not isinstance(item, field.list_of) for item in value):
                add(name, f"All items must be {field.list_of.__name__}.")
            elif field.list_choices and not set(value) <= field.list_choices:
                bad = sorted(set(value) - field.list_choices)
                add(name, f"Unknown values: {', '.join(bad)}.")

    unknown = set(specs) - set(schema)
    if unknown:
        add("specs", f"Unknown keys: {', '.join(sorted(unknown))}.")

    # Cross-field rules inside a single component (only on complete data).
    if partial and missing_fields(kind, specs):
        return errors
    if kind == CategoryKind.CPU and not errors and specs["threads"] < specs["cores"]:
        add("threads", "Threads cannot be fewer than cores.")
    # A missing size is incompleteness (catalog-only), not an invalid value.
    if kind == CategoryKind.COOLER and not errors and not partial:
        if specs["type"] == "air" and "height_mm" not in specs:
            add("height_mm", "Air coolers must specify height_mm.")
        if specs["type"] == "liquid" and "radiator_mm" not in specs:
            add("radiator_mm", "Liquid coolers must specify radiator_mm.")

    return errors


def missing_fields(kind: str, specs: dict) -> list[str]:
    """Required spec fields that are not filled in yet."""
    schema = SCHEMAS.get(kind, {})
    return [name for name, field in schema.items() if field.required and name not in specs]


def is_complete(kind: str, specs: Any) -> bool:
    return isinstance(specs, dict) and not validate_specs(kind, specs)
