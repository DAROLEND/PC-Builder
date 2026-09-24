"""Build compatibility engine.

Deliberately framework-free: it takes plain ``Part`` objects and returns a
``Report``. The ORM, serializers, the AI advisor and the stateless
``/compatibility/check/`` endpoint all adapt their data to ``Part`` and call
``check()``. That keeps every rule unit-testable without a database and
guarantees that the API and the advisor apply exactly the same rules.

Severity model:
* ``error``   – the build physically cannot work (wrong socket, GPU does not
  fit, PSU below the estimated load). Saving a build with errors is rejected.
* ``warning`` – it works but is a bad idea or cannot be verified (low PSU
  headroom, cooler rated below CPU TDP, GPU fits with <10 mm to spare).
* missing required parts are reported separately, so an incomplete build can
  be saved as a draft while the user is still choosing parts.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

# Kinds are duplicated as plain strings on purpose: the engine must not
# import Django. They are kept in sync with catalog.CategoryKind by a test.
CPU, MOTHERBOARD, RAM, GPU, STORAGE, PSU, CASE, COOLER = (
    "cpu",
    "motherboard",
    "ram",
    "gpu",
    "storage",
    "psu",
    "case",
    "cooler",
)
ALL_KINDS = (CPU, MOTHERBOARD, RAM, GPU, STORAGE, PSU, CASE, COOLER)
REQUIRED_KINDS = (CPU, MOTHERBOARD, RAM, STORAGE, PSU, CASE)

# How many units of each kind a single build may contain.
MAX_QUANTITY = {CPU: 1, MOTHERBOARD: 1, PSU: 1, CASE: 1, COOLER: 1, GPU: 2, RAM: 8, STORAGE: 8}

# Power estimation (watts). Values are deliberately conservative averages.
MOTHERBOARD_W = 50
RAM_MODULE_W = 5
STORAGE_W = 8
AIR_COOLER_W = 5
LIQUID_COOLER_W = 15
FANS_AND_PERIPHERALS_W = 25
# AMD defines the socket power limit (PPT) of AM4/AM5 desktop CPUs as 1.35 × TDP.
AMD_PPT_FACTOR = 1.35
PSU_HEADROOM = 1.3  # keep the PSU at ≤ ~75 % load for efficiency and transients
PSU_ROUND_TO = 50

GPU_TIGHT_FIT_MM = 10


@dataclass(frozen=True)
class Part:
    id: int
    kind: str
    name: str
    specs: dict[str, Any]
    quantity: int = 1


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str  # "error" | "warning"
    message: str  # English, for logs and API clients that don't localise
    component_ids: tuple[int, ...] = ()
    # Values the message is built from. The frontend renders its own localised
    # text from ``code`` + ``params``, so the engine stays language-agnostic.
    params: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "component_ids": list(self.component_ids),
            "params": self.params,
        }


@dataclass
class Report:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    estimated_wattage: int = 0
    recommended_psu_wattage: int = 0

    @property
    def is_compatible(self) -> bool:
        return not self.errors

    @property
    def is_complete(self) -> bool:
        return not self.missing

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_compatible": self.is_compatible,
            "is_complete": self.is_complete,
            "errors": [i.as_dict() for i in self.errors],
            "warnings": [i.as_dict() for i in self.warnings],
            "missing": self.missing,
            "estimated_wattage": self.estimated_wattage,
            "recommended_psu_wattage": self.recommended_psu_wattage,
        }


class BuildView:
    """Read helper over the parts of a build, grouped by kind."""

    def __init__(self, parts: Iterable[Part]):
        self.parts = list(parts)
        self._by_kind: dict[str, list[Part]] = {}
        for part in self.parts:
            self._by_kind.setdefault(part.kind, []).append(part)

    def all(self, kind: str) -> list[Part]:
        return self._by_kind.get(kind, [])

    def one(self, kind: str) -> Part | None:
        """The single part of a kind, or None if absent *or ambiguous*.

        Pairwise rules only run when the slot is unambiguous; ambiguity itself
        is reported by the cardinality rule, so we don't pile up duplicates.
        """
        items = self.all(kind)
        if len(items) == 1 and items[0].quantity == 1:
            return items[0]
        return None

    def count(self, kind: str) -> int:
        return sum(p.quantity for p in self.all(kind))


Rule = Callable[[BuildView], Iterator[Issue]]
RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    RULES.append(fn)
    return fn


def error(code: str, message: str, *parts: Part, **params: Any) -> Issue:
    return Issue(code, "error", message, tuple(p.id for p in parts), params)


def warning(code: str, message: str, *parts: Part, **params: Any) -> Issue:
    return Issue(code, "warning", message, tuple(p.id for p in parts), params)


# --- Cardinality ----------------------------------------------------------------


@rule
def quantity_limits(b: BuildView) -> Iterator[Issue]:
    for kind, limit in MAX_QUANTITY.items():
        count = b.count(kind)
        if count > limit:
            yield error(
                "TOO_MANY_PARTS",
                f"A build can contain at most {limit} × {kind}, got {count}.",
                *b.all(kind),
                kind=kind,
                limit=limit,
                count=count,
            )


# --- CPU ↔ motherboard -----------------------------------------------------------


@rule
def cpu_socket(b: BuildView) -> Iterator[Issue]:
    cpu, mb = b.one(CPU), b.one(MOTHERBOARD)
    if cpu and mb and cpu.specs["socket"] != mb.specs["socket"]:
        yield error(
            "CPU_SOCKET_MISMATCH",
            f"{cpu.name} uses socket {cpu.specs['socket']}, "
            f"but {mb.name} has socket {mb.specs['socket']}.",
            cpu,
            mb,
            cpu=cpu.name,
            cpu_socket=cpu.specs["socket"],
            board=mb.name,
            board_socket=mb.specs["socket"],
        )


@rule
def cpu_chipset(b: BuildView) -> Iterator[Issue]:
    cpu, mb = b.one(CPU), b.one(MOTHERBOARD)
    # Only meaningful when the socket matches; otherwise the socket error says it all.
    if not (cpu and mb) or cpu.specs["socket"] != mb.specs["socket"]:
        return
    if mb.specs["chipset"] not in cpu.specs["supported_chipsets"]:
        yield error(
            "CHIPSET_UNSUPPORTED",
            f"{cpu.name} is not supported by the {mb.specs['chipset']} chipset "
            f"(supported: {', '.join(cpu.specs['supported_chipsets'])}).",
            cpu,
            mb,
            cpu=cpu.name,
            chipset=mb.specs["chipset"],
            supported=", ".join(cpu.specs["supported_chipsets"]),
        )


# --- Memory ------------------------------------------------------------------------


@rule
def memory_type(b: BuildView) -> Iterator[Issue]:
    rams = b.all(RAM)
    types = {r.specs["memory_type"] for r in rams}
    if len(types) > 1:
        yield error("MIXED_MEMORY_TYPES", "DDR4 and DDR5 modules cannot be mixed.", *rams)
        return

    mb, cpu = b.one(MOTHERBOARD), b.one(CPU)
    for ram in rams:
        if mb and ram.specs["memory_type"] != mb.specs["memory_type"]:
            yield error(
                "MEMORY_TYPE_MISMATCH",
                f"{ram.name} is {ram.specs['memory_type']}, "
                f"but {mb.name} only supports {mb.specs['memory_type']}.",
                ram,
                mb,
                ram=ram.name,
                ram_type=ram.specs["memory_type"],
                board=mb.name,
                board_type=mb.specs["memory_type"],
            )
        if cpu and ram.specs["memory_type"] not in cpu.specs["memory_types"]:
            yield error(
                "CPU_MEMORY_UNSUPPORTED",
                f"{cpu.name} does not support {ram.specs['memory_type']} memory.",
                ram,
                cpu,
                cpu=cpu.name,
                ram_type=ram.specs["memory_type"],
            )


@rule
def memory_capacity(b: BuildView) -> Iterator[Issue]:
    mb, rams = b.one(MOTHERBOARD), b.all(RAM)
    if not (mb and rams):
        return
    sticks = sum(r.specs["modules"] * r.quantity for r in rams)
    total_gb = sum(r.specs["modules"] * r.specs["module_size_gb"] * r.quantity for r in rams)
    if sticks > mb.specs["memory_slots"]:
        yield error(
            "NOT_ENOUGH_MEMORY_SLOTS",
            f"{sticks} memory modules selected, but {mb.name} has "
            f"{mb.specs['memory_slots']} slots.",
            mb,
            *rams,
            modules=sticks,
            board=mb.name,
            slots=mb.specs["memory_slots"],
        )
    if total_gb > mb.specs["max_memory_gb"]:
        yield error(
            "MEMORY_OVER_MAX",
            f"{total_gb} GB of memory exceeds the {mb.specs['max_memory_gb']} GB "
            f"supported by {mb.name}.",
            mb,
            *rams,
            total_gb=total_gb,
            board=mb.name,
            max_gb=mb.specs["max_memory_gb"],
        )
    if len(rams) > 1 or any(r.quantity > 1 for r in rams):
        yield warning(
            "MIXED_MEMORY_KITS",
            "Mixing several memory kits may not run at rated speed; "
            "a single kit with the full capacity is more reliable.",
            *rams,
        )


# --- Case fitment --------------------------------------------------------------------


@rule
def board_form_factor(b: BuildView) -> Iterator[Issue]:
    mb, case = b.one(MOTHERBOARD), b.one(CASE)
    if mb and case and mb.specs["form_factor"] not in case.specs["supported_form_factors"]:
        yield error(
            "CASE_FORM_FACTOR",
            f"{mb.name} is {mb.specs['form_factor']}, but {case.name} supports "
            f"{', '.join(case.specs['supported_form_factors'])}.",
            mb,
            case,
            board=mb.name,
            form_factor=mb.specs["form_factor"],
            case=case.name,
            supported=", ".join(case.specs["supported_form_factors"]),
        )


@rule
def gpu_length(b: BuildView) -> Iterator[Issue]:
    case = b.one(CASE)
    if not case:
        return
    limit = case.specs["max_gpu_length_mm"]
    for gpu in b.all(GPU):
        length = gpu.specs.get("length_mm")
        if length is None:
            yield warning(
                "GPU_LENGTH_UNKNOWN",
                f"The length of {gpu.name} is unknown; check that it fits in {case.name} "
                f"(up to {limit} mm).",
                gpu,
                case,
                gpu=gpu.name,
                case=case.name,
                limit=limit,
            )
        elif length > limit:
            yield error(
                "GPU_TOO_LONG",
                f"{gpu.name} is {length} mm long, {case.name} fits up to {limit} mm.",
                gpu,
                case,
                gpu=gpu.name,
                length=length,
                case=case.name,
                limit=limit,
            )
        elif limit - length < GPU_TIGHT_FIT_MM:
            yield warning(
                "GPU_TIGHT_FIT",
                f"{gpu.name} fits in {case.name} with only {limit - length} mm to spare; "
                "front fans or cables may get in the way.",
                gpu,
                case,
                gpu=gpu.name,
                case=case.name,
                spare=limit - length,
            )


@rule
def psu_form_factor(b: BuildView) -> Iterator[Issue]:
    psu, case = b.one(PSU), b.one(CASE)
    if psu and case and psu.specs["form_factor"] not in case.specs["psu_form_factors"]:
        yield error(
            "PSU_FORM_FACTOR",
            f"{psu.name} is {psu.specs['form_factor']}, but {case.name} accepts "
            f"{', '.join(case.specs['psu_form_factors'])}.",
            psu,
            case,
            psu=psu.name,
            form_factor=psu.specs["form_factor"],
            case=case.name,
            supported=", ".join(case.specs["psu_form_factors"]),
        )


# --- Cooling ---------------------------------------------------------------------------


def cpu_load_power(cpu: Part) -> int:
    """Heat the cooler must remove under sustained all-core load, in watts.

    The TDP on the box is a base-clock figure: an i7-14700K is "125 W" but runs
    at up to 253 W. Intel publishes that limit (``max_power_w``); for AMD it is
    the PPT, 1.35 × TDP.
    """
    if cpu.specs.get("max_power_w"):
        return cpu.specs["max_power_w"]
    if str(cpu.specs.get("socket", "")).upper().startswith("AM"):
        return round(cpu.specs["tdp_w"] * AMD_PPT_FACTOR)
    return cpu.specs["tdp_w"]


def _round_up(watts: int, step: int = 10) -> int:
    return math.ceil(watts / step) * step


def _cooling_capacity(cooler: Part, cpu: Part) -> Iterator[Issue]:
    rating, tdp, load = cooler.specs.get("tdp_rating_w"), cpu.specs["tdp_w"], cpu_load_power(cpu)
    recommended = _round_up(load)
    if rating is None:
        yield warning(
            "COOLER_RATING_UNKNOWN",
            f"{cooler.name} does not state how much heat it can dissipate; {cpu.name} "
            f"produces up to {load} W under load.",
            cooler,
            cpu,
            cooler=cooler.name,
            cpu=cpu.name,
            load=load,
        )
    elif rating < tdp:
        yield warning(
            "COOLER_UNDERRATED",
            f"{cooler.name} is rated for {rating} W, {cpu.name} has a TDP of {tdp} W and "
            f"up to {load} W under load; it will throttle. Choose a cooler rated for "
            f"{recommended} W or more.",
            cooler,
            cpu,
            cooler=cooler.name,
            rating=rating,
            cpu=cpu.name,
            tdp=tdp,
            load=load,
            recommended=recommended,
        )
    elif rating < load:
        yield warning(
            "COOLER_LOW_HEADROOM",
            f"{cooler.name} ({rating} W) handles {cpu.name} at its {tdp} W TDP, but under "
            f"full load it draws up to {load} W; for sustained load choose {recommended} W "
            "or more.",
            cooler,
            cpu,
            cooler=cooler.name,
            rating=rating,
            cpu=cpu.name,
            tdp=tdp,
            load=load,
            recommended=recommended,
        )


@rule
def cooler_fitment(b: BuildView) -> Iterator[Issue]:
    cooler, cpu, case = b.one(COOLER), b.one(CPU), b.one(CASE)
    if not cooler:
        if cpu and cpu.specs.get("boxed_cooler") is False:
            yield warning(
                "COOLER_REQUIRED",
                f"{cpu.name} is sold without a cooler; add a CPU cooler rated for at least "
                f"{_round_up(cpu_load_power(cpu))} W.",
                cpu,
                cpu=cpu.name,
                recommended=_round_up(cpu_load_power(cpu)),
            )
        elif cpu and not cpu.specs.get("boxed_cooler"):
            yield warning(
                "NO_COOLER",
                f"No CPU cooler selected; make sure {cpu.name} ships with a boxed cooler.",
                cpu,
                cpu=cpu.name,
            )
        return

    if cpu and cpu.specs["socket"] not in cooler.specs["sockets"]:
        yield error(
            "COOLER_SOCKET",
            f"{cooler.name} does not support socket {cpu.specs['socket']}.",
            cooler,
            cpu,
            cooler=cooler.name,
            socket=cpu.specs["socket"],
        )
    if cpu:
        yield from _cooling_capacity(cooler, cpu)
    if not case:
        return
    if cooler.specs["type"] == "air":
        height, limit = cooler.specs.get("height_mm"), case.specs["max_cooler_height_mm"]
        if height is None:
            yield warning(
                "COOLER_HEIGHT_UNKNOWN",
                f"The height of {cooler.name} is unknown; check that it fits in {case.name} "
                f"(up to {limit} mm).",
                cooler,
                case,
                cooler=cooler.name,
                case=case.name,
                limit=limit,
            )
        elif height > limit:
            yield error(
                "COOLER_TOO_TALL",
                f"{cooler.name} is {height} mm tall, {case.name} fits coolers up to {limit} mm.",
                cooler,
                case,
                cooler=cooler.name,
                height=height,
                case=case.name,
                limit=limit,
            )
    else:
        radiator = cooler.specs.get("radiator_mm")
        limit = case.specs.get("max_radiator_mm")
        if radiator is None:
            return
        if limit is None:
            yield warning(
                "RADIATOR_UNKNOWN",
                f"{case.name} does not list radiator support; check that a "
                f"{radiator} mm radiator fits.",
                cooler,
                case,
                case=case.name,
                radiator=radiator,
            )
        elif radiator > limit:
            yield error(
                "RADIATOR_TOO_LARGE",
                f"{cooler.name} needs a {radiator} mm radiator mount, "
                f"{case.name} supports up to {limit} mm.",
                cooler,
                case,
                cooler=cooler.name,
                radiator=radiator,
                case=case.name,
                limit=limit,
            )


# --- Storage -----------------------------------------------------------------------------


@rule
def storage_slots(b: BuildView) -> Iterator[Issue]:
    mb, drives = b.one(MOTHERBOARD), b.all(STORAGE)
    if not (mb and drives):
        return
    m2 = [d for d in drives if d.specs["interface"].startswith("M.2")]
    sata = [d for d in drives if d.specs["interface"] == "SATA"]
    m2_count = sum(d.quantity for d in m2)
    sata_count = sum(d.quantity for d in sata)
    if m2_count > mb.specs["m2_slots"]:
        yield error(
            "NOT_ENOUGH_M2_SLOTS",
            f"{m2_count} M.2 drives selected, {mb.name} has {mb.specs['m2_slots']} M.2 slots.",
            mb,
            *m2,
            count=m2_count,
            board=mb.name,
            slots=mb.specs["m2_slots"],
        )
    if sata_count > mb.specs["sata_ports"]:
        yield error(
            "NOT_ENOUGH_SATA_PORTS",
            f"{sata_count} SATA drives selected, {mb.name} has {mb.specs['sata_ports']} ports.",
            mb,
            *sata,
            count=sata_count,
            board=mb.name,
            ports=mb.specs["sata_ports"],
        )


# --- Video output ----------------------------------------------------------------------------


@rule
def video_output(b: BuildView) -> Iterator[Issue]:
    cpu = b.one(CPU)
    if cpu and not b.all(GPU) and not cpu.specs["integrated_graphics"]:
        yield error(
            "NO_VIDEO_OUTPUT",
            f"{cpu.name} has no integrated graphics; add a graphics card.",
            cpu,
            cpu=cpu.name,
        )


# --- Power -------------------------------------------------------------------------------------


def estimate_wattage(b: BuildView) -> int:
    total = 0
    if cpu := b.one(CPU):
        total += cpu.specs["tdp_w"]
    total += sum(g.specs["tdp_w"] * g.quantity for g in b.all(GPU))
    if b.all(MOTHERBOARD):
        total += MOTHERBOARD_W
    total += sum(r.specs["modules"] * r.quantity for r in b.all(RAM)) * RAM_MODULE_W
    total += b.count(STORAGE) * STORAGE_W
    if cooler := b.one(COOLER):
        total += LIQUID_COOLER_W if cooler.specs["type"] == "liquid" else AIR_COOLER_W
    if total:
        total += FANS_AND_PERIPHERALS_W
    return total


def recommended_psu(estimated: int) -> int:
    if not estimated:
        return 0
    return math.ceil(estimated * PSU_HEADROOM / PSU_ROUND_TO) * PSU_ROUND_TO


@rule
def psu_capacity(b: BuildView) -> Iterator[Issue]:
    psu = b.one(PSU)
    if not psu:
        return
    wattage = psu.specs["wattage"]
    estimated = estimate_wattage(b)
    recommended = recommended_psu(estimated)
    if wattage < estimated:
        yield error(
            "PSU_INSUFFICIENT",
            f"{psu.name} provides {wattage} W, the build draws about {estimated} W.",
            psu,
            psu=psu.name,
            wattage=wattage,
            estimated=estimated,
        )
    elif wattage < recommended:
        yield warning(
            "PSU_LOW_HEADROOM",
            f"{psu.name} ({wattage} W) leaves little headroom for a ~{estimated} W load; "
            f"{recommended} W is recommended.",
            psu,
            psu=psu.name,
            wattage=wattage,
            estimated=estimated,
            recommended=recommended,
        )
    for gpu in b.all(GPU):
        vendor_min = gpu.specs.get("recommended_psu_w")
        if vendor_min and wattage < vendor_min:
            yield warning(
                "PSU_BELOW_GPU_RECOMMENDATION",
                f"The vendor of {gpu.name} recommends at least a {vendor_min} W PSU.",
                psu,
                gpu,
                gpu=gpu.name,
                recommended=vendor_min,
            )


# --- Entry point ---------------------------------------------------------------------------------


def check(parts: Iterable[Part]) -> Report:
    view = BuildView(parts)
    report = Report()
    for rule_fn in RULES:
        for issue in rule_fn(view):
            (report.errors if issue.severity == "error" else report.warnings).append(issue)
    report.missing = [kind for kind in REQUIRED_KINDS if not view.all(kind)]
    report.estimated_wattage = estimate_wattage(view)
    report.recommended_psu_wattage = recommended_psu(report.estimated_wattage)
    return report
