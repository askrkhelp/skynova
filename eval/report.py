"""Renders eval/report.md from a run's results + computed metrics.

Format: a metrics summary table (spec §9's six metrics, plus the grounding
target callout), then a "Failing / borderline scenarios" section — every
scenario with at least one mismatch reason (eval/metrics.py's
`match_reasons`) — with enough detail (turns, replies, expected vs. actual,
notes) to debug without re-running the harness.
"""

from __future__ import annotations

from typing import Any

from eval.metrics import match_reasons


def _fmt_pct(rate: float | None) -> str:
    return f"{rate:.1%}" if rate is not None else "n/a"


def _metrics_table(metrics: dict[str, Any]) -> str:
    rr = metrics["resolution_rate"]
    ra = metrics["routing_accuracy"]
    ec = metrics["escalation_calibration"]
    gh = metrics["grounding_hallucination_rate"]
    jf = metrics["justification_faithfulness"]
    orr = metrics["orchestration_reliability"]

    lines = [
        "| # | Metric | Result | Detail |",
        "|---|---|---|---|",
        f"| 1 | Resolution rate | {_fmt_pct(rr['rate'])} | {rr['correct']}/{rr['scope']} assistant-alone-resolvable scenarios closed correctly |",
        f"| 2 | Routing accuracy | {_fmt_pct(ra['rate'])} | {ra['correct']}/{ra['scope']} route-verdict scenarios sent to the correct team |",
        f"| 3 | Escalation calibration | {_fmt_pct(ec['rate'])} | recall(hard→escalated)={_fmt_pct(ec['recall_hard_cases_escalated'])}, specificity(clear→not escalated)={_fmt_pct(ec['specificity_clear_cases_not_escalated'])} (TP={ec['true_positive']} FN={ec['false_negative']} FP={ec['false_positive']} TN={ec['true_negative']}) |",
        f"| 4 | Grounding / hallucination rate | {gh['hallucination_rate']:.2%} | {gh['unverified_claims']}/{gh['total_claims']} numeric claims unverified — target <{gh['target']:.0%}, {'MEETS' if gh['meets_target'] else 'MISSES'} target |",
        f"| 5 | Justification faithfulness | {jf['mean_score_0_to_3'] if jf['mean_score_0_to_3'] is not None else 'n/a'} / 3 | judged {jf['judged']}/{jf['eligible']} verdict-bearing cases; low-score (<=1) ids: {jf['low_score_ids'] or 'none'} |",
        f"| 6 | Orchestration reliability | {_fmt_pct(orr['rate'])} | {orr['successes']}/{orr['scope']} decision scenarios completed with a real verdict inside the wall-clock caps |",
    ]
    return "\n".join(lines)


def _scenario_detail(result: dict[str, Any], reasons: list[str]) -> str:
    exp = result["expected"]
    act = result["actual"]
    lines = [
        f"### {result['id']} — {result.get('category')}",
        f"- Notes: {result.get('notes')}",
        f"- Expected: {result.get('expected_text')}",
        f"- Expected outcome: case={exp['case']} verdict={exp['verdict']} team={exp['team']} clarify={exp['clarify']}",
        f"- Actual outcome: case_id={act['case_id']} verdict={act['verdict']} team={act['team']} clarify={act['clarify']} guardrail_tripped={act['guardrail_tripped']}",
        f"- Duration: {result.get('duration_s')}s",
        "- Mismatch reasons:",
    ]
    lines.extend(f"  - {reason}" for reason in reasons)
    if result.get("faithfulness"):
        lines.append(f"- Faithfulness score: {result['faithfulness'].get('score')} — {result['faithfulness'].get('rationale')}")
    lines.append("- Transcript:")
    for i, turn in enumerate(result.get("turns", []), start=1):
        lines.append(f"  {i}. **User:** {turn['text']}")
        lines.append(f"     **Assistant:** {turn.get('reply')}")
        if turn.get("case_id"):
            lines.append(f"     _(opened {turn['case_id']})_")
    return "\n".join(lines)


def render_report(results: list[dict[str, Any]], metrics: dict[str, Any]) -> str:
    failing = [(r, match_reasons(r)) for r in results]
    failing = [(r, reasons) for r, reasons in failing if reasons]

    parts = [
        "# ResolveAI Evaluation Report (Epic 8)",
        "",
        f"Scenarios run: {len(results)} (from `data/eval_scenarios.json`). "
        f"{metrics['overall_match_rate']['matched']}/{metrics['overall_match_rate']['total']} fully matched their expected outcome.",
        "",
        "## Metrics (spec §9)",
        "",
        _metrics_table(metrics),
        "",
        f"## Failing / borderline scenarios ({len(failing)})",
        "",
    ]
    if not failing:
        parts.append("None — every scenario matched its expected outcome.")
    else:
        for result, reasons in failing:
            parts.append(_scenario_detail(result, reasons))
            parts.append("")

    return "\n".join(parts)
