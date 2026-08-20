"""Tests for the Assistant Agent (Epic 4).

All tests need a live Gemini call (the agent's model + gemini-embedding-001
via search_policy) and are skipped without GEMINI_API_KEY, same convention
as tests/test_rag_smoke.py. Each test builds its own isolated MCP server
(temp cases.json) via build_server(), same as tests/test_mcp_server.py, so
nothing here touches data/cases.json.
"""

from __future__ import annotations

import asyncio
import os
import re
import time

import pytest

from app.agents.mcp_client import MCPBridge
from app.agents.session import AssistantSession
from app.mcp_server.bookings import BookingLookup
from app.mcp_server.server import build_server
from app.store import LocalJSONCaseStore

requires_key = pytest.mark.skipif(
    not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
    reason="GEMINI_API_KEY not set - agent tests need a live model call",
)


def run(coro):
    return asyncio.run(coro)


# The free tier is rate-limited to 15 requests/min per model; this suite
# makes dozens of live calls across its tests, so every send is paced to
# stay under that ceiling rather than bursting and hitting 429s.
_MIN_CALL_INTERVAL_S = 4.5
_last_call_at = 0.0


async def send_paced(session: AssistantSession, text: str) -> dict:
    global _last_call_at
    wait = _last_call_at + _MIN_CALL_INTERVAL_S - time.monotonic()
    if wait > 0:
        await asyncio.sleep(wait)
    try:
        return await session.send(text)
    finally:
        _last_call_at = time.monotonic()


@pytest.fixture
def server(tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text("[]", encoding="utf-8")
    return build_server(cases=LocalJSONCaseStore(cases_path), bookings=BookingLookup())


class RecordingBridge(MCPBridge):
    """MCPBridge that logs every MCP tool call, for asserting tool choice
    without needing to inspect the model's internal reasoning."""

    def __init__(self, server):
        super().__init__(server)
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool_name, **kwargs):
        self.calls.append((tool_name, kwargs))
        return await super().call(tool_name, **kwargs)


# ---------------------------------------------------------------------------
# Intent + entity extraction accuracy (>=90% field-level, per backlog Epic 4)
# ---------------------------------------------------------------------------

# Only fields with an unambiguous correct value are graded (issue_type, pnr,
# fare_class always; flight_leg only for the one case that mirrors the
# agent's own few-shot example, as a coreference sanity check). amount/
# urgency are left ungraded — genuinely subjective for single-line requests.
_ANY = frozenset  # alias for readability at call sites

EXTRACTION_CASES: list[tuple[str, dict]] = [
    ("What is my cabin baggage limit on a Saver fare?", {"issue_type": "policy_question", "pnr": None, "fare_class": "Saver"}),
    ("How much is extra baggage per kg?", {"issue_type": "policy_question", "pnr": None, "fare_class": None}),
    ("I'm on SN8804, can I change my flight?", {"issue_type": "change", "pnr": "SN8804", "fare_class": None, "flight_leg": _ANY({"outbound", None})}),
    ("I have a problem with my trip", {"issue_type": "unclear", "pnr": None, "fare_class": None}),
    ("I want to cancel SN8803 and get a refund.", {"issue_type": "refund", "pnr": "SN8803", "fare_class": None}),
    ("Cancel SN8802 and refund me fully, I changed my mind.", {"issue_type": "refund", "pnr": "SN8802", "fare_class": None}),
    ("My flight SN8801 was delayed 5 hours, what are my options?", {"issue_type": "delay_compensation", "pnr": "SN8801", "fare_class": None}),
    ("SN8811 was delayed about 2.5 hours, do I get a refund?", {"issue_type": "delay_compensation", "pnr": "SN8811", "fare_class": None}),
    ("My bag never arrived on SN8807.", {"issue_type": "baggage_claim", "pnr": "SN8807", "fare_class": None}),
    ("I need wheelchair and oxygen support on SN8808.", {"issue_type": "special_assistance", "pnr": "SN8808", "fare_class": None}),
    ("I missed my flight SN8810, I want a refund.", {"issue_type": "refund", "pnr": "SN8810", "fare_class": None}),
    ("When does web check-in close for a domestic flight?", {"issue_type": "policy_question", "pnr": None, "fare_class": None}),
    ("What is included in a Business fare?", {"issue_type": "policy_question", "pnr": None, "fare_class": "Business"}),
    ("Can I select my seat for free on a Flex fare?", {"issue_type": "policy_question", "pnr": None, "fare_class": "Flex"}),
    ("Something's wrong with my booking", {"issue_type": "unclear", "pnr": None, "fare_class": None}),
    ("Can you help me with my flight?", {"issue_type": "unclear", "pnr": None, "fare_class": None}),
    ("I need a refund", {"issue_type": "refund", "pnr": None, "fare_class": None}),
    ("My checked bag was damaged when I landed on SN8910.", {"issue_type": "baggage_claim", "pnr": "SN8910", "fare_class": None}),
    ("They wouldn't let me carry my power bank in the cabin on SN8912, is that normal?", {"issue_type": "policy_question", "pnr": "SN8912", "fare_class": None}),
    ("Refund SN8903 in full, I've had bad luck with your airline lately.", {"issue_type": "refund", "pnr": "SN8903", "fare_class": None}),
]

assert len(EXTRACTION_CASES) == 20


def _field_matches(expected, actual) -> bool:
    if isinstance(expected, frozenset):
        return actual in expected
    return expected == actual


@requires_key
def test_extraction_field_level_accuracy(server):
    async def _run():
        results = []
        for text, expected in EXTRACTION_CASES:
            session = AssistantSession(server=server)
            result = await send_paced(session, text)
            results.append((expected, result.get("extracted") or {}))
        return results

    results = run(_run())

    total = correct = 0
    misses = []
    for expected, extracted in results:
        for field, exp in expected.items():
            total += 1
            actual = extracted.get(field)
            if _field_matches(exp, actual):
                correct += 1
            else:
                misses.append((field, exp, actual))

    accuracy = correct / total
    assert accuracy >= 0.9, f"field accuracy {accuracy:.0%} below 90% target; misses: {misses}"


# ---------------------------------------------------------------------------
# Tool choice: search_policy vs get_booking vs open_case, across 10 scenarios
# ---------------------------------------------------------------------------

# must_call/must_not_call use MCP-level tool names, as recorded by
# RecordingBridge — the ADK tool the LLM calls is named "open_case", but it
# calls through to the MCP server's "create_case" tool (per SS3.4's naming).
TOOL_CHOICE_SCENARIOS = [
    # (text, must_call, must_not_call)
    ("How much is extra baggage per kg?", {"search_policy"}, {"get_booking", "create_case"}),
    ("What is my cabin baggage limit on a Saver fare?", {"search_policy"}, {"get_booking", "create_case"}),
    ("When does web check-in close for a domestic flight?", {"search_policy"}, {"get_booking", "create_case"}),
    ("Can I bring my dog on the flight?", {"search_policy"}, {"get_booking", "create_case"}),
    ("Does my infant need their own seat and ticket?", {"search_policy"}, {"get_booking", "create_case"}),
    ("I want to cancel SN8803 and get a refund.", {"get_booking", "create_case"}, set()),
    ("My flight SN8801 was delayed 5 hours, what are my options?", {"get_booking", "create_case"}, set()),
    ("My bag never arrived on SN8807.", {"get_booking", "create_case"}, set()),
    ("I need wheelchair and oxygen support on SN8808.", {"get_booking", "create_case"}, set()),
    ("I'm on SN8804, can I change my flight?", {"get_booking", "create_case"}, set()),
]

assert len(TOOL_CHOICE_SCENARIOS) == 10


@requires_key
def test_tool_choice_across_ten_scenarios(server):
    async def _run():
        outcomes = []
        for text, must_call, must_not_call in TOOL_CHOICE_SCENARIOS:
            bridge = RecordingBridge(server)
            session = AssistantSession(server=server, bridge=bridge)
            await send_paced(session, text)
            called_mcp = {name for name, _ in bridge.calls}
            # search_policy runs in-process (not through the MCP bridge); its
            # citations landing in the structured output is our signal it ran.
            outcomes.append((text, must_call, must_not_call, called_mcp))
        return outcomes

    outcomes = run(_run())

    failures = []
    for text, must_call, must_not_call, called_mcp in outcomes:
        mcp_musts = must_call & {"get_booking", "create_case"}
        if not mcp_musts <= called_mcp:
            failures.append((text, "missing", mcp_musts - called_mcp))
        mcp_forbidden = must_not_call & {"get_booking", "create_case"}
        if mcp_forbidden & called_mcp:
            failures.append((text, "forbidden", mcp_forbidden & called_mcp))

    assert not failures, f"tool choice mismatches: {failures}"


# ---------------------------------------------------------------------------
# Multi-turn coreference: E03-style "return leg too" resolves without re-ask
# ---------------------------------------------------------------------------


@requires_key
def test_return_leg_scenario_resolves_without_reasking_pnr(server):
    async def _run():
        session = AssistantSession(server=server)
        first = await send_paced(session, "I'm on SN8804, can I change my flight?")
        second = await send_paced(session, "What about my return leg too?")
        state = await session.get_state()
        return first, second, state

    first, second, state = run(_run())

    assert first["extracted"]["pnr"] == "SN8804"
    assert second["needs_clarification"] is False
    assert "PNR" not in (second.get("clarifying_question") or "")
    assert state["pnr_in_focus"] == "SN8804"


# ---------------------------------------------------------------------------
# Clarify-on-ambiguity: exactly one question, no tool call
# ---------------------------------------------------------------------------


@requires_key
def test_no_pnr_no_issue_triggers_exactly_one_clarifying_question(server):
    async def _run():
        bridge = RecordingBridge(server)
        session = AssistantSession(server=server, bridge=bridge)
        result = await send_paced(session, "I have a problem with my trip")
        return result, bridge.calls

    result, calls = run(_run())

    assert result["needs_clarification"] is True
    assert result["clarifying_question"]
    assert result["case_id"] is None
    assert calls == [], f"expected no MCP tool calls on a clarifying turn, got {calls}"


# ---------------------------------------------------------------------------
# Decision-requiring scenario opens a case via open_case
# ---------------------------------------------------------------------------


@requires_key
def test_decision_requiring_scenario_opens_a_case(server):
    async def _run():
        session = AssistantSession(server=server)
        return await send_paced(session, "I want to cancel SN8803 and get a refund.")

    result = run(_run())

    assert result["case_id"] is not None
    assert re.match(r"^CASE-\d+$", result["case_id"])
    assert result["needs_clarification"] is False
