"""Epic 8 scenario runner — executes data/eval_scenarios.json against the
live agent pipeline (Assistant Agent + Triage Orchestrator via one
AssistantSession per scenario), not the UI, per the Epic 8 build prompt.

Each scenario gets its own isolated MCP server (temp cases.json,
BookingLookup) — same isolation pattern as tests/test_assistant_agent.py —
so a run never touches the real data/cases.json. `run_scenario` returns a
plain dict (the "one result record per scenario" the acceptance criterion
asks for) rather than a dataclass, so the whole run serializes straight to
eval/results.json with no extra encoding step.

A scenario-level exception (including a live-call 429) is caught and
recorded on the result rather than raised, so one bad scenario doesn't lose
the rest of a long, quota-paced run — see CLAUDE.md's GEMINI_API_KEY pacing
note, which this runner's default --pace applies at the scenario boundary.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from app.agents.mcp_client import MCPBridge
from app.agents.session import AssistantSession
from app.guardrails.hallucination_check import extract_numeric_claims, verify_numeric_claims
from app.mcp_server.bookings import BookingLookup
from app.mcp_server.server import build_server
from app.store import LocalJSONCaseStore
from eval.golden import ExpectedOutcome, expected_outcome_for
from eval.judge import JudgeRunner

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIOS_PATH = REPO_ROOT / "data" / "eval_scenarios.json"

# Set on a case's justification.policy_clause by app/guardrails/caps.py when
# a guardrail cap trip (not the Orchestrator's real rule table) produced the
# verdict — used to flag a scenario as an orchestration-reliability failure
# even though it technically produced *some* verdict.
GUARDRAIL_POLICY_CLAUSE = "guardrail/human_review_required"


def load_scenarios(path: Path = DEFAULT_SCENARIOS_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


async def run_scenario(
    scenario: dict[str, Any],
    judge: JudgeRunner | None = None,
) -> dict[str, Any]:
    scenario_id = scenario["id"]
    tmp_dir = tempfile.TemporaryDirectory(prefix=f"resolveai_eval_{scenario_id}_")
    cases_path = Path(tmp_dir.name) / "cases.json"
    cases_path.write_text("[]", encoding="utf-8")
    server = build_server(cases=LocalJSONCaseStore(cases_path), bookings=BookingLookup())
    bridge = MCPBridge(server)
    session = AssistantSession(server=server, bridge=bridge, conversation_id=f"eval-{scenario_id}")

    turn_records: list[dict[str, Any]] = []
    error: str | None = None
    t0 = time.monotonic()
    try:
        for text in scenario["turns"]:
            result = await session.send(text)
            state = await session.get_state()
            chunks = list(state.get("_guardrail_chunks") or [])
            ok, unverified = verify_numeric_claims(result.get("reply", ""), chunks)
            turn_records.append(
                {
                    "text": text,
                    "extracted": result.get("extracted"),
                    "needs_clarification": result.get("needs_clarification"),
                    "clarifying_question": result.get("clarifying_question"),
                    "reply": result.get("reply"),
                    "case_id": result.get("case_id"),
                    "citations": result.get("citations"),
                    "claims_total": len(extract_numeric_claims(result.get("reply", ""))),
                    "unverified_claims": unverified,
                    "grounded": ok,
                }
            )
    except Exception as exc:  # noqa: BLE001 - a scenario failure must not kill the run
        error = f"{type(exc).__name__}: {exc}"
    duration_s = round(time.monotonic() - t0, 2)

    case_ids = [t["case_id"] for t in turn_records if t.get("case_id")]
    final_case: dict[str, Any] | None = None
    if case_ids:
        try:
            final_case = await bridge.call("get_status", case_id=case_ids[-1])
        except Exception as exc:  # noqa: BLE001
            error = error or f"get_status failed: {type(exc).__name__}: {exc}"

    tmp_dir.cleanup()

    expected = expected_outcome_for(scenario_id)
    actual_verdict = final_case.get("verdict") if final_case else None
    actual_team = final_case.get("assigned_team") if final_case else None
    actual_clarify = any(t.get("needs_clarification") for t in turn_records)
    guardrail_tripped = bool(
        final_case
        and (final_case.get("justification") or {}).get("policy_clause") == GUARDRAIL_POLICY_CLAUSE
    )

    faithfulness: dict[str, Any] | None = None
    if judge is not None and final_case and final_case.get("justification") and not guardrail_tripped:
        try:
            score = await judge.score(
                issue_type=final_case.get("issue_type", ""),
                verdict=actual_verdict or "",
                justification=final_case["justification"],
            )
            faithfulness = {"score": score.score, "rationale": score.rationale}
        except Exception as exc:  # noqa: BLE001
            faithfulness = {"score": None, "rationale": f"judge error: {type(exc).__name__}: {exc}"}

    return {
        "id": scenario_id,
        "category": scenario.get("category"),
        "notes": scenario.get("notes"),
        "expected_text": scenario.get("expected"),
        "duration_s": duration_s,
        "error": error,
        "turns": turn_records,
        "final_case": final_case,
        "expected": {
            "case": expected.case,
            "verdict": expected.verdict,
            "team": expected.team,
            "clarify": expected.clarify,
        },
        "actual": {
            "case_id": case_ids[-1] if case_ids else None,
            "verdict": actual_verdict,
            "team": actual_team,
            "clarify": actual_clarify,
            "guardrail_tripped": guardrail_tripped,
        },
        "faithfulness": faithfulness,
    }
