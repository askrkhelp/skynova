"""AssistantSession — runs the Assistant Agent for one conversation.

Owns the ADK Runner + InMemorySessionService and the SS4.3 session schema
(conversation_id, pnr_in_focus, passenger_in_focus, last_leg,
open_case_ids, turn_history, last_intent). The Assistant Agent's
after_agent_callback (assistant_agent.py) does the actual per-turn state
updates; this class just owns the session lifecycle and exposes a plain
`send(text)` call for the UI (Epic 7) and eval harness (Epic 8) to use
without touching ADK internals directly.

Guardrails (Epic 6, SS3.6) live here rather than deeper in the ADK agent
because they all need to fall back through the Runner/session, which only
this class has access to:
- Input validation (app/guardrails/input_validation.py) sanitizes the raw
  text before it ever becomes a Content message or a tool argument.
- The wall-clock half of the step/cost cap wraps each turn in
  asyncio.wait_for; the tool-call half raises CapTripped from inside the
  agent (assistant_agent.py's before_tool_callback) and is caught here
  alongside the timeout — both fall back to the same guardrail escalation
  (app/guardrails/caps.py) rather than hanging or surfacing an error.
- The anti-hallucination check (app/guardrails/hallucination_check.py) runs
  after every turn against that turn's retrieved chunks (stashed by
  tools.py's search_policy); a failed check regenerates the turn once, then
  escalates if it still fails.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from app.agents.assistant_agent import OUTPUT_KEY, build_assistant_agent
from app.agents.mcp_client import MCPBridge
from app.agents.schemas import AssistantTurnOutput
from app.guardrails.caps import (
    ASSISTANT_WALL_CLOCK_CAP_S,
    CapTripped,
    open_guardrail_escalation_case,
)
from app.guardrails.hallucination_check import verify_numeric_claims
from app.guardrails.input_validation import sanitize_input
from app.guardrails.pii_redaction import redact_pii
from app.mcp_server.server import build_server

APP_NAME = "resolveai_assistant"
logger = logging.getLogger("resolveai.guardrails")


def _initial_state(conversation_id: str) -> dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "pnr_in_focus": None,
        "passenger_in_focus": None,
        "last_leg": None,
        "open_case_ids": [],
        "turn_history": [],
        "last_intent": None,
    }


class AssistantSession:
    def __init__(
        self,
        server: Any | None = None,
        bridge: MCPBridge | None = None,
        user_id: str = "traveler",
        conversation_id: str | None = None,
    ):
        self._server = server if server is not None else build_server()
        self._bridge = bridge if bridge is not None else MCPBridge(self._server)
        self._agent = build_assistant_agent(self._bridge)
        self._session_service = InMemorySessionService()
        self._runner = Runner(agent=self._agent, app_name=APP_NAME, session_service=self._session_service)
        self.user_id = user_id
        self.conversation_id = conversation_id or f"conv-{uuid.uuid4().hex[:8]}"
        self._started = False

    async def _ensure_session(self) -> None:
        if self._started:
            return
        await self._session_service.create_session(
            app_name=APP_NAME,
            user_id=self.user_id,
            session_id=self.conversation_id,
            state=_initial_state(self.conversation_id),
        )
        self._started = True

    async def send(self, text: str) -> dict[str, Any]:
        """Runs one turn (subject to the guardrails above) and returns the
        turn's AssistantTurnOutput as a dict.

        Re-validated through AssistantTurnOutput rather than returned as the
        raw parsed model JSON: the model's structured-output mode is free to
        omit a field that's at its default (e.g. case_id when no case was
        opened), so the raw dict from session state can be missing keys a
        caller expects to always be present. Round-tripping through the
        pydantic model fills in every declared default.
        """
        await self._ensure_session()
        sanitized = sanitize_input(text)
        logger.info(
            "assistant_turn conversation_id=%s injection_detected=%s text=%s",
            self.conversation_id,
            sanitized.injection_detected,
            redact_pii(sanitized.text),
        )

        result = await self._run_turn_capped(sanitized.text)
        if result is None:
            return await self._escalate_turn("guardrail cap tripped")

        chunks = await self._read_turn_chunks()
        ok, mismatches = verify_numeric_claims(result.get("reply", ""), chunks)
        if not ok:
            result = await self._run_turn_capped(sanitized.text)
            if result is None:
                return await self._escalate_turn("guardrail cap tripped during regeneration")
            chunks = await self._read_turn_chunks()
            ok, mismatches = verify_numeric_claims(result.get("reply", ""), chunks)
            if not ok:
                return await self._escalate_turn(
                    f"anti-hallucination check failed twice; unverified numeric claims {mismatches}"
                )

        return result

    async def _run_turn_capped(self, text: str) -> dict[str, Any] | None:
        """Runs one raw agent turn under the wall-clock cap. Returns None
        (rather than raising) on a cap trip, so `send` can fall back to
        escalation uniformly for both cap halves.
        """
        try:
            return await asyncio.wait_for(self._run_turn(text), timeout=ASSISTANT_WALL_CLOCK_CAP_S)
        except (asyncio.TimeoutError, CapTripped) as exc:
            logger.warning("assistant_cap_tripped conversation_id=%s reason=%s", self.conversation_id, exc)
            return None

    async def _run_turn(self, text: str) -> dict[str, Any]:
        message = genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=text)])

        async for _event in self._runner.run_async(
            user_id=self.user_id,
            session_id=self.conversation_id,
            new_message=message,
        ):
            pass

        session = await self._session_service.get_session(
            app_name=APP_NAME, user_id=self.user_id, session_id=self.conversation_id
        )
        raw = session.state.get(OUTPUT_KEY) or {}
        return AssistantTurnOutput.model_validate(raw).model_dump()

    async def _read_turn_chunks(self) -> list[dict[str, Any]]:
        """This turn's search_policy/get_booking/open_case results, stashed
        by tools.py into session state. Not cleared here — the Assistant
        Agent's before_agent_callback (assistant_agent.py) resets
        `_guardrail_chunks` to [] at the *start* of every real turn, since
        writes from out here (see `_apply_state_delta`) are the only way to
        persist a change outside a callback, and clearing "the old way" is
        simpler than the delta dance for a value nothing else reads across
        turns.
        """
        session = await self._session_service.get_session(
            app_name=APP_NAME, user_id=self.user_id, session_id=self.conversation_id
        )
        return list(session.state.get("_guardrail_chunks") or [])

    async def _apply_state_delta(self, delta: dict[str, Any]) -> None:
        """Persists a state change from outside the ADK callback machinery.

        `session_service.get_session()` always returns a deep copy (see
        InMemorySessionService._get_session_impl) — mutating `.state` on it
        is a no-op against storage. `append_event` with an EventActions
        state_delta is the supported way to write state from outside a
        running agent invocation.
        """
        session = await self._session_service.get_session(
            app_name=APP_NAME, user_id=self.user_id, session_id=self.conversation_id
        )
        event = Event(author="guardrail", actions=EventActions(state_delta=delta))
        await self._session_service.append_event(session, event)

    async def _escalate_turn(self, reason: str) -> dict[str, Any]:
        """The guardrail fallback shared by both cap halves and the
        anti-hallucination check: open (or is-already-open, doesn't matter —
        this always opens a fresh one, since a cap trip means we don't
        reliably know if open_case already ran this turn) and escalate a
        case, then update session state and return an AssistantTurnOutput-
        shaped reply exactly as a normal turn would.
        """
        state = await self.get_state()
        case = await open_guardrail_escalation_case(
            self._bridge,
            pnr=state.get("pnr_in_focus"),
            issue_type=state.get("last_intent"),
            conversation_id=self.conversation_id,
            reason=reason,
        )
        case_id = case["case_id"]

        open_ids = list(state.get("open_case_ids") or [])
        if case_id not in open_ids:
            open_ids.append(case_id)

        reply = (
            "This is taking longer than expected, so I've opened a case "
            f"({case_id}) for a specialist to review and get back to you."
        )
        history = list(state.get("turn_history") or [])
        history.append({"role": "assistant", "text": reply})

        await self._apply_state_delta({"open_case_ids": open_ids, "turn_history": history[-6:]})

        result = AssistantTurnOutput.model_validate(
            {
                "extracted": {
                    "issue_type": state.get("last_intent") or "unclear",
                    "pnr": state.get("pnr_in_focus"),
                },
                "needs_clarification": False,
                "clarifying_question": None,
                "reply": reply,
                "case_id": case_id,
                "citations": [],
            }
        ).model_dump()
        return result

    async def get_state(self) -> dict[str, Any]:
        await self._ensure_session()
        session = await self._session_service.get_session(
            app_name=APP_NAME, user_id=self.user_id, session_id=self.conversation_id
        )
        return dict(session.state)
