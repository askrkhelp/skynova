"""ResolveAI Booking & Case MCP server (FastMCP).

Exposes the 6 tools from 01_Architecture_and_Design.md SS3.4, plus a 7th,
`list_cases`, added in Epic 7: the Reviewer Queue tab (03_UI_UX_Design.md
SS3, "Queue table load: MCP.list_cases(filter)") needs to read every case in
the store, which none of the original 6 tools expose, and it must do so
through this same server rather than reading data/cases.json directly — the
CLAUDE.md non-negotiable is "never a second implementation of booking/case
logic", and the UI is now a third MCP client alongside the Assistant Agent
and Triage Orchestrator. Filtering (status/team/PNR search) is done in the
UI layer over the full list rather than as tool arguments, since the
Reviewer Queue's filters change per keystroke/dropdown and the case count is
small enough that server-side filtering would add complexity for no real
benefit.

Both the Assistant Agent (Epic 4) and the Triage Orchestrator (Epic 5) connect to
this one server as independent MCP clients — this module is the single
implementation of booking/case logic; nothing else should duplicate it.

`build_server` is a factory (rather than a bare module-level instance) so
tests can hand it isolated store/booking instances instead of touching the
real data/cases.json.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from app.mcp_server.bookings import BookingLookup, BookingNotFoundError
from app.store import CaseNotFoundError, CaseStore, get_case_store


def build_server(
    cases: CaseStore | None = None,
    bookings: BookingLookup | None = None,
) -> FastMCP:
    cases = cases if cases is not None else get_case_store()
    bookings = bookings if bookings is not None else BookingLookup()

    mcp: FastMCP = FastMCP("ResolveAI Booking & Case Server")

    @mcp.tool
    def get_booking(pnr: str) -> dict[str, Any]:
        """Fetch a booking record by PNR."""
        try:
            return bookings.get(pnr)
        except BookingNotFoundError:
            raise ToolError(f"No booking found for PNR {pnr!r}") from None

    @mcp.tool
    def create_case(pnr: str, issue_type: str, summary: str, conversation_id: str) -> dict[str, Any]:
        """Open a new case for a booking issue that needs triage."""
        return cases.create_case(
            pnr=pnr, issue_type=issue_type, summary=summary, conversation_id=conversation_id
        )

    @mcp.tool
    def update_case(
        case_id: str,
        status: str | None = None,
        verdict: str | None = None,
        justification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Progress a case's status/verdict/justification."""
        try:
            return cases.update_case(case_id, status=status, verdict=verdict, justification=justification)
        except CaseNotFoundError:
            raise ToolError(f"No case found for case_id {case_id!r}") from None
        except ValueError as exc:
            raise ToolError(str(exc)) from None

    @mcp.tool
    def assign_team(case_id: str, team: str) -> dict[str, Any]:
        """Route a case to a specialist team (Refunds / Rebooking / Baggage / Special Assistance)."""
        try:
            return cases.assign_team(case_id, team=team)
        except CaseNotFoundError:
            raise ToolError(f"No case found for case_id {case_id!r}") from None
        except ValueError as exc:
            raise ToolError(str(exc)) from None

    @mcp.tool
    def escalate(case_id: str, dossier: str) -> dict[str, Any]:
        """Flag a case for human review with an auto-written dossier."""
        try:
            return cases.escalate(case_id, dossier=dossier)
        except CaseNotFoundError:
            raise ToolError(f"No case found for case_id {case_id!r}") from None

    @mcp.tool
    def get_status(case_id: str) -> dict[str, Any]:
        """Poll a case's current status/verdict/team."""
        try:
            return cases.get_case(case_id)
        except CaseNotFoundError:
            raise ToolError(f"No case found for case_id {case_id!r}") from None

    @mcp.tool
    def list_cases() -> dict[str, Any]:
        """List every case in the store, newest first (for the Reviewer Queue)."""
        all_cases = sorted(cases.list_cases(), key=lambda c: c.get("created_at") or "", reverse=True)
        return {"count": len(all_cases), "cases": all_cases}

    return mcp


mcp = build_server()

if __name__ == "__main__":
    mcp.run()
