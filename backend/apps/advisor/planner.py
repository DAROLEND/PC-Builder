"""Deterministic, rule-based build planner.

Used when no Anthropic API key is configured, when the LLM fails, and as a
baseline in tests. It works the way a person would:

1. Split the budget between slots according to the use case.
2. *Performance* slots (CPU, GPU, RAM) take the most expensive compatible
   part within their share plus whatever earlier slots did not spend.
   Price is the proxy for performance inside a category.
3. *Sufficiency* slots (motherboard, cooler, case, PSU) take the cheapest part
   that raises no errors and none of the "you'll regret this" warnings. Paying
   more for them doesn't make a game run faster.
4. Storage gets its own share only, so savings don't end up in a bigger SSD.
5. Every pick leaves enough money for the cheapest part of each slot that is
   still empty, so an early expensive CPU cannot starve the PSU.
6. Upgrade pass: spend what is left on the use case's priority slots, re-picking
   the PSU so it still matches the new power draw. If the build is still over
   budget (cheapest parts are not always mutually compatible), a downgrade pass
   steps the most expensive performance parts down until it fits.
7. A local downgrade cannot switch platforms (an AM5 CPU drags in DDR5 and an
   AM5 board). If the plan still does not fit, re-plan from scratch with smaller
   slot shares while keeping the real budget as the ceiling.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Min

from apps.builds import compatibility as c
from apps.catalog.compat_query import compatible_q
from apps.catalog.models import Component

from .tools import to_part

USE_CASES = ("gaming", "workstation", "streaming", "office")

# Share of the budget per slot. Rows sum to 1.0.
BUDGET_SPLIT: dict[str, dict[str, float]] = {
    "gaming": {
        "cpu": 0.18, "motherboard": 0.10, "ram": 0.08, "gpu": 0.40,
        "cooler": 0.03, "storage": 0.08, "case": 0.06, "psu": 0.07,
    },
    "streaming": {
        "cpu": 0.24, "motherboard": 0.11, "ram": 0.09, "gpu": 0.30,
        "cooler": 0.04, "storage": 0.09, "case": 0.06, "psu": 0.07,
    },
    "workstation": {
        "cpu": 0.30, "motherboard": 0.12, "ram": 0.14, "gpu": 0.20,
        "cooler": 0.05, "storage": 0.10, "case": 0.04, "psu": 0.05,
    },
    "office": {
        "cpu": 0.30, "motherboard": 0.18, "ram": 0.14, "gpu": 0.0,
        "cooler": 0.04, "storage": 0.16, "case": 0.10, "psu": 0.08,
    },
}  # fmt: skip

UPGRADE_PRIORITY = {
    "gaming": ["gpu", "cpu", "ram"],
    "streaming": ["cpu", "gpu", "ram"],
    "workstation": ["cpu", "ram", "gpu", "storage"],
    "office": ["storage", "ram"],
}

# GPU goes before cooler and case (it constrains the case), PSU is last
# because its size depends on everything else.
PICK_ORDER = ["cpu", "motherboard", "ram", "gpu", "cooler", "storage", "case", "psu"]
PERFORMANCE_KINDS = {"cpu", "gpu", "ram"}
SUFFICIENCY_KINDS = {"motherboard", "cooler", "case", "psu"}
BLOCKING_WARNINGS = {"COOLER_UNDERRATED", "PSU_LOW_HEADROOM", "PSU_BELOW_GPU_RECOMMENDATION"}


@dataclass
class Plan:
    components: list[Component] = field(default_factory=list)
    # (code, params) pairs; the service renders them in the user's language.
    notes: list[tuple[str, dict]] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum((comp.price for comp in self.components), Decimal("0"))

    @property
    def ids(self) -> list[int]:
        return [comp.id for comp in self.components]


def _acceptable(parts: list[c.Part]) -> bool:
    report = c.check(parts)
    return not report.errors and not any(w.code in BLOCKING_WARNINGS for w in report.warnings)


def _candidates(kind: str, chosen: list[Component]) -> list[Component]:
    parts = [to_part(x) for x in chosen]
    return list(
        Component.objects.buildable()
        .with_related()
        .filter(category__kind=kind)
        .filter(compatible_q(kind, parts))
    )


def _cheapest_acceptable(kind: str, chosen: list[Component]) -> Component | None:
    parts = [to_part(x) for x in chosen]
    for candidate in sorted(_candidates(kind, chosen), key=lambda x: x.price):
        if _acceptable([*parts, to_part(candidate)]):
            return candidate
    return None


def _best_within(kind: str, chosen: list[Component], allocation: Decimal) -> Component | None:
    parts = [to_part(x) for x in chosen]
    for candidate in sorted(_candidates(kind, chosen), key=lambda x: x.price, reverse=True):
        if candidate.price <= allocation and _acceptable([*parts, to_part(candidate)]):
            return candidate
    return None


def _min_prices() -> dict[str, Decimal]:
    rows = Component.objects.buildable().values("category__kind").annotate(p=Min("price"))
    return {row["category__kind"]: row["p"] for row in rows}


RETRY_FACTORS = ("1.00", "0.92", "0.85", "0.78", "0.70")


def plan_build(budget: Decimal, use_case: str) -> Plan:
    best: Plan | None = None
    for factor in RETRY_FACTORS:
        plan = _plan(budget * Decimal(factor), use_case, ceiling=budget)
        if plan.total <= budget:
            if factor != RETRY_FACTORS[0]:
                plan.notes.append(("REPLANNED", {}))
            return plan
        if best is None or plan.total < best.total:
            best = plan
    assert best is not None
    best.notes.append(("OVER_BUDGET", {"total": str(best.total), "budget": str(budget)}))
    return best


def _plan(target: Decimal, use_case: str, *, ceiling: Decimal) -> Plan:
    """One planning pass. Shares come from ``target``, hard limits from ``ceiling``."""
    budget = target
    split = BUDGET_SPLIT[use_case]
    plan = Plan()
    carry = Decimal("0")
    floor = _min_prices()
    needed = [k for k in PICK_ORDER if split[k] > 0 or k != "gpu"]

    for index, kind in enumerate(PICK_ORDER):
        if kind == "gpu" and split["gpu"] == 0:
            cpu = next((x for x in plan.components if x.kind == "cpu"), None)
            if cpu and cpu.specs["integrated_graphics"]:
                plan.notes.append(("NO_GPU_NEEDED", {}))
                continue

        share = budget * Decimal(str(split[kind]))
        if kind in SUFFICIENCY_KINDS:
            pick = _cheapest_acceptable(kind, plan.components)
        else:
            allocation = share + carry if kind in PERFORMANCE_KINDS else share
            later = [k for k in PICK_ORDER[index + 1 :] if k in needed]
            reserve = sum((floor.get(k, Decimal("0")) for k in later), Decimal("0"))
            allocation = min(allocation, budget - plan.total - reserve)
            pick = _best_within(kind, plan.components, allocation)
            if pick is None:
                pick = _cheapest_acceptable(kind, plan.components)
                if pick is not None:
                    plan.notes.append(("SHARE_EXCEEDED", {"kind": kind}))

        if pick is None:
            plan.notes.append(("NO_PART", {"kind": kind}))
            continue

        plan.components.append(pick)
        if kind in PERFORMANCE_KINDS:
            carry = share + carry - pick.price
        else:
            carry += share - pick.price

    for kind in UPGRADE_PRIORITY[use_case]:
        _try_upgrade(plan, kind, ceiling)
    while plan.total > ceiling and _try_downgrade(plan):
        pass
    return plan


def _try_upgrade(plan: Plan, kind: str, budget: Decimal) -> None:
    current = next((x for x in plan.components if x.kind == kind), None)
    if current is None:
        return
    base = [x for x in plan.components if x.kind not in (kind, "psu")]
    for candidate in sorted(_candidates(kind, base), key=lambda x: x.price, reverse=True):
        if candidate.price <= current.price:
            return
        trial = [*base, candidate]
        psu = _cheapest_acceptable("psu", trial)
        if psu is None:
            continue
        trial.append(psu)
        if sum(x.price for x in trial) <= budget and _acceptable([to_part(x) for x in trial]):
            plan.components = sorted(trial, key=lambda x: PICK_ORDER.index(x.kind))
            plan.notes.append(("UPGRADED", {"kind": kind}))
            return


def _try_downgrade(plan: Plan) -> bool:
    """Replace the priciest performance/storage part with the next cheaper one."""
    kinds = PERFORMANCE_KINDS | {"storage"}
    for current in sorted(
        (x for x in plan.components if x.kind in kinds), key=lambda x: x.price, reverse=True
    ):
        base = [x for x in plan.components if x is not current and x.kind != "psu"]
        cheaper = sorted(
            (x for x in _candidates(current.kind, base) if x.price < current.price),
            key=lambda x: x.price,
            reverse=True,
        )
        for candidate in cheaper:
            trial = [*base, candidate]
            psu = _cheapest_acceptable("psu", trial)
            if psu and _acceptable([to_part(x) for x in [*trial, psu]]):
                plan.components = sorted([*trial, psu], key=lambda x: PICK_ORDER.index(x.kind))
                plan.notes.append(("DOWNGRADED", {"kind": current.kind}))
                return True
    return False
