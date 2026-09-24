"""Specifications and shop offers from a hotline.ua product page.

The page state (``window.__NUXT__``, read by :mod:`nuxt_state` without running
it) holds the product's full spec sheet as ``(title, value)`` rows — the same
table a visitor sees — and every shop offer with its price. This module turns
those rows into our ``Component.specs`` keys, per category.

Rules:
* Only values that parse cleanly are returned; a row that is missing or
  unfamiliar leaves the key out, so the part stays catalog-only rather than
  getting a guessed spec. The importer additionally runs ``validate_specs``.
* Two things are *derived* rather than read, both documented where they happen:
  the chipsets a CPU works with (from its socket) and the PSU format of a case
  that takes ATX boards (ATX).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any

from .nuxt_state import NuxtStateError, extract_nuxt_state

logger = logging.getLogger(__name__)


@dataclass
class PageState:
    specs: list[tuple[str, str]] = field(default_factory=list)
    offer_prices: list[Decimal] = field(default_factory=list)

    @property
    def median_price(self) -> Decimal | None:
        if not self.offer_prices:
            return None
        return Decimal(median(self.offer_prices)).quantize(Decimal("0.01"))


_NEW = {"новый", "новий", "new"}


def read_page_state(html: str) -> PageState | None:
    """Spec rows and prices of new-condition offers, or None if unavailable."""
    if "window.__NUXT__" not in html:
        return None
    try:
        product = extract_nuxt_state(html)["state"]["product"]
    except (NuxtStateError, KeyError, TypeError) as exc:
        logger.info("No usable page state: %s", exc)
        return None

    state = PageState()
    for edge in _edges(product.get("productValues")):
        title, value = edge.get("title"), edge.get("value")
        if edge.get("isHeader") or not isinstance(title, str) or not isinstance(value, str):
            continue
        state.specs.append((title, value))

    offers = [edge for edge in _edges(product.get("offers")) if _price(edge.get("price"))]
    new = [o for o in offers if str(o.get("condition", "")).strip().lower() in _NEW]
    # Used and refurbished offers would drag the typical price down.
    state.offer_prices = sorted(_price(o["price"]) for o in (new or offers))
    return state


def _edges(connection: Any) -> list[dict]:
    if not isinstance(connection, dict):
        return []
    return [
        e["node"] for e in connection.get("edges") or [] if isinstance(e, dict) and e.get("node")
    ]


def _price(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        price = Decimal(str(value))
    except InvalidOperation:
        return None
    return price if price > 0 else None


# --- Row lookup helpers -------------------------------------------------------------


def _norm(text: str) -> str:
    text = re.sub(r"[’ʼ`´]", "'", text)
    return re.sub(r"\s+", " ", text).strip().lower()


class Rows:
    def __init__(self, rows: list[tuple[str, str]]):
        self.rows = [(_norm(t), v.strip()) for t, v in rows]

    def get(self, *titles: str) -> str | None:
        wanted = {_norm(t) for t in titles}
        return next((v for t, v in self.rows if t in wanted and v), None)

    def starting(self, prefix: str) -> list[tuple[str, str]]:
        prefix = _norm(prefix)
        return [(t, v) for t, v in self.rows if t.startswith(prefix)]

    def int(self, *titles: str) -> int | None:
        return _first_int(self.get(*titles))

    def float(self, *titles: str) -> float | None:
        value = self.get(*titles)
        match = re.search(r"\d+(?:[.,]\d+)?", value or "")
        return float(match.group().replace(",", ".")) if match else None


def _first_int(value: str | None) -> int | None:
    # "1 840" is one number; "до 410 мм" is 410.
    match = re.search(r"\d[\d\s]*", value or "")
    return int(re.sub(r"\s", "", match.group())) if match else None


def _ints(value: str | None) -> list[int]:
    return [int(n) for n in re.findall(r"\d+", value or "")]


def _yes(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().lower() not in ("немає", "ні", "no", "-", "нет")


# --- Shared vocabularies ----------------------------------------------------------


def socket_name(value: str | None) -> str | None:
    """'Socket AM5' -> 'AM5', 'Socket 1700' -> 'LGA1700'."""
    if not value:
        return None
    if match := re.search(r"\bAM(\d)\b", value, re.I):
        return f"AM{match.group(1)}"
    if match := re.search(r"\b(1[0-9]{3})\b", value):
        return f"LGA{match.group(1)}"
    return None


# Which chipsets a socket's CPUs work with. Derived per platform: the source
# lists the socket, not the chipsets. (Older boards may need a BIOS update for
# a newer CPU generation; the curated catalog models that per CPU.)
CHIPSETS_BY_SOCKET = {
    "AM4": ["A520", "B450", "X470", "B550", "X570"],
    "AM5": ["A620", "B650", "B650E", "X670", "X670E", "B840", "B850", "X870", "X870E"],
    "LGA1700": ["H610", "B660", "H670", "Z690", "B760", "H770", "Z790"],
    "LGA1851": ["H810", "B860", "Z890"],
}

_BOARD_FORMATS = [
    (re.compile(r"e-?atx", re.I), "E-ATX"),
    (re.compile(r"micro-?atx|\bm-?atx\b", re.I), "Micro-ATX"),
    (re.compile(r"mini-?itx", re.I), "Mini-ITX"),
    (re.compile(r"\batx\b", re.I), "ATX"),
]


def board_formats(value: str | None) -> list[str]:
    found: list[str] = []
    for part in re.split(r"[/,;]", value or ""):
        for pattern, name in _BOARD_FORMATS:
            if pattern.search(part):
                if name not in found:
                    found.append(name)
                break
    return found


# --- Per category ------------------------------------------------------------------------


def cpu(rows: Rows) -> dict:
    specs: dict = {}
    if socket := socket_name(rows.get("Тип роз'єму")):
        specs["socket"] = socket
        if socket in CHIPSETS_BY_SOCKET:
            specs["supported_chipsets"] = CHIPSETS_BY_SOCKET[socket]
    _put(specs, "cores", rows.int("Загальна кількість ядер"))
    _put(specs, "threads", rows.int("Кількість потоків"))
    _put(specs, "base_clock_ghz", rows.float("Базова частота продуктивних ядер, ГГц"))
    _put(specs, "boost_clock_ghz", rows.float("Максимальна частота продуктивних ядер, ГГц"))
    _put(specs, "tdp_w", rows.int("Базове тепловиділення TDP, Вт"))
    # Intel's PL2 / turbo power: what a cooler really has to handle under load.
    _put(specs, "max_power_w", rows.int("Максимальне тепловиділення TDP, Вт"))
    memory = sorted(set(re.findall(r"DDR[45]", rows.get("Тип пам'яті") or "", re.I)))
    if memory:
        specs["memory_types"] = [m.upper() for m in memory]
    _put(specs, "integrated_graphics", _yes(rows.get("Інтегрована графіка")))
    _put(specs, "boxed_cooler", _yes(rows.get("Кулер в комплекті")))
    return specs


def motherboard(rows: Rows) -> dict:
    specs: dict = {}
    _put(specs, "socket", socket_name(rows.get("Тип роз'єму CPU")))
    if chipset := rows.get("Чіпсет", "Чипсет"):
        specs["chipset"] = re.sub(r"^(AMD|Intel)\s+", "", chipset, flags=re.I).strip()
    formats = board_formats((rows.get("Форм-фактор") or "").split(",")[0])
    if formats:
        specs["form_factor"] = formats[0]
    dimm = rows.get("DIMM") or ""
    if match := re.search(r"(\d+)\s*[xх×]\s*(DDR[45])", dimm, re.I):
        specs["memory_slots"] = int(match.group(1))
        specs["memory_type"] = match.group(2).upper()
    if match := re.search(r"до\s*(\d+)\s*[ГG][БB]", dimm, re.I):
        specs["max_memory_gb"] = int(match.group(1))
    _put(specs, "m2_slots", rows.int("Кількість M.2"))
    sata = rows.get("SATA Revision 3.0", "SATA 3.0", "SATA")
    if sata is not None:
        specs["sata_ports"] = 0 if _yes(sata) is False else (_first_int(sata) or 0)
    return specs


_PSU_FORMATS = [
    ("SFX-L", re.compile(r"SFX-?L", re.I)),
    ("SFX", re.compile(r"SFX", re.I)),
    ("ATX", re.compile(r"ATX", re.I)),
]


def psu(rows: Rows) -> dict:
    specs: dict = {}
    _put(specs, "wattage", rows.int("Потужність сумарна, Вт", "Потужність, Вт"))
    form = rows.get("Форм-фактор БЖ", "Форм-фактор")
    for name, pattern in _PSU_FORMATS:
        if form and pattern.search(form):
            specs["form_factor"] = name
            break
    cert = rows.get("Сертифікат 80 PLUS")
    if cert and _yes(cert):
        level = re.sub(r"(?i)^80\s*plus\s*", "", cert).strip()
        specs["efficiency"] = f"80+ {level}".strip() if level else "80+"
    return specs


def case(rows: Rows) -> dict:
    specs: dict = {}
    formats = board_formats(rows.get("Форм-фактор материнської плати"))
    if formats:
        specs["supported_form_factors"] = formats
    _put(specs, "max_gpu_length_mm", rows.int("Максимальна довжина відеокарти, мм"))
    # "76/153/155" = depends on the fan layout; the tallest option is the limit.
    heights = _ints(rows.get("Максимальна висота процесорного кулера, мм"))
    if heights:
        specs["max_cooler_height_mm"] = max(heights)
    psu_form = rows.get("Форм-фактор БЖ")
    if psu_form:
        found = [name for name, pattern in _PSU_FORMATS if pattern.search(psu_form)]
        if found:
            specs["psu_form_factors"] = found[-1:] if found[-1] == "ATX" else found[:1]
    elif set(formats) & {"E-ATX", "ATX"}:
        # Not listed on the source; a case for full ATX boards takes an ATX PSU.
        specs["psu_form_factors"] = ["ATX"]
    return specs


def cooler(rows: Rows) -> dict:
    purpose = rows.get("Призначення")
    if purpose and "процесор" not in purpose.lower():
        return {}  # case fan, VRM/SSD heatsink ...
    specs: dict = {}
    kind = (rows.get("Тип") or "").lower()
    if "повітр" in kind:
        specs["type"] = "air"
    elif "вод" in kind or "рідин" in kind:
        specs["type"] = "liquid"
    sockets: list[str] = []
    for title, value in rows.starting("Socket"):
        if _yes(value) is False:
            continue
        for token in re.findall(r"AM\d|\d{3,4}x?", title, re.I):
            name = token.upper() if token.upper().startswith("AM") else f"LGA{token.upper()}"
            if name not in sockets:
                sockets.append(name)
    if sockets:
        specs["sockets"] = sockets
    dims = _ints(rows.get("Розміри кулера, мм"))
    if specs.get("type") == "air" and len(dims) >= 3:
        specs["height_mm"] = dims[2]
    if specs.get("type") == "liquid":
        fans, fan_size = rows.int("Кількість вентиляторів"), rows.int("Розміри вентилятора, мм")
        if fans and fan_size in (120, 140):
            specs["radiator_mm"] = fans * fan_size
    _put(specs, "tdp_rating_w", rows.int("Розсіювана потужність, Вт"))
    return specs


def gpu(rows: Rows, chip_names: list[str] | None = None) -> dict:
    specs: dict = {}
    if chip := rows.get("GPU"):
        wanted = _norm(chip).replace("geforce ", "").replace("radeon ", "")
        known = next(
            (
                name
                for name in chip_names or []
                if _norm(name).replace("geforce ", "").replace("radeon ", "") == wanted
            ),
            None,
        )
        specs["chipset"] = known or chip.strip()
    _put(specs, "vram_gb", rows.int("Об'єм пам'яті, ГБ"))
    dims = _ints(rows.get("Розміри, мм"))
    if dims and dims[0] >= 100:
        specs["length_mm"] = dims[0]
    _put(specs, "recommended_psu_w", rows.int("Рекомендована потужність блоку живлення, Вт"))
    return specs


def storage(rows: Rows) -> dict:
    specs: dict = {}
    _put(specs, "capacity_gb", rows.int("Об'єм, ГБ"))
    interface = (rows.get("Інтерфейс") or "").lower()
    form = (rows.get("Форм-фактор") or "").lower()
    m2 = "m.2" in interface or "m.2" in form
    if "usb" in interface or "thunderbolt" in interface:
        return {}  # external drive
    if "pci" in interface or "nvme" in interface:
        specs["interface"] = "M.2 NVMe"
    elif "sata" in interface:
        specs["interface"] = "M.2 SATA" if m2 else "SATA"
    return specs


def ram(rows: Rows) -> dict:
    form = rows.get("Формфактор пам'яті", "Форм-фактор пам'яті") or ""
    if re.search(r"SO-?DIMM", form, re.I):
        return {}
    specs: dict = {}
    total, count = rows.int("Обсяг, ГБ"), rows.int("Кількість планок в комплекті")
    if total and count:
        specs["modules"] = count
        specs["module_size_gb"] = total // count
    if match := re.search(r"DDR[45]", rows.get("Тип") or "", re.I):
        specs["memory_type"] = match.group().upper()
    _put(specs, "speed_mhz", rows.int("Ефективна частота, МТ/с", "Ефективна частота, МГц"))
    return specs


MAPPERS = {
    "cpu": cpu,
    "motherboard": motherboard,
    "psu": psu,
    "case": case,
    "cooler": cooler,
    "storage": storage,
    "ram": ram,
}


def specs_from_rows(
    kind: str, rows: list[tuple[str, str]], *, gpu_chips: list[str] | None = None
) -> dict:
    table = Rows(rows)
    if kind == "gpu":
        return gpu(table, gpu_chips)
    mapper = MAPPERS.get(kind)
    return mapper(table) if mapper else {}


def _put(specs: dict, key: str, value: Any) -> None:
    if value is not None:
        specs[key] = value
