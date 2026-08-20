"""Triage Orchestrator — Coordinator for the Intent/Policy/Risk specialists.

Per 01_Architecture_and_Design.md SS3.3: fetches the booking, runs the three
specialists (Intent and Policy concurrently — both do I/O; Risk is a pure
function so it needs no concurrency), combines their outputs through the
deterministic rule table, writes the verdict via update_case, and — for
route/escalate — assign_team, plus escalate(dossier) for escalate. The LLM
(Intent Agent) only classifies and contributes a rationale; the verdict
category itself always comes from `decide_verdict`, never from a model.

Verdict rule table (SS3.3), as implemented here:
  abuse_flag set (from Risk, or Intent classifying abuse_signal) -> escalate
  else policy category "auto"     -> auto_resolve (no team assigned)
  else policy category "route"    -> route (team assigned)
  else (policy category "escalate") -> escalate (team assigned)

Guardrails (Epic 6, SS3.6) wrap this module in two ways: `run_triage` caps
the whole run at ORCHESTRATOR_WALL_CLOCK_CAP_S wall-clock seconds, falling
back to a guardrail escalation of the already-created case rather than
hanging (the "1 pass per specialist" half of the same guardrail needs no
code — this module already calls each specialist exactly once, no retries);
and `build_dossier` redacts PII out of the traveler's free-text quote
(the dossier's structured fields — PNR, price, etc. — stay in plain text as
the case's essential facts; only the incidental free text a traveler typed
gets masked).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.agents.intent_agent import IntentAgentRunner
from app.agents.mcp_client import MCPBridge
from app.agents.policy_agent import PolicyAgentResult, run_policy_agent
from app.agents.risk_agent import RiskSignal, score_risk
from app.guardrails.caps import ORCHESTRATOR_WALL_CLOCK_CAP_S, escalate_case_for_guardrail
from app.guardrails.pii_redaction import redact_pii

logger = logging.getLogger("resolveai.guardrails")

# Below this, an Intent Agent disagreement with the case's recorded
# issue_type is treated as noise rather than a correction.
INTENT_OVERRIDE_CONFIDENCE = 0.6


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def decide_verdict(policy_result: PolicyAgentResult, risk_signal: RiskSignal, abuse_flag: bool) -> tuple[str, str | None]:
    """Pure rule-table application — the deterministic core SS3.3 requires."""
    if abuse_flag and policy_result.category != "escalate":
        return "escalate", policy_result.team or "Refunds"
    if policy_result.category == "auto":
        return "auto_resolve", None
    if policy_result.category == "route":
        return "route", policy_result.team
    return "escalate", policy_result.team or "Refunds"


def build_dossier(
    case: dict[str, Any],
    booking: dict[str, Any],
    justification: dict[str, Any],
    traveler_text: str,
) -> str:
    signals = justification.get("signals", {})
    lines = [
        f"Case {case['case_id']} — {case.get('issue_type')} — PNR {booking.get('pnr')} ({booking.get('passenger', 'unknown passenger')})",
        (
            f"Flight {booking.get('flight_no')} {booking.get('origin')}->{booking.get('destination')} "
            f"on {booking.get('depart_datetime')} | fare={booking.get('fare_class')} | "
            f"price=INR {booking.get('price_inr')} | status={booking.get('status')} | "
            f"delay={booking.get('delay_minutes')}min"
        ),
        (
            f"Account: age={booking.get('account_age_days')}d, prior_bookings={booking.get('prior_bookings')}, "
            f"prior_refunds_90d={booking.get('prior_refunds_90d')}, "
            f"return_to_order_ratio={booking.get('return_to_order_ratio')}"
        ),
        f"Policy clause: {justification.get('policy_clause')}",
        f"Policy text: {justification.get('policy_text')}",
        f"Risk score: {signals.get('risk_score')} | abuse_flag={signals.get('abuse_flag')}",
        f"Reasoning: {justification.get('reasoning')}",
        f"Traveler's original message: \"{redact_pii(traveler_text)}\"",
    ]
    return "\n".join(lines)


async def run_triage(
    case: dict[str, Any],
    bridge: MCPBridge,
    traveler_text: str,
    intent_runner: IntentAgentRunner | None = None,
) -> dict[str, Any]:
    """Runs the full SS3.3 sequence for an already-opened case, capped at
    ORCHESTRATOR_WALL_CLOCK_CAP_S wall-clock seconds (SS3.6 guardrail) —
    on timeout, the case is escalated instead of the call hanging.
    """
    try:
        return await asyncio.wait_for(
            _run_triage_inner(case, bridge, traveler_text, intent_runner),
            timeout=ORCHESTRATOR_WALL_CLOCK_CAP_S,
        )
    except asyncio.TimeoutError:
        reason = f"Triage Orchestrator exceeded the {ORCHESTRATOR_WALL_CLOCK_CAP_S:.0f}s wall-clock cap."
        final_case = await escalate_case_for_guardrail(
            bridge,
            case_id=case["case_id"],
            reason=reason,
            traveler_text=traveler_text,
            issue_type=case.get("issue_type"),
        )
        return {
            "case_id": case["case_id"],
            "pnr": case["pnr"],
            "issue_type": case["issue_type"],
            "verdict": "escalate",
            "justification": final_case["justification"],
            "assigned_team": final_case.get("assigned_team"),
            "dossier": final_case.get("dossier"),
            "created_at": final_case.get("updated_at", _now_iso()),
        }


async def _run_triage_inner(
    case: dict[str, Any],
    bridge: MCPBridge,
    traveler_text: str,
    intent_runner: IntentAgentRunner | None,
) -> dict[str, Any]:
    """The full SS3.3 sequence for an already-opened case, returning the
    verdict dict (schemas.Verdict shape). All MCP writes (update_case,
    assign_team, escalate) happen here before returning.
    """
    pnr = case["pnr"]
    issue_type = case["issue_type"]
    booking = await bridge.call("get_booking", pnr=pnr)

    risk_signal = score_risk(booking)

    runner = intent_runner or IntentAgentRunner()
    intent_result, policy_result = await asyncio.gather(
        runner.classify(traveler_text, issue_type),
        run_policy_agent(issue_type, booking, traveler_text),
    )

    effective_issue_type = issue_type
    if (
        intent_result.confidence >= INTENT_OVERRIDE_CONFIDENCE
        and intent_result.issue_type != issue_type
        and intent_result.issue_type != "abuse_signal"
    ):
        # A confident, non-abuse reclassification changes which policy
        # branch governs (e.g. Assistant said "refund", Intent Agent says
        # this is actually a "change") — re-run Policy Agent against it.
        effective_issue_type = intent_result.issue_type
        policy_result = await run_policy_agent(effective_issue_type, booking, traveler_text)

    abuse_flag = risk_signal.abuse_flag or intent_result.issue_type == "abuse_signal"

    verdict, assigned_team = decide_verdict(policy_result, risk_signal, abuse_flag)

    reasoning = policy_result.reason
    if abuse_flag and "abuse" not in reasoning.lower():
        flag_text = ", ".join(risk_signal.flags) or "elevated refund/return pattern"
        reasoning += f" Risk signals indicate possible abuse ({flag_text}) — escalating for review rather than deciding automatically."

    justification = {
        "policy_clause": policy_result.policy_clause,
        "policy_text": policy_result.policy_text,
        "signals": {
            "issue_type": effective_issue_type,
            "intent_confidence": intent_result.confidence,
            "fare_class": booking.get("fare_class"),
            "price_inr": booking.get("price_inr"),
            "delay_minutes": booking.get("delay_minutes"),
            "risk_score": risk_signal.risk_score,
            "abuse_flag": abuse_flag,
        },
        "reasoning": reasoning,
    }

    await bridge.call(
        "update_case",
        case_id=case["case_id"],
        verdict=verdict,
        justification=justification,
        status="resolved" if verdict == "auto_resolve" else None,
    )

    if verdict in ("route", "escalate"):
        await bridge.call("assign_team", case_id=case["case_id"], team=assigned_team)

    dossier_text = None
    if verdict == "escalate":
        dossier_text = build_dossier(case=case, booking=booking, justification=justification, traveler_text=traveler_text)
        await bridge.call("escalate", case_id=case["case_id"], dossier=dossier_text)
        logger.info(
            "case_escalated case_id=%s pnr=%s reason=%s",
            case["case_id"],
            pnr,
            redact_pii(reasoning),
        )

    final_case = await bridge.call("get_status", case_id=case["case_id"])

    return {
        "case_id": case["case_id"],
        "pnr": pnr,
        "issue_type": effective_issue_type,
        "verdict": verdict,
        "justification": justification,
        "assigned_team": final_case.get("assigned_team"),
        "dossier": final_case.get("dossier"),
        "created_at": final_case.get("updated_at", _now_iso()),
    }
