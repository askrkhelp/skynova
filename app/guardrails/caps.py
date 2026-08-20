"""Step/cost cap guardrails — bounded tool-call count and wall-clock time
for the Assistant Agent loop (Epic 4) and the Triage Orchestrator (Epic 5).

Per 01_Architecture_and_Design.md SS3.6: "Assistant loop: max 4 tool calls /
turn, 12s wall clock; Orchestrator: max 1 pass per specialist, 20s wall
clock — both cap on timeout by escalating rather than hanging." The
Orchestrator's "1 pass per specialist" half is already structurally true
(app/agents/triage_orchestrator.py calls each specialist exactly once, with
no retry loop) and needs no extra enforcement here; only the wall-clock
half needs an explicit guard, applied in triage_orchestrator.run_triage.

ASSISTANT_WALL_CLOCK_CAP_S is raised above the doc's stated 12s default:
tools.py's open_case runs run_triage (the Orchestrator, capped at
ORCHESTRATOR_WALL_CLOCK_CAP_S) synchronously *inside* the Assistant's own
turn, so the outer cap has to comfortably contain the inner one plus the
Assistant's own get_booking/open_case tool-call round trips and its final
reply synthesis — 12s < 20s made the outer cap trip before the Orchestrator
could ever finish on any decision-flow turn (get_booking + open_case in one
turn), regardless of latency. 35s leaves ~15s of headroom over the
Orchestrator's 20s budget for that surrounding work.

`CapTripped` is the single signal the Assistant Agent's tool-call counter
raises on a breach; callers catch it alongside `asyncio.TimeoutError` (the
wall-clock half) and fall back to `open_guardrail_escalation_case` /
`escalate_case_for_guardrail` below instead of letting the turn hang,
error, or surface whatever partial result exists — the SS3.6 non-negotiable
that a guardrail trip is never a dead end.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from app.guardrails.pii_redaction import redact_pii

if TYPE_CHECKING:
    from app.agents.mcp_client import MCPBridge

logger = logging.getLogger("resolveai.guardrails")

ASSISTANT_MAX_TOOL_CALLS = 4
ASSISTANT_WALL_CLOCK_CAP_S = 35.0

ORCHESTRATOR_WALL_CLOCK_CAP_S = 20.0

_TOOL_CALL_COUNT_KEY = "_guardrail_tool_call_count"


class CapTripped(Exception):
    """Raised when a step or wall-clock cap is exceeded."""


class _StateLike(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...
    def __setitem__(self, key: str, value: Any) -> None: ...


def reset_tool_call_counter(state: _StateLike) -> None:
    state[_TOOL_CALL_COUNT_KEY] = 0


def count_tool_call(state: _StateLike, max_calls: int = ASSISTANT_MAX_TOOL_CALLS) -> None:
    """`before_tool_callback` body: increments the per-turn tool-call
    counter and raises CapTripped once a call would exceed max_calls. Reset
    once per turn via `reset_tool_call_counter` in a `before_agent_callback`.
    """
    count = (state.get(_TOOL_CALL_COUNT_KEY) or 0) + 1
    state[_TOOL_CALL_COUNT_KEY] = count
    if count > max_calls:
        raise CapTripped(f"exceeded max tool calls per turn ({max_calls})")


def _guardrail_justification(issue_type: str | None, reason: str) -> dict[str, Any]:
    return {
        "policy_clause": "guardrail/human_review_required",
        "policy_text": "N/A - guardrail escalation, not a policy-grounded verdict.",
        "signals": {
            "issue_type": issue_type or "unclear",
            "intent_confidence": 0.0,
            "risk_score": 0.0,
            "abuse_flag": False,
        },
        "reasoning": reason,
    }


async def escalate_case_for_guardrail(
    bridge: MCPBridge,
    *,
    case_id: str,
    reason: str,
    traveler_text: str = "",
    issue_type: str | None = None,
) -> dict[str, Any]:
    """Marks an already-open case escalated directly, bypassing the Triage
    Orchestrator — used when a guardrail trips after a case exists (the
    Orchestrator's own wall-clock cap; app/agents/triage_orchestrator.py).
    """
    justification = _guardrail_justification(issue_type, reason)
    await bridge.call(
        "update_case",
        case_id=case_id,
        verdict="escalate",
        justification=justification,
        status="escalated",
    )
    dossier = (
        f"Case {case_id} — guardrail escalation\n"
        f"Reason: {reason}\n"
        f'Traveler\'s original message: "{redact_pii(traveler_text)}"'
    )
    await bridge.call("escalate", case_id=case_id, dossier=dossier)
    logger.warning("guardrail_escalation case_id=%s reason=%s", case_id, reason)
    return await bridge.call("get_status", case_id=case_id)


async def open_guardrail_escalation_case(
    bridge: MCPBridge,
    *,
    pnr: str | None,
    issue_type: str | None,
    conversation_id: str,
    reason: str,
    traveler_text: str = "",
) -> dict[str, Any]:
    """Opens a new case and marks it escalated in one step — used when a
    guardrail trips before any case exists (the Assistant Agent's own
    tool-call/wall-clock cap; app/agents/session.py), so the trip still
    produces a real case rather than a dropped request.
    """
    case = await bridge.call(
        "create_case",
        pnr=pnr or "UNKNOWN",
        issue_type=issue_type or "unclear",
        summary=f"Guardrail escalation: {reason}",
        conversation_id=conversation_id,
    )
    return await escalate_case_for_guardrail(
        bridge,
        case_id=case["case_id"],
        reason=reason,
        traveler_text=traveler_text,
        issue_type=issue_type,
    )
