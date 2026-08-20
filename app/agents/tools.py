"""ADK tool functions for the Assistant Agent.

Four tools per 01_Architecture_and_Design.md SS3.2: search_policy (Epic 2,
called in-process), get_booking / open_case / get_status (Epic 3, called as
MCP client calls through an MCPBridge). Built as a factory (build_tools)
bound to one MCPBridge, not module-level instances, so tests can point them
at an isolated MCP server the same way build_server() is isolated per test.

All parameters are required with no default values (ADK's automatic
function-calling schema is built from the signature; optional filters use
an empty-string sentinel for "no filter" instead of a Python default) per
the ADK tool-writing rules in google-agents-cli-adk-code.

open_case additionally runs the Triage Orchestrator (Epic 5) synchronously
within the same tool call before returning, rather than exposing a second
"run_triage" tool the model would have to remember to call with correctly
re-supplied structured fields — the case_id, pnr, and issue_type it needs
are already on the case this call just created, and the orchestrator's own
get_booking call (SS3.3's sequence diagram) re-fetches the booking rather
than trusting a value threaded through the model. This keeps the SS3.2 step
5 handoff ("open_case, then invoke the Triage Orchestrator... relay the
verdict") as one deterministic tool call instead of two model-chosen ones
(run_triage's own wall-clock cap, per app/guardrails/caps.py, already
covers this call — see triage_orchestrator.py).

search_policy also stashes each turn's retrieved chunks into
tool_context.state — app/guardrails/hallucination_check.py's post-hoc
numeric-claim check (wired in app/agents/session.py) reads them back after
the turn to verify the reply's Rs/kg/hour figures against what was actually
retrieved.
"""

from __future__ import annotations

from typing import Any

from fastmcp.exceptions import ToolError as MCPToolError
from google.adk.tools import ToolContext

from app.agents.mcp_client import MCPBridge
from app.agents.triage_orchestrator import run_triage
from app.rag.search import search_policy as _search_policy


def build_tools(bridge: MCPBridge) -> list[Any]:
    async def search_policy(query: str, fare_class: str, doc_type: str, tool_context: ToolContext) -> dict:
        """Search SkyNova's KB and policy/fare-rule documents for grounded facts.

        Use this for any price/fee/allowance/refund/policy claim — never state
        such a fact without having retrieved it here first. If nothing relevant
        comes back, say so to the traveler instead of guessing.

        Args:
          query: free-text description of what to look up.
          fare_class: "Saver", "Flex", or "Business" to scope the search to that
            fare's rules (fare-agnostic policy docs are always included too);
            pass "" if the question isn't fare-specific.
          doc_type: "kb", "fare_rule", or "policy" to scope to one doc type;
            pass "" to search all of them.
        """
        results = _search_policy(
            query,
            fare_class=fare_class or None,
            doc_type=doc_type or None,
            k=4,
        )
        turn_chunks = list(tool_context.state.get("_guardrail_chunks") or [])
        turn_chunks.extend(results)
        tool_context.state["_guardrail_chunks"] = turn_chunks
        return {"count": len(results), "results": results}

    async def get_booking(pnr: str, tool_context: ToolContext) -> dict:
        """Look up a booking record by PNR: fare class, status, dates, baggage,
        delay minutes, and account/risk fields.

        Args:
          pnr: the booking reference, e.g. "SN8804".
        """
        try:
            booking = await bridge.call("get_booking", pnr=pnr)
            # A reply can restate a booking-derived figure (e.g. "your delay
            # was 300 minutes") rather than a policy citation — record it so
            # the anti-hallucination check doesn't flag it as ungrounded.
            turn_chunks = list(tool_context.state.get("_guardrail_chunks") or [])
            turn_chunks.append({"source_id": f"booking:{pnr}", "text": str(booking)})
            tool_context.state["_guardrail_chunks"] = turn_chunks
            return {"found": True, "booking": booking}
        except MCPToolError as exc:
            return {"found": False, "error": str(exc)}

    async def open_case(
        pnr: str, issue_type: str, summary: str, traveler_message: str, tool_context: ToolContext
    ) -> dict:
        """Open a case for a booking issue that requires a decision: refund,
        change, delay_compensation, baggage_claim, or special_assistance.

        This call opens the case AND immediately runs the Triage Orchestrator
        (Intent/Policy/Risk specialists + the deterministic verdict rule
        table) to get a verdict — you do not decide the outcome yourself, the
        table does, and you never see this before it's already decided.
        Relay exactly what's returned (verdict, policy_text, reasoning) to the
        traveler in plain language along with the case id — do not add,
        soften, or invent anything beyond what this call returns.

        Args:
          pnr: booking reference this case is about.
          issue_type: one of refund, change, delay_compensation, baggage_claim,
            special_assistance.
          summary: a short free-text summary of the traveler's request, for the
            case record.
          traveler_message: the traveler's current message, copied verbatim —
            the Orchestrator's specialists (sarcasm/abuse detection, dossier)
            need the original wording, not your summary of it.
        """
        conversation_id = tool_context.state.get("conversation_id") or "conv-unknown"
        case = await bridge.call(
            "create_case",
            pnr=pnr,
            issue_type=issue_type,
            summary=summary,
            conversation_id=conversation_id,
        )
        tool_context.state["_last_case_id"] = case["case_id"]

        verdict = await run_triage(case=case, bridge=bridge, traveler_text=traveler_message)
        justification = verdict["justification"]

        # The reply the model relays from this verdict (fees, compensation
        # amounts, etc.) is grounded in the Orchestrator's own Policy Agent
        # retrieval, not a search_policy call the model made itself — record
        # it as a retrieved chunk too so the anti-hallucination check
        # (app/guardrails/hallucination_check.py, wired in session.py) can
        # verify those numbers against it instead of flagging them as
        # ungrounded.
        turn_chunks = list(tool_context.state.get("_guardrail_chunks") or [])
        turn_chunks.append(
            {
                "source_id": justification.get("policy_clause"),
                "text": justification.get("policy_text") or justification.get("reasoning") or "",
            }
        )
        tool_context.state["_guardrail_chunks"] = turn_chunks

        return {
            "case_id": case["case_id"],
            "verdict": verdict["verdict"],
            "assigned_team": verdict["assigned_team"],
            "policy_clause": justification["policy_clause"],
            "policy_text": justification["policy_text"],
            "reasoning": justification["reasoning"],
        }

    async def get_status(case_id: str) -> dict:
        """Check the current status/verdict/team of a previously opened case.

        Args:
          case_id: case id returned from open_case, e.g. "CASE-000123".
        """
        try:
            case = await bridge.call("get_status", case_id=case_id)
            return {"found": True, "case": case}
        except MCPToolError as exc:
            return {"found": False, "error": str(exc)}

    return [search_policy, get_booking, open_case, get_status]
