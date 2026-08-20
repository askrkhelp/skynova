"""Offline tests for the Epic 8 evaluation harness (eval/). No live model
call needed: eval/golden.py's expected outcomes come from the same pure,
dependency-free rule-table functions Epic 5 already unit-tests
(app.agents.policy_agent.evaluate_policy_signal / app.agents.risk_agent.
score_risk / app.agents.triage_orchestrator.decide_verdict), and
eval/metrics.py + eval/report.py operate on plain result dicts that this
suite constructs by hand rather than by running the real pipeline.
"""

from __future__ import annotations

from eval.golden import CLARIFY_IDS, DECISION_SCENARIOS, expected_outcome_for
from eval.metrics import compute_metrics, match_reasons
from eval.report import render_report
from eval.runner import DEFAULT_SCENARIOS_PATH, load_scenarios

# ---------------------------------------------------------------------------
# golden.py
# ---------------------------------------------------------------------------


def test_scenario_id_groups_partition_the_full_set_with_no_overlap():
    scenarios = load_scenarios(DEFAULT_SCENARIOS_PATH)
    all_ids = {s["id"] for s in scenarios}

    assert set(DECISION_SCENARIOS) & CLARIFY_IDS == set()
    assert set(DECISION_SCENARIOS) <= all_ids
    assert CLARIFY_IDS <= all_ids

    other_ids = all_ids - set(DECISION_SCENARIOS) - CLARIFY_IDS
    for scenario_id in other_ids:
        outcome = expected_outcome_for(scenario_id)
        assert outcome.case is False
        assert outcome.clarify is False
        assert outcome.verdict is None


def test_clarify_ids_expect_clarification_and_no_case():
    for scenario_id in CLARIFY_IDS:
        outcome = expected_outcome_for(scenario_id)
        assert outcome.clarify is True
        assert outcome.case is False
        assert outcome.verdict is None


def test_decision_scenario_team_matches_eval_scenarios_json_ground_truth():
    """eval_scenarios.json's own "expected_team" field was hand-authored
    independently of the rule table; cross-checking golden.py's re-derived
    team against it catches both a golden.py transcription error and a
    rule-table regression.

    E17 (the injection scenario) is a known exception: its json expected_team
    is null because the scenario's focus is injection resistance, not
    routing, but the underlying signal (Saver refund dispute) is identical to
    E06/E42/E44-E46, all of which the json *does* label expected_team=
    "Refunds". Treated as "not asserted" rather than "expected empty" here —
    a real routing bug on E17 would still be caught via
    eval/golden.py's own decide_verdict/evaluate_policy_signal unit coverage
    in tests/test_triage_orchestrator.py.
    """
    scenarios = {s["id"]: s for s in load_scenarios(DEFAULT_SCENARIOS_PATH)}
    known_unasserted = {"E17"}
    mismatches = []
    for scenario_id in DECISION_SCENARIOS:
        outcome = expected_outcome_for(scenario_id)
        json_team = scenarios[scenario_id]["expected_team"]
        if json_team is None and scenario_id in known_unasserted:
            continue
        if outcome.team != json_team:
            mismatches.append((scenario_id, outcome.team, json_team))
    assert not mismatches, f"golden.py team vs eval_scenarios.json expected_team mismatches: {mismatches}"


def test_decision_scenarios_cover_every_orchestrator_backed_category():
    scenarios = {s["id"]: s for s in load_scenarios(DEFAULT_SCENARIOS_PATH)}
    for scenario_id in DECISION_SCENARIOS:
        assert scenario_id in scenarios


# ---------------------------------------------------------------------------
# metrics.py — built from hand-constructed result dicts, matching the shape
# eval/runner.py's run_scenario() produces.
# ---------------------------------------------------------------------------


def _result(
    scenario_id: str,
    *,
    expected_case: bool,
    expected_verdict: str | None,
    expected_team: str | None,
    expected_clarify: bool,
    actual_verdict: str | None,
    actual_team: str | None,
    actual_case_id: str | None,
    actual_clarify: bool = False,
    guardrail_tripped: bool = False,
    error: str | None = None,
    turns: list[dict] | None = None,
    faithfulness: dict | None = None,
) -> dict:
    return {
        "id": scenario_id,
        "category": "test",
        "notes": "",
        "expected_text": "",
        "duration_s": 1.0,
        "error": error,
        "turns": turns if turns is not None else [{"text": "x", "reply": "ok", "claims_total": 0, "unverified_claims": []}],
        "final_case": None,
        "expected": {
            "case": expected_case,
            "verdict": expected_verdict,
            "team": expected_team,
            "clarify": expected_clarify,
        },
        "actual": {
            "case_id": actual_case_id,
            "verdict": actual_verdict,
            "team": actual_team,
            "clarify": actual_clarify,
            "guardrail_tripped": guardrail_tripped,
        },
        "faithfulness": faithfulness,
    }


def test_resolution_rate_counts_correct_auto_resolve_and_no_case_scenarios():
    results = [
        _result("A", expected_case=True, expected_verdict="auto_resolve", expected_team=None, expected_clarify=False, actual_verdict="auto_resolve", actual_team=None, actual_case_id="CASE-1"),
        _result("B", expected_case=False, expected_verdict=None, expected_team=None, expected_clarify=False, actual_verdict=None, actual_team=None, actual_case_id=None),
        _result("C", expected_case=True, expected_verdict="auto_resolve", expected_team=None, expected_clarify=False, actual_verdict="route", actual_team="Refunds", actual_case_id="CASE-2"),
        _result("D", expected_case=True, expected_verdict="route", expected_team="Refunds", expected_clarify=False, actual_verdict="route", actual_team="Refunds", actual_case_id="CASE-3"),
    ]
    metrics = compute_metrics(results)
    rr = metrics["resolution_rate"]
    assert rr["scope"] == 3  # A, B, C (D is out of scope: expected route)
    assert rr["correct"] == 2  # A and B; C wrongly routed instead of auto-resolving
    assert rr["rate"] == round(2 / 3, 4)


def test_routing_accuracy_requires_correct_team():
    results = [
        _result("A", expected_case=True, expected_verdict="route", expected_team="Baggage", expected_clarify=False, actual_verdict="route", actual_team="Baggage", actual_case_id="CASE-1"),
        _result("B", expected_case=True, expected_verdict="route", expected_team="Refunds", expected_clarify=False, actual_verdict="route", actual_team="Rebooking", actual_case_id="CASE-2"),
    ]
    metrics = compute_metrics(results)
    ra = metrics["routing_accuracy"]
    assert ra["scope"] == 2
    assert ra["correct"] == 1
    assert ra["rate"] == 0.5


def test_escalation_calibration_confusion_counts():
    results = [
        _result("hard1", expected_case=True, expected_verdict="escalate", expected_team="Refunds", expected_clarify=False, actual_verdict="escalate", actual_team="Refunds", actual_case_id="CASE-1"),
        _result("hard2", expected_case=True, expected_verdict="escalate", expected_team="Refunds", expected_clarify=False, actual_verdict="route", actual_team="Refunds", actual_case_id="CASE-2"),
        _result("clear1", expected_case=True, expected_verdict="auto_resolve", expected_team=None, expected_clarify=False, actual_verdict="auto_resolve", actual_team=None, actual_case_id="CASE-3"),
        _result("clear2", expected_case=True, expected_verdict="route", expected_team="Baggage", expected_clarify=False, actual_verdict="escalate", actual_team="Baggage", actual_case_id="CASE-4"),
    ]
    metrics = compute_metrics(results)
    ec = metrics["escalation_calibration"]
    assert ec["true_positive"] == 1
    assert ec["false_negative"] == 1
    assert ec["false_positive"] == 1
    assert ec["true_negative"] == 1
    assert ec["recall_hard_cases_escalated"] == 0.5
    assert ec["specificity_clear_cases_not_escalated"] == 0.5


def test_guardrail_tripped_verdict_not_counted_as_a_real_escalate():
    results = [
        _result(
            "trip",
            expected_case=True,
            expected_verdict="auto_resolve",
            expected_team=None,
            expected_clarify=False,
            actual_verdict="escalate",
            actual_team="Refunds",
            actual_case_id="CASE-1",
            guardrail_tripped=True,
        ),
    ]
    metrics = compute_metrics(results)
    # A clear (auto_resolve-expected) case whose guardrail tripped is a
    # false positive for escalation, not a legitimate escalate.
    assert metrics["escalation_calibration"]["false_positive"] == 1
    assert metrics["orchestration_reliability"]["successes"] == 0


def test_grounding_rate_computes_unverified_over_total_claims():
    results = [
        _result(
            "A",
            expected_case=False,
            expected_verdict=None,
            expected_team=None,
            expected_clarify=False,
            actual_verdict=None,
            actual_team=None,
            actual_case_id=None,
            turns=[
                {"text": "q1", "reply": "r1", "claims_total": 2, "unverified_claims": ["500"]},
                {"text": "q2", "reply": "r2", "claims_total": 1, "unverified_claims": []},
            ],
        )
    ]
    gh = compute_metrics(results)["grounding_hallucination_rate"]
    assert gh["total_claims"] == 3
    assert gh["unverified_claims"] == 1
    assert gh["hallucination_rate"] == round(1 / 3, 4)
    assert gh["meets_target"] is False  # 33% >> 2% target


def test_grounding_rate_zero_claims_is_trivially_grounded():
    results = [
        _result("A", expected_case=False, expected_verdict=None, expected_team=None, expected_clarify=False, actual_verdict=None, actual_team=None, actual_case_id=None, turns=[])
    ]
    gh = compute_metrics(results)["grounding_hallucination_rate"]
    assert gh["hallucination_rate"] == 0.0
    assert gh["meets_target"] is True


def test_justification_faithfulness_averages_scored_cases_only():
    results = [
        _result("A", expected_case=True, expected_verdict="auto_resolve", expected_team=None, expected_clarify=False, actual_verdict="auto_resolve", actual_team=None, actual_case_id="CASE-1", faithfulness={"score": 3, "rationale": "good"}),
        _result("B", expected_case=True, expected_verdict="route", expected_team="Refunds", expected_clarify=False, actual_verdict="route", actual_team="Refunds", actual_case_id="CASE-2", faithfulness={"score": 1, "rationale": "weak"}),
        _result("C", expected_case=True, expected_verdict="route", expected_team="Refunds", expected_clarify=False, actual_verdict="route", actual_team="Refunds", actual_case_id="CASE-3", faithfulness=None),
    ]
    jf = compute_metrics(results)["justification_faithfulness"]
    assert jf["judged"] == 2
    assert jf["eligible"] == 3
    assert jf["mean_score_0_to_3"] == 2.0
    assert jf["low_score_ids"] == ["B"]


def test_orchestration_reliability_scoped_to_decision_scenarios():
    results = [
        _result("A", expected_case=True, expected_verdict="auto_resolve", expected_team=None, expected_clarify=False, actual_verdict="auto_resolve", actual_team=None, actual_case_id="CASE-1"),
        _result("B", expected_case=True, expected_verdict="route", expected_team="Refunds", expected_clarify=False, actual_verdict=None, actual_team=None, actual_case_id=None, error="TimeoutError: boom"),
        _result("C", expected_case=False, expected_verdict=None, expected_team=None, expected_clarify=False, actual_verdict=None, actual_team=None, actual_case_id=None),
    ]
    orr = compute_metrics(results)["orchestration_reliability"]
    assert orr["scope"] == 2  # A and B only; C isn't a decision scenario
    assert orr["successes"] == 1
    assert orr["rate"] == 0.5


def test_match_reasons_empty_for_a_fully_matching_scenario():
    result = _result("A", expected_case=False, expected_verdict=None, expected_team=None, expected_clarify=False, actual_verdict=None, actual_team=None, actual_case_id=None)
    assert match_reasons(result) == []


def test_match_reasons_flags_verdict_and_team_mismatches():
    result = _result("A", expected_case=True, expected_verdict="escalate", expected_team="Refunds", expected_clarify=False, actual_verdict="route", actual_team="Baggage", actual_case_id="CASE-1")
    reasons = match_reasons(result)
    assert any("verdict mismatch" in r for r in reasons)
    assert any("team mismatch" in r for r in reasons)


# ---------------------------------------------------------------------------
# report.py
# ---------------------------------------------------------------------------


def test_render_report_includes_all_six_metrics_and_failing_scenarios():
    results = [
        _result("A", expected_case=True, expected_verdict="auto_resolve", expected_team=None, expected_clarify=False, actual_verdict="auto_resolve", actual_team=None, actual_case_id="CASE-1"),
        _result("B", expected_case=True, expected_verdict="escalate", expected_team="Refunds", expected_clarify=False, actual_verdict="route", actual_team="Refunds", actual_case_id="CASE-2"),
    ]
    metrics = compute_metrics(results)
    report = render_report(results, metrics)

    assert "Resolution rate" in report
    assert "Routing accuracy" in report
    assert "Escalation calibration" in report
    assert "Grounding / hallucination rate" in report
    assert "Justification faithfulness" in report
    assert "Orchestration reliability" in report
    assert "### B — test" in report
    assert "### A — test" not in report  # A matched; only failing scenarios get a detail section


def test_render_report_handles_zero_failing_scenarios():
    results = [
        _result("A", expected_case=False, expected_verdict=None, expected_team=None, expected_clarify=False, actual_verdict=None, actual_team=None, actual_case_id=None),
    ]
    metrics = compute_metrics(results)
    report = render_report(results, metrics)
    assert "None — every scenario matched its expected outcome." in report
