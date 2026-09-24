"""Unit tests for the compatibility rules. No database: plain Part objects."""

import itertools

import pytest

from apps.builds import compatibility as c
from apps.catalog.models_enums import CategoryKind

_ids = itertools.count(1)


def part(kind, quantity=1, **specs):
    defaults = {
        "cpu": {
            "socket": "AM5", "tdp_w": 65, "integrated_graphics": True,
            "supported_chipsets": ["B650", "X670E"], "memory_types": ["DDR5"],
        },
        "motherboard": {
            "socket": "AM5", "chipset": "B650", "form_factor": "ATX", "memory_type": "DDR5",
            "memory_slots": 4, "max_memory_gb": 192, "m2_slots": 2, "sata_ports": 4,
        },
        "ram": {"memory_type": "DDR5", "modules": 2, "module_size_gb": 16},
        "gpu": {"length_mm": 300, "tdp_w": 200},
        "storage": {"interface": "M.2 NVMe"},
        "psu": {"wattage": 750, "form_factor": "ATX"},
        "case": {
            "supported_form_factors": ["ATX", "Micro-ATX", "Mini-ITX"], "max_gpu_length_mm": 360,
            "max_cooler_height_mm": 165, "psu_form_factors": ["ATX"], "max_radiator_mm": 360,
        },
        "cooler": {
            "type": "air", "sockets": ["AM4", "AM5", "LGA1700"], "height_mm": 155,
            "tdp_rating_w": 200,
        },
    }[kind]  # fmt: skip
    return c.Part(
        id=next(_ids),
        kind=kind,
        name=f"{kind}-{specs}",
        specs={**defaults, **specs},
        quantity=quantity,
    )


def full_build(**overrides):
    """A complete, valid build; override any slot with a Part or None to drop it."""
    parts = {kind: part(kind) for kind in c.ALL_KINDS}
    parts.update(overrides)
    return [p for p in parts.values() if p is not None]


def codes(report):
    return {i.code for i in report.errors}, {i.code for i in report.warnings}


def test_engine_kinds_match_category_kinds():
    # The engine duplicates the kinds as strings to stay Django-free.
    assert set(c.ALL_KINDS) == set(CategoryKind.values)


def test_valid_build_has_no_issues():
    report = c.check(full_build())
    assert report.is_compatible and report.is_complete
    assert report.errors == [] and report.warnings == []


def test_empty_build_is_incomplete_but_not_incompatible():
    report = c.check([])
    assert report.is_compatible
    assert set(report.missing) == set(c.REQUIRED_KINDS)
    assert report.estimated_wattage == 0


def test_socket_mismatch():
    errors, _ = codes(c.check(full_build(cpu=part("cpu", socket="LGA1700"))))
    assert "CPU_SOCKET_MISMATCH" in errors
    # Chipset is not reported on top of a socket mismatch.
    assert "CHIPSET_UNSUPPORTED" not in errors


def test_chipset_not_supported_by_cpu():
    board = part("motherboard", chipset="A620")
    errors, _ = codes(c.check(full_build(motherboard=board)))
    assert errors == {"CHIPSET_UNSUPPORTED"}


@pytest.mark.parametrize(
    ("ram_type", "board_type", "cpu_types", "expected"),
    [
        ("DDR4", "DDR5", ["DDR5"], {"MEMORY_TYPE_MISMATCH", "CPU_MEMORY_UNSUPPORTED"}),
        ("DDR4", "DDR4", ["DDR5"], {"CPU_MEMORY_UNSUPPORTED"}),
        ("DDR4", "DDR4", ["DDR4", "DDR5"], set()),
    ],
)
def test_memory_type(ram_type, board_type, cpu_types, expected):
    build = full_build(
        ram=part("ram", memory_type=ram_type),
        motherboard=part("motherboard", memory_type=board_type),
        cpu=part("cpu", memory_types=cpu_types),
    )
    errors, _ = codes(c.check(build))
    assert errors == expected


def test_mixed_ddr4_and_ddr5():
    build = [*full_build(ram=None), part("ram"), part("ram", memory_type="DDR4")]
    errors, _ = codes(c.check(build))
    assert "MIXED_MEMORY_TYPES" in errors


def test_memory_slots_and_capacity():
    board = part("motherboard", memory_slots=2, max_memory_gb=64)
    build = full_build(motherboard=board, ram=part("ram", quantity=2, module_size_gb=32))
    errors, warnings = codes(c.check(build))
    assert {"NOT_ENOUGH_MEMORY_SLOTS", "MEMORY_OVER_MAX"} <= errors
    assert "MIXED_MEMORY_KITS" in warnings


def test_board_form_factor_must_fit_case():
    case = part("case", supported_form_factors=["Mini-ITX"])
    errors, _ = codes(c.check(full_build(case=case)))
    assert "CASE_FORM_FACTOR" in errors


@pytest.mark.parametrize(
    ("gpu_len", "case_max", "error", "warning"),
    [(361, 360, True, False), (360, 360, False, True), (350, 360, False, False)],
)
def test_gpu_length(gpu_len, case_max, error, warning):
    build = full_build(
        gpu=part("gpu", length_mm=gpu_len), case=part("case", max_gpu_length_mm=case_max)
    )
    errors, warnings = codes(c.check(build))
    assert ("GPU_TOO_LONG" in errors) is error
    assert ("GPU_TIGHT_FIT" in warnings) is warning


def test_cooler_height_socket_and_rating():
    cooler = part("cooler", height_mm=170, sockets=["LGA1700"], tdp_rating_w=50)
    errors, warnings = codes(c.check(full_build(cooler=cooler)))
    assert {"COOLER_TOO_TALL", "COOLER_SOCKET"} <= errors
    assert "COOLER_UNDERRATED" in warnings


def test_liquid_cooler_radiator():
    cooler = part("cooler", type="liquid", radiator_mm=360, height_mm=None)
    case = part("case", max_radiator_mm=280)
    errors, _ = codes(c.check(full_build(cooler=cooler, case=case)))
    assert "RADIATOR_TOO_LARGE" in errors


def test_missing_cooler_is_a_warning():
    report = c.check(full_build(cooler=None))
    assert report.is_compatible and report.is_complete
    assert "NO_COOLER" in codes(report)[1]


def test_psu_form_factor():
    build = full_build(case=part("case", psu_form_factors=["SFX"]))
    assert "PSU_FORM_FACTOR" in codes(c.check(build))[0]


def test_power_estimate_and_recommendation():
    report = c.check(full_build())
    # 65 CPU + 200 GPU + 50 board + 2*5 RAM + 8 SSD + 5 air cooler + 25 misc
    assert report.estimated_wattage == 363
    # 363 * 1.3 = 471.9 → rounded up to the next 50 W
    assert report.recommended_psu_wattage == 500


@pytest.mark.parametrize(
    ("wattage", "error", "warning"),
    [(350, "PSU_INSUFFICIENT", None), (450, None, "PSU_LOW_HEADROOM"), (500, None, None)],
)
def test_psu_capacity(wattage, error, warning):
    errors, warnings = codes(c.check(full_build(psu=part("psu", wattage=wattage))))
    assert (error in errors) if error else not errors
    assert (warning in warnings) if warning else "PSU_LOW_HEADROOM" not in warnings


def test_two_gpus_double_the_gpu_power():
    single = c.check(full_build()).estimated_wattage
    double = c.check(full_build(gpu=part("gpu", quantity=2))).estimated_wattage
    assert double - single == 200


def test_gpu_vendor_psu_recommendation():
    gpu = part("gpu", recommended_psu_w=850)
    assert "PSU_BELOW_GPU_RECOMMENDATION" in codes(c.check(full_build(gpu=gpu)))[1]


def test_storage_slots():
    board = part("motherboard", m2_slots=1, sata_ports=1)
    drives = [part("storage"), part("storage"), part("storage", interface="SATA", quantity=2)]
    errors, _ = codes(c.check(full_build(motherboard=board, storage=None) + drives))
    assert {"NOT_ENOUGH_M2_SLOTS", "NOT_ENOUGH_SATA_PORTS"} <= errors


def test_no_video_output_without_gpu_and_igpu():
    cpu = part("cpu", integrated_graphics=False)
    assert "NO_VIDEO_OUTPUT" in codes(c.check(full_build(cpu=cpu, gpu=None)))[0]
    # Same CPU with a GPU is fine.
    assert "NO_VIDEO_OUTPUT" not in codes(c.check(full_build(cpu=cpu)))[0]


def test_too_many_cpus_disables_pairwise_cpu_rules():
    two_cpus = [*full_build(cpu=None), part("cpu"), part("cpu", socket="LGA1700")]
    errors, _ = codes(c.check(two_cpus))
    # One cardinality error, not a cascade of socket errors for each CPU.
    assert errors == {"TOO_MANY_PARTS"}


def test_issue_references_involved_components():
    cpu = part("cpu", socket="LGA1700")
    board = part("motherboard")
    report = c.check([cpu, board])
    issue = next(i for i in report.errors if i.code == "CPU_SOCKET_MISMATCH")
    assert set(issue.component_ids) == {cpu.id, board.id}
