import logging
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings

from . import tools
from .llm import AdvisorError, advise_with_claude
from .planner import plan_build

logger = logging.getLogger(__name__)

LANGUAGES = ("en", "uk")

KINDS = {
    "en": {
        "cpu": "CPU", "motherboard": "motherboard", "ram": "memory", "gpu": "graphics card",
        "storage": "storage", "psu": "power supply", "case": "case", "cooler": "CPU cooler",
    },
    "uk": {
        "cpu": "процесор", "motherboard": "материнська плата", "ram": "пам'ять",
        "gpu": "відеокарта", "storage": "накопичувач", "psu": "блок живлення",
        "case": "корпус", "cooler": "кулер",
    },
}  # fmt: skip

TEXTS = {
    "en": {
        "SUMMARY": (
            "Rule-based {use_case} build for {budget}: the budget is split by slot, "
            "performance parts get the most money, the rest take the cheapest option "
            "that raises no compatibility problems."
        ),
        "AI_UNAVAILABLE": "The AI advisor was unavailable; this is the rule-based recommendation.",
        "REPLANNED": "Re-planned with smaller shares to fit the budget.",
        "OVER_BUDGET": "Total {total} is above the {budget} budget.",
        "NO_GPU_NEEDED": "No graphics card: integrated graphics are enough for office work.",
        "SHARE_EXCEEDED": "{kind}: nothing fit its share, took the cheapest option.",
        "NO_PART": "{kind}: no compatible part in the catalog.",
        "UPGRADED": "Upgraded the {kind} with the remaining budget.",
        "DOWNGRADED": "Downgraded the {kind} to stay within the budget.",
    },
    "uk": {
        "SUMMARY": (
            "Збірка «{use_case}» за правилами на {budget}: бюджет розподілено між слотами, "
            "найбільше отримують деталі, що впливають на продуктивність, решта — найдешевший "
            "варіант без проблем сумісності."
        ),
        "AI_UNAVAILABLE": "AI-порадник недоступний, це рекомендація планувальника на правилах.",
        "REPLANNED": "Переплановано з меншими частками, щоб вкластися в бюджет.",
        "OVER_BUDGET": "Разом {total} — більше за бюджет {budget}.",
        "NO_GPU_NEEDED": "Без відеокарти: для офісу достатньо вбудованої графіки.",
        "SHARE_EXCEEDED": "{kind}: у свою частку нічого не влізло, взято найдешевший варіант.",
        "NO_PART": "{kind}: у каталозі немає сумісної деталі.",
        "UPGRADED": "{kind}: покращено на залишок бюджету.",
        "DOWNGRADED": "{kind}: взято дешевшу модель, щоб вкластися в бюджет.",
    },
}

USE_CASE_NAMES = {
    "en": {"gaming": "gaming", "streaming": "gaming + streaming", "workstation": "workstation",
           "office": "office"},
    "uk": {"gaming": "ігри", "streaming": "ігри + стрими", "workstation": "робоча станція",
           "office": "офіс"},
}  # fmt: skip


@dataclass(frozen=True)
class Money:
    """How the user entered the budget; amounts in notes are shown the same way."""

    amount: Decimal
    currency: str = "USD"
    uah_rate: Decimal | None = None

    def format(self, usd: Decimal | None = None) -> str:
        """``usd`` converted to this currency, or the entered amount itself."""
        if self.currency == "UAH" and self.uah_rate:
            value = self.amount if usd is None else usd * self.uah_rate
            return f"{value:,.0f} грн".replace(",", "\u00a0")
        value = self.amount if usd is None else usd
        return f"${value:,.2f}"


def render_note(code: str, params: dict, language: str, money: Money | None = None) -> str:
    params = dict(params)
    if money is not None:
        for key in ("total", "budget"):
            if key in params:
                params[key] = money.format(Decimal(params[key]))
    if "kind" in params:
        params["kind"] = KINDS[language].get(params["kind"], params["kind"])
        params["kind"] = params["kind"][:1].upper() + params["kind"][1:]
    return TEXTS[language][code].format(**params)


def advise(
    *,
    budget: Decimal,
    use_case: str,
    preferences: str = "",
    language: str = "en",
    display: Money | None = None,
) -> dict:
    """``budget`` is in USD (the catalog's currency); ``display`` is what the user typed."""
    language = language if language in LANGUAGES else "en"
    display = display or Money(budget)
    notes: list[str] = []
    if settings.ANTHROPIC_API_KEY:
        try:
            result = advise_with_claude(
                budget=budget, use_case=use_case, preferences=preferences, language=language
            )
            return _response(
                "claude", result.model, result.summary, result.component_ids, budget, notes, display
            )
        except AdvisorError as exc:
            logger.warning("Claude advisor failed, using the rule-based planner: %s", exc)
            notes.append(TEXTS[language]["AI_UNAVAILABLE"])

    plan = plan_build(budget, use_case)
    summary = TEXTS[language]["SUMMARY"].format(
        use_case=USE_CASE_NAMES[language][use_case], budget=display.format()
    )
    notes += [render_note(code, params, language, display) for code, params in plan.notes]
    return _response("rule_based", "", summary, plan.ids, budget, notes, display)


def _response(source, model, summary, ids, budget, notes, display: Money) -> dict:
    components = tools.load_components(ids)
    report, total = tools.check_components(ids)
    return {
        "source": source,
        "model": model,
        "summary": summary,
        "notes": notes,
        "components": components,
        "total_price": total,
        "budget": budget,
        "budget_amount": display.amount,
        "budget_currency": display.currency,
        "compatibility": report.as_dict(),
    }
