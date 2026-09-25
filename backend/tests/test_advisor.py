from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import pytest

from apps.advisor import llm
from apps.advisor.planner import USE_CASES, plan_build
from apps.advisor.tools import BLOCKING_WARNINGS, check_components, describe

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("use_case", USE_CASES)
# Budgets reflect the frozen fixture (2026 market prices: DDR5 kits are expensive).
@pytest.mark.parametrize("budget", [1600, 2000, 3000, 6000])
def test_rule_based_plan_is_complete_compatible_and_within_budget(use_case, budget):
    plan = plan_build(Decimal(budget), use_case)
    report, total = check_components(plan.ids)
    assert report.is_compatible, report.errors
    assert report.is_complete, report.missing
    assert total <= budget, plan.notes
    # Works on paper is not enough: no cooler below the CPU's load, no tight PSU.
    assert not [w.code for w in report.warnings if w.code in BLOCKING_WARNINGS]


def test_infeasible_budget_is_reported_not_hidden():
    # No compatible build with a graphics card in the fixture costs $700.
    plan = plan_build(Decimal(700), "gaming")
    report, total = check_components(plan.ids)
    assert report.is_compatible and report.is_complete
    assert total > 700
    assert ("OVER_BUDGET", {"total": str(total), "budget": "700"}) in plan.notes


def test_office_budget_without_gpu_fits():
    plan = plan_build(Decimal(1000), "office")
    assert plan.total <= 1000
    assert "gpu" not in [c.kind for c in plan.components]


def test_bigger_budget_buys_a_better_gpu():
    gpu_price = {}
    for budget in (1600, 4000):
        plan = plan_build(Decimal(budget), "gaming")
        gpu_price[budget] = next(c.price for c in plan.components if c.kind == "gpu")
    assert gpu_price[4000] > gpu_price[1600]


def test_office_build_skips_gpu_when_cpu_has_igpu():
    plan = plan_build(Decimal(700), "office")
    kinds = [c.kind for c in plan.components]
    cpu = next(c for c in plan.components if c.kind == "cpu")
    assert ("gpu" in kinds) != cpu.specs["integrated_graphics"]


def test_advisor_endpoint_requires_login(api):
    assert api.post("/api/advisor/", {"budget": 1000, "use_case": "gaming"}).status_code == 401


def test_advisor_endpoint_rule_based(auth_api):
    resp = auth_api.post("/api/advisor/", {"budget": "1200", "use_case": "gaming"})
    assert resp.status_code == 200, resp.data
    assert resp.data["source"] == "rule_based"
    assert resp.data["compatibility"]["is_compatible"] is True
    assert Decimal(resp.data["total_price"]) <= 1200


def test_advisor_validates_input(auth_api):
    assert auth_api.post("/api/advisor/", {"budget": 50, "use_case": "gaming"}).status_code == 400
    assert auth_api.post("/api/advisor/", {"budget": 900, "use_case": "mining"}).status_code == 400


# --- Claude loop with a scripted fake client -------------------------------------------


def tool_use(name, tool_input, block_id):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=block_id)


def message(*blocks, stop_reason="tool_use"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, model="claude-opus-5")


class ScriptedClient:
    """Replays prepared responses and records what the loop sent back."""

    def __init__(self, responses):
        self._responses = iter(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        # Snapshot: the loop keeps appending to the same messages list.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return next(self._responses)


def run_advisor(settings, responses):
    settings.ANTHROPIC_API_KEY = "test-key"
    client = ScriptedClient(responses)
    with mock.patch.object(llm.anthropic, "Anthropic", return_value=client):
        result = llm.advise_with_claude(budget=Decimal(3000), use_case="gaming", preferences="")
    return result, client


def test_claude_loop_rejects_incompatible_submission_then_accepts(
    settings, comp, budget_gaming_ids
):
    bad = [comp("Ryzen 5 7600").id, comp("B450M Pro4").id]
    result, client = run_advisor(
        settings,
        [
            message(tool_use("search_components", {"category": "cpu", "max_price": 200}, "t1")),
            message(tool_use("submit_build", {"component_ids": bad, "summary": "x"}, "t2")),
            message(
                tool_use(
                    "submit_build", {"component_ids": budget_gaming_ids, "summary": "Good"}, "t3"
                )
            ),
        ],
    )
    assert result.component_ids == budget_gaming_ids
    assert result.summary == "Good"

    # The search result went back to the model...
    first_result = client.requests[1]["messages"][-1]["content"][0]
    assert first_result["tool_use_id"] == "t1" and not first_result["is_error"]
    # ...and the bad submission came back as an error explaining why.
    rejection = client.requests[2]["messages"][-1]["content"][0]
    assert rejection["is_error"] is True
    assert "socket" in rejection["content"]


def test_claude_submission_with_a_weak_cooler_is_rejected(comp):
    # AK400 (220 W) covers the Ryzen 9 9950X's 170 W TDP but not its 230 W PPT
    # under load: a warning in the configurator, a rejection for the advisor.
    ids = [comp("Ryzen 9 9950X").id, comp("AK400").id]
    content, is_error, result = llm._run_tool(
        "submit_build", {"component_ids": ids, "summary": "x"}, Decimal(3000)
    )
    assert is_error and result is None
    assert "230 W" in content


def test_model_sees_the_cpu_load_power_not_only_the_tdp(comp):
    specs = describe(comp("Ryzen 9 9950X"))["specs"]
    assert specs["tdp_w"] == 170 and specs["load_power_w"] == 230


def test_claude_loop_rejects_over_budget(settings, comp):
    pricey = [comp("ROG Astral GeForce RTX 5090 32GB").id]
    with pytest.raises(llm.AdvisorError):
        run_advisor(
            settings,
            [
                message(
                    tool_use("submit_build", {"component_ids": pricey, "summary": "x"}, f"t{i}")
                )
                for i in range(settings.ADVISOR_MAX_TOOL_ROUNDS)
            ],
        )


def test_claude_refusal_falls_back_to_rule_based(settings, auth_api):
    settings.ANTHROPIC_API_KEY = "test-key"
    client = ScriptedClient([message(stop_reason="refusal")])
    with mock.patch.object(llm.anthropic, "Anthropic", return_value=client):
        resp = auth_api.post("/api/advisor/", {"budget": "1000", "use_case": "gaming"})
    assert resp.status_code == 200
    assert resp.data["source"] == "rule_based"
    assert any("unavailable" in n for n in resp.data["notes"])


def test_claude_request_shape(settings, budget_gaming_ids):
    _, client = run_advisor(
        settings,
        [
            message(
                tool_use(
                    "submit_build", {"component_ids": budget_gaming_ids, "summary": "ok"}, "t1"
                )
            )
        ],
    )
    request = client.requests[0]
    assert request["model"] == settings.ADVISOR_MODEL
    assert request["fallbacks"] == "default"
    assert {t["name"] for t in request["tools"]} == {
        "search_components",
        "check_build",
        "submit_build",
    }


def test_advisor_answers_in_ukrainian(auth_api):
    resp = auth_api.post(
        "/api/advisor/", {"budget": "2000", "use_case": "gaming", "language": "uk"}
    )
    assert resp.status_code == 200
    assert "бюджет" in resp.data["summary"]


def test_every_issue_carries_params_for_localisation(api, comp):
    ids = [comp("Ryzen 5 7600").id, comp("B450M Pro4").id, comp("CH370").id]
    resp = api.post(
        "/api/compatibility/check/", {"items": [{"component": i, "quantity": 1} for i in ids]}
    )
    issue = next(e for e in resp.data["errors"] if e["code"] == "CPU_SOCKET_MISMATCH")
    assert issue["params"] == {
        "cpu": "AMD Ryzen 5 7600",
        "cpu_socket": "AM5",
        "board": "ASRock B450M Pro4",
        "board_socket": "AM4",
    }


def test_django_messages_follow_accept_language(api):
    resp = api.post("/api/auth/token/", {"username": "", "password": ""}, HTTP_ACCEPT_LANGUAGE="uk")
    assert resp.status_code == 400
    assert "Це поле не може бути порожнім." in str(resp.data)


@pytest.fixture
def uah_rate(db):
    from datetime import date

    from apps.catalog.models import ExchangeRate

    return ExchangeRate.objects.create(
        currency="USD", rate=Decimal("40.0000"), rate_date=date(2026, 9, 1)
    ).rate


def test_budget_in_hryvnias_is_converted_and_echoed(auth_api, uah_rate):
    resp = auth_api.post(
        "/api/advisor/",
        {"budget": "80000", "currency": "UAH", "use_case": "gaming", "language": "uk"},
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["budget"] == "2000.00"  # planned in USD: 80 000 / 40
    assert (resp.data["budget_amount"], resp.data["budget_currency"]) == ("80000.00", "UAH")
    assert "80 000 грн" in resp.data["summary"]
    assert Decimal(resp.data["total_price"]) <= Decimal("2000")


def test_hryvnia_limits_are_explained_in_hryvnias(auth_api, uah_rate):
    resp = auth_api.post(
        "/api/advisor/", {"budget": "5000", "currency": "UAH", "use_case": "gaming"}
    )
    assert resp.status_code == 400
    assert "12,000" in str(resp.data["budget"]) and "UAH" in str(resp.data["budget"])


def test_hryvnia_budget_needs_an_exchange_rate(auth_api, db):
    resp = auth_api.post(
        "/api/advisor/", {"budget": "50000", "currency": "UAH", "use_case": "gaming"}
    )
    assert resp.status_code == 400 and "currency" in resp.data


def test_daily_ai_quota_falls_back_to_the_planner(settings, auth_api):
    settings.ANTHROPIC_API_KEY = "test-key"
    settings.ADVISOR_DAILY_LLM_LIMIT = 1
    client = ScriptedClient([message(stop_reason="refusal")])
    with mock.patch.object(llm.anthropic, "Anthropic", return_value=client) as anthropic:
        auth_api.post("/api/advisor/", {"budget": "1000", "use_case": "gaming"})  # uses the quota
        resp = auth_api.post("/api/advisor/", {"budget": "1000", "use_case": "gaming"})
    assert anthropic.call_count == 1  # the second request never reached Claude
    assert resp.data["source"] == "rule_based"
    assert any("quota" in n for n in resp.data["notes"])
