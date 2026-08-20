"""The six spec §9 metrics, computed from a list of eval/runner.py result
records.

Each metric is scoped to a different subset of the golden set, matching what
the spec text actually asks for rather than reusing one blanket "% correct":

1. resolution_rate — scenarios expected to be closeable by the assistant
   *alone* (a grounded answer with no case, or a case that resolves
   auto_resolve): fraction where that's what actually happened.
2. routing_accuracy — scenarios expected to route to a team: fraction that
   both got verdict=="route" AND landed on the *correct* team.
3. escalation_calibration — across every decision-requiring scenario, recall
   (truly-hard cases that got escalated) and specificity (clear cases that
   did NOT get escalated), per spec's "high coverage of truly-hard cases +
   high automation on clear ones."
4. grounding/hallucination_rate — unverified numeric claims / total numeric
   claims across every turn (target <2%, spec §9.4).
5. justification_faithfulness — mean 0-3 LLM-judge score across judged
   verdict-bearing cases.
6. orchestration_reliability — fraction of decision-requiring scenarios that
   ran to completion (no exception, a real verdict, no guardrail-cap
   fallback) within the wall-clock caps.

A guardrail-cap trip (app/guardrails/caps.py's fallback escalation) is
deliberately NOT counted as a correct "escalate" for calibration/resolution
purposes even though its verdict string is "escalate" — it means the
Orchestrator/Assistant didn't finish its real job in time, which is exactly
what orchestration_reliability exists to catch separately.
"""

from __future__ import annotations

from typing import Any

GROUNDING_TARGET = 0.02


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def match_reasons(result: dict[str, Any]) -> list[str]:
    """Every way `result`'s actual outcome diverges from its expected one.
    Empty list means the scenario fully matched — used both to build the
    report's failing/borderline list and to feed the metrics below.
    """
    reasons: list[str] = []
    if result.get("error"):
        reasons.append(f"scenario error: {result['error']}")

    exp = result["expected"]
    act = result["actual"]

    if exp["clarify"] != act["clarify"]:
        reasons.append(f"clarify mismatch: expected={exp['clarify']} actual={act['clarify']}")
    if exp["case"] and not act["case_id"]:
        reasons.append("expected a case to open; none did")
    if not exp["case"] and act["case_id"] and not exp["clarify"]:
        reasons.append("a case opened but none was expected")
    if exp["verdict"] is not None and act["verdict"] != exp["verdict"]:
        reasons.append(f"verdict mismatch: expected={exp['verdict']} actual={act['verdict']}")
    if exp["team"] is not None and act["team"] != exp["team"]:
        reasons.append(f"team mismatch: expected={exp['team']} actual={act['team']}")
    if act.get("guardrail_tripped"):
        reasons.append("guardrail cap tripped — fallback escalation, not a real verdict")

    for i, turn in enumerate(result.get("turns", [])):
        if turn.get("unverified_claims"):
            reasons.append(f"turn {i + 1}: unverified numeric claims {turn['unverified_claims']}")

    return reasons


def resolution_rate(results: list[dict[str, Any]]) -> dict[str, Any]:
    scope = [
        r
        for r in results
        if r["expected"]["verdict"] == "auto_resolve" or (not r["expected"]["case"] and not r["expected"]["clarify"])
    ]
    correct = 0
    for r in scope:
        exp, act = r["expected"], r["actual"]
        if r.get("error"):
            continue
        if exp["verdict"] == "auto_resolve":
            if act["verdict"] == "auto_resolve" and act["case_id"] and not act["guardrail_tripped"]:
                correct += 1
        else:
            if act["case_id"] is None and not act["clarify"]:
                correct += 1
    return {"rate": _safe_rate(correct, len(scope)), "correct": correct, "scope": len(scope)}


def routing_accuracy(results: list[dict[str, Any]]) -> dict[str, Any]:
    scope = [r for r in results if r["expected"]["verdict"] == "route"]
    correct = sum(
        1
        for r in scope
        if not r.get("error")
        and r["actual"]["verdict"] == "route"
        and r["actual"]["team"] == r["expected"]["team"]
        and not r["actual"]["guardrail_tripped"]
    )
    return {"rate": _safe_rate(correct, len(scope)), "correct": correct, "scope": len(scope)}


def escalation_calibration(results: list[dict[str, Any]]) -> dict[str, Any]:
    scope = [r for r in results if r["expected"]["case"]]
    tp = fn = fp = tn = 0
    for r in scope:
        if r.get("error"):
            continue
        expected_escalate = r["expected"]["verdict"] == "escalate"
        # A guardrail-cap trip still counts as "escalated" here even though
        # it bypassed the real rule table: on a clear (auto_resolve/route
        # expected) scenario it's a genuine calibration failure — the system
        # failed to automate a clear case and fell back to a human instead.
        # orchestration_reliability (below) separately penalizes the trip
        # itself; this metric only cares about the resulting verdict shape.
        actual_escalate = r["actual"]["verdict"] == "escalate"
        if expected_escalate and actual_escalate:
            tp += 1
        elif expected_escalate and not actual_escalate:
            fn += 1
        elif not expected_escalate and actual_escalate:
            fp += 1
        else:
            tn += 1

    recall = _safe_rate(tp, tp + fn)
    specificity = _safe_rate(tn, tn + fp)
    components = [x for x in (recall, specificity) if x is not None]
    balanced = round(sum(components) / len(components), 4) if components else None
    return {
        "rate": balanced,
        "recall_hard_cases_escalated": recall,
        "specificity_clear_cases_not_escalated": specificity,
        "true_positive": tp,
        "false_negative": fn,
        "false_positive": fp,
        "true_negative": tn,
        "scope": len(scope),
    }


def grounding_rate(results: list[dict[str, Any]]) -> dict[str, Any]:
    total_claims = 0
    unverified_claims = 0
    for r in results:
        if r.get("error"):
            continue
        for turn in r.get("turns", []):
            total_claims += turn.get("claims_total") or 0
            unverified_claims += len(turn.get("unverified_claims") or [])
    rate = _safe_rate(unverified_claims, total_claims) if total_claims else 0.0
    return {
        "hallucination_rate": rate if rate is not None else 0.0,
        "unverified_claims": unverified_claims,
        "total_claims": total_claims,
        "target": GROUNDING_TARGET,
        "meets_target": (rate if rate is not None else 0.0) < GROUNDING_TARGET,
    }


def justification_faithfulness(results: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [r for r in results if r["expected"]["case"] and not r.get("error")]
    scored = [r for r in eligible if r.get("faithfulness") and r["faithfulness"].get("score") is not None]
    scores = [r["faithfulness"]["score"] for r in scored]
    mean_score = round(sum(scores) / len(scores), 2) if scores else None
    low_scores = [r["id"] for r in scored if r["faithfulness"]["score"] <= 1]
    return {
        "mean_score_0_to_3": mean_score,
        "judged": len(scored),
        "eligible": len(eligible),
        "low_score_ids": low_scores,
    }


def orchestration_reliability(results: list[dict[str, Any]]) -> dict[str, Any]:
    scope = [r for r in results if r["expected"]["case"]]
    successes = sum(
        1
        for r in scope
        if not r.get("error") and r["actual"]["verdict"] is not None and not r["actual"]["guardrail_tripped"]
    )
    return {"rate": _safe_rate(successes, len(scope)), "successes": successes, "scope": len(scope)}


def overall_match_rate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Not one of the six spec metrics — a general run-health rollup: the
    fraction of scenarios with zero mismatch reasons at all.
    """
    matched = sum(1 for r in results if not match_reasons(r))
    return {"rate": _safe_rate(matched, len(results)), "matched": matched, "total": len(results)}


def compute_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "resolution_rate": resolution_rate(results),
        "routing_accuracy": routing_accuracy(results),
        "escalation_calibration": escalation_calibration(results),
        "grounding_hallucination_rate": grounding_rate(results),
        "justification_faithfulness": justification_faithfulness(results),
        "orchestration_reliability": orchestration_reliability(results),
        "overall_match_rate": overall_match_rate(results),
    }
