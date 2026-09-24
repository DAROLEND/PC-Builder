"""Claude-powered build advisor.

A manual tool-use loop (not the SDK's beta tool runner) because the loop has
to stop on a *specific* tool call — ``submit_build`` — and the server must be
able to reject that submission and send the model back to work.

Tools map one-to-one onto our own API:
* ``search_components`` → ``GET /api/components/?category=&max_price=&compatible_with=``
* ``check_build``       → ``POST /api/compatibility/check/``
* ``submit_build``      → final answer, re-validated by the same engine.

The model never gets to "just say" a build: whatever it proposes is checked
server-side, and a build with compatibility errors or over budget is returned
to the model as a tool error.
"""

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import anthropic
from django.conf import settings

from . import tools

logger = logging.getLogger(__name__)

CATEGORIES = list(tools.KEY_SPECS)
BUDGET_TOLERANCE = Decimal("1.02")  # allow 2 % over the stated budget

SYSTEM_PROMPT = """\
You are the build advisor of PC Builder, an online PC configurator.
You help a customer choose a complete, compatible desktop PC within a budget.

You can only recommend components that exist in our catalog, so always use
the tools: search the catalog per category (pass the ids you have already
chosen as `compatible_with` so you only see parts that fit), run
`check_build` on your candidate list, and finish by calling `submit_build`.

A complete build has exactly one CPU, motherboard, PSU and case, at least
one memory kit and one storage drive; add a CPU cooler unless the CPU is a
low-TDP part, and a graphics card unless the use case is office work and the
CPU has integrated graphics.

Spend the budget where it matters for the stated use case (for gaming that
is mostly the GPU) and don't overspend on parts that don't affect
performance. Prices are in USD. The summary for the customer is 3–6
sentences explaining the key trade-offs, in the language named in the request.
"""

LANGUAGE_NAMES = {"en": "English", "uk": "Ukrainian"}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "search_components",
        "description": (
            "Search the catalog in one category. Returns up to 15 active components, most "
            "expensive first, with id, name, price and key specs. Use `compatible_with` "
            "with the ids you have already picked to get only parts that fit them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": CATEGORIES},
                "max_price": {"type": "number", "description": "Max price in USD."},
                "compatible_with": {"type": "array", "items": {"type": "integer"}},
                "query": {"type": "string", "description": "Substring of the product name."},
            },
            "required": ["category"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check_build",
        "description": (
            "Run the compatibility engine on a list of component ids. Returns errors "
            "(must fix), warnings, missing required parts, estimated wattage and total price."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"component_ids": {"type": "array", "items": {"type": "integer"}}},
            "required": ["component_ids"],
            "additionalProperties": False,
        },
    },
    {
        "name": "submit_build",
        "description": (
            "Submit the final recommendation. It is rejected if the build has "
            "compatibility errors, is incomplete, or is over budget; fix and resubmit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "component_ids": {"type": "array", "items": {"type": "integer"}},
                "summary": {"type": "string"},
            },
            "required": ["component_ids", "summary"],
            "additionalProperties": False,
        },
    },
]


class AdvisorError(Exception):
    pass


@dataclass
class LlmResult:
    component_ids: list[int]
    summary: str
    model: str


def _run_tool(
    name: str, args: dict[str, Any], budget: Decimal
) -> tuple[str, bool, LlmResult | None]:
    """Execute one tool call. Returns (content, is_error, final_result)."""
    if name == "search_components":
        if args.get("category") not in CATEGORIES:
            return f"Unknown category. Use one of {CATEGORIES}.", True, None
        found = tools.search_components(
            category=args["category"],
            max_price=args.get("max_price"),
            compatible_with=args.get("compatible_with") or None,
            query=args.get("query") or None,
        )
        return json.dumps([tools.describe(x) for x in found]), False, None

    if name in ("check_build", "submit_build"):
        ids = args.get("component_ids")
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            return "component_ids must be a list of integers.", True, None
        report, total = tools.check_components(ids)
        payload = {**report.as_dict(), "total_price_usd": str(total), "budget_usd": str(budget)}

        if name == "check_build":
            return json.dumps(payload), False, None

        problems = [e["message"] for e in payload["errors"]]
        if report.missing:
            problems.append(f"Missing required parts: {', '.join(report.missing)}.")
        if total > budget * BUDGET_TOLERANCE:
            problems.append(f"Total ${total} is over the ${budget} budget.")
        if problems:
            return "Rejected:\n- " + "\n- ".join(problems), True, None
        summary = str(args.get("summary", "")).strip()
        return "Accepted.", False, LlmResult(ids, summary, "")

    return f"Unknown tool {name}.", True, None


def advise_with_claude(
    *, budget: Decimal, use_case: str, preferences: str, language: str = "en"
) -> LlmResult:
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=90.0)
    user_message = (
        f"Budget: ${budget} USD.\nMain use: {use_case}.\n"
        f"Preferences: {preferences or '(none)'}\n"
        f"Write the summary in {LANGUAGE_NAMES.get(language, 'English')}."
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

    for _ in range(settings.ADVISOR_MAX_TOOL_ROUNDS):
        try:
            response = client.beta.messages.create(
                model=settings.ADVISOR_MODEL,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=messages,
                output_config={"effort": settings.ADVISOR_EFFORT},
                # On a policy decline the API re-runs the request on the
                # recommended fallback model instead of returning a refusal.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIError as exc:
            raise AdvisorError(f"Claude API error: {exc}") from exc

        if response.stop_reason == "refusal":
            raise AdvisorError("The model declined the request.")
        if response.stop_reason == "max_tokens":
            raise AdvisorError("The model ran out of output tokens.")

        # Keep the full content (thinking + tool_use blocks) in the history.
        messages.append({"role": "assistant", "content": response.content})

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            # The model answered in text without submitting; nudge it once more.
            messages.append(
                {"role": "user", "content": "Please call submit_build with your final build."}
            )
            continue

        results, final = [], None
        for block in tool_uses:
            try:
                content, is_error, outcome = _run_tool(block.name, dict(block.input), budget)
            except ValueError as exc:  # e.g. unknown component ids
                content, is_error, outcome = str(exc), True, None
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": is_error,
                }
            )
            final = final or outcome
        if final is not None:
            final.model = response.model
            return final
        # All tool results of one turn go back in a single user message.
        messages.append({"role": "user", "content": results})

    raise AdvisorError("The model did not submit a valid build in time.")
