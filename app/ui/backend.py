"""Shared backend singleton for the Gradio UI (Epic 7).

One process-wide MCP server/bridge/case-store/booking-lookup so both tabs
operate on the same Booking & Case system the Assistant Agent (Epic 4) and
Triage Orchestrator (Epic 5) already talk to — this is what makes "a case
opened in the chat tab is immediately visible in the reviewer tab" true
without any extra plumbing (03_UI_UX_Design.md SS4, "single source of
truth"). Each browser tab gets its own `AssistantSession` (created lazily on
load, see chat_tab.py), but every session shares this one `server`/`bridge`.

Reviewer actions (approve/deny/reassign/resolve) write back through
`bridge.call("update_case"/"assign_team", ...)` — the same MCP path the
agents use — rather than touching `case_store` directly, so a human action
is a first-class case-store write with the same audit properties as an AI
one (03_UI_UX_Design.md SS3, "same write path the Orchestrator uses").

Audit trail: the Case schema (01_Architecture_and_Design.md SS4.2) has a
single `justification` dict, not an append-only history list — Epic 3 built
`update_case` to overwrite it (see CLAUDE.md's Epic 3 note), so a reviewer
action can't get its own top-level schema field without touching Epic 3's
contract. Instead, human actions are appended to
`justification["human_actions"]` (a list this module owns), preserving the
AI's original policy_clause/policy_text/signals/reasoning alongside every
subsequent human override — satisfying SS6's "every verdict change is an
append... not an overwrite" within the existing schema rather than changing
it.

Chat transcripts are kept here too (keyed by conversation_id), separately
from AssistantSession's own `turn_history`: that field is capped to the
last 6 entries for the agent's own prompt budget (app/agents/session.py),
too short for a human audit view, so the UI keeps its own uncapped copy for
the Reviewer tab's "View full transcript" link.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.agents.mcp_client import MCPBridge
from app.agents.session import AssistantSession
from app.mcp_server.bookings import BookingLookup
from app.mcp_server.server import build_server
from app.store import get_case_store


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Backend:
    def __init__(self) -> None:
        self.case_store = get_case_store()
        self.bookings = BookingLookup()
        self.server = build_server(cases=self.case_store, bookings=self.bookings)
        self.bridge = MCPBridge(self.server)
        self.chat_sessions: dict[str, AssistantSession] = {}
        self.transcripts: dict[str, list[tuple[str, str]]] = {}

    def new_chat_session(self) -> AssistantSession:
        session = AssistantSession(server=self.server, bridge=self.bridge)
        self.chat_sessions[session.conversation_id] = session
        self.transcripts[session.conversation_id] = []
        return session

    def append_transcript(self, conversation_id: str, role: str, text: str) -> None:
        self.transcripts.setdefault(conversation_id, []).append((role, text))

    async def get_booking_safe(self, pnr: str | None) -> dict[str, Any] | None:
        if not pnr:
            return None
        try:
            return await self.bridge.call("get_booking", pnr=pnr)
        except Exception:
            return None

    async def list_cases(self) -> list[dict[str, Any]]:
        result = await self.bridge.call("list_cases")
        return result["cases"]

    async def get_case(self, case_id: str) -> dict[str, Any]:
        return await self.bridge.call("get_status", case_id=case_id)

    async def _append_human_action(
        self,
        case_id: str,
        action: str,
        note: str,
        status: str | None,
        actor: str = "reviewer",
    ) -> dict[str, Any]:
        case = await self.bridge.call("get_status", case_id=case_id)
        justification = dict(case.get("justification") or {})
        human_actions = list(justification.get("human_actions") or [])
        human_actions.append({"action": action, "note": note or "", "actor": actor, "at": _now_iso()})
        justification["human_actions"] = human_actions
        return await self.bridge.call(
            "update_case", case_id=case_id, status=status, verdict=None, justification=justification
        )

    async def approve_case(self, case_id: str, note: str) -> dict[str, Any]:
        return await self._append_human_action(
            case_id, "approve", note or "Approved by reviewer.", status="resolved"
        )

    async def deny_case(self, case_id: str, note: str) -> dict[str, Any]:
        return await self._append_human_action(
            case_id, "deny", note or "Denied by reviewer.", status="resolved"
        )

    async def resolve_case(self, case_id: str, note: str) -> dict[str, Any]:
        return await self._append_human_action(
            case_id, "mark_resolved", note or "Marked resolved by reviewer.", status="resolved"
        )

    async def reassign_case(self, case_id: str, team: str, note: str) -> dict[str, Any]:
        await self.bridge.call("assign_team", case_id=case_id, team=team)
        return await self._append_human_action(
            case_id, "reassign", note or f"Reassigned to {team}.", status=None
        )
