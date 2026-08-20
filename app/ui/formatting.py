"""Markdown rendering helpers for the Gradio UI (Epic 7).

Kept separate from chat_tab.py/reviewer_tab.py so both tabs render the same
session-context/citation/case-detail markdown the same way, per
03_UI_UX_Design.md's component tables for both tabs.
"""

from __future__ import annotations

from typing import Any

VERDICT_LABELS = {
    "auto_resolve": "Auto-resolved ✅",
    "route": "Routed →",
    "escalate": "Escalated to a human reviewer ⚠️",
}


def style_citations(text: str, citations: list[str]) -> str:
    """Turns the agent's inline `[source_id]` citations into styled chips.

    Only replaces tokens that are actually in `citations` (the turn's real
    source_ids), not any bracketed text that happens to appear in the reply.
    """
    styled = text
    for source_id in citations:
        token = f"[{source_id}]"
        if token in styled:
            styled = styled.replace(token, f" `\U0001f4ce {source_id}` ")
    return styled


def render_context_panel(state: dict[str, Any], booking: dict[str, Any] | None) -> str:
    booking = booking or {}
    pnr = state.get("pnr_in_focus") or "—"
    passenger = booking.get("passenger") or state.get("passenger_in_focus") or "—"
    fare_class = booking.get("fare_class") or "—"
    flight = booking.get("flight_no") or state.get("last_leg") or "—"
    open_cases = state.get("open_case_ids") or []
    open_case = ", ".join(open_cases) if open_cases else "—"
    return (
        "### Session context\n"
        f"- **PNR:** {pnr}\n"
        f"- **Passenger:** {passenger}\n"
        f"- **Fare class:** {fare_class}\n"
        f"- **Flight:** {flight}\n"
        f"- **Open case:** {open_case}\n"
    )


def render_sources_panel(sources: list[str]) -> str:
    if not sources:
        return "### Sources cited\n_None yet._"
    lines = "\n".join(f"- {source_id}" for source_id in sources)
    return f"### Sources cited\n{lines}"


def render_case_banner(case: dict[str, Any]) -> str:
    verdict = case.get("verdict")
    team = case.get("assigned_team")
    if verdict == "route" and team:
        label = f"Routed to {team} →"
    else:
        label = VERDICT_LABELS.get(verdict, verdict or "pending")
    follow_up = " A specialist will follow up." if verdict == "escalate" else ""
    reasoning = ((case.get("justification") or {}).get("reasoning")) or ""
    return f"**Case {case['case_id']} opened — {label}.**{follow_up} {reasoning}".strip()


def render_case_detail(case: dict[str, Any], booking: dict[str, Any] | None) -> str:
    lines = [f"### {case['case_id']} — {case.get('issue_type')}"]

    if booking:
        lines.append(
            f"**Booking:** {booking.get('pnr')} · {booking.get('passenger')} · "
            f"{booking.get('fare_class')} · {booking.get('flight_no')} · "
            f"₹{booking.get('price_inr')}"
        )

    lines.append(
        f"**Status:** {case.get('status')} &nbsp;|&nbsp; **Verdict:** {case.get('verdict') or '—'} "
        f"&nbsp;|&nbsp; **Team:** {case.get('assigned_team') or '—'}"
    )
    lines.append(f"**Issue:** {case.get('summary')}")

    justification = case.get("justification") or {}
    if justification.get("policy_clause") or justification.get("reasoning"):
        lines.append("\n#### Justification trail")
        lines.append(
            f"- **Policy:** `{justification.get('policy_clause')}` — "
            f"\"{justification.get('policy_text')}\""
        )
        signals = justification.get("signals") or {}
        if signals:
            sig_str = ", ".join(f"{key}={value}" for key, value in signals.items())
            lines.append(f"- **Signals:** {sig_str}")
        lines.append(f"- **Reasoning:** {justification.get('reasoning')}")

    dossier = case.get("dossier")
    if dossier:
        quoted = dossier.replace("\n", "\n> ")
        lines.append("\n#### Dossier (auto-written)")
        lines.append(f"> {quoted}")

    human_actions = justification.get("human_actions") or []
    if human_actions:
        lines.append("\n#### Human review audit trail")
        for entry in human_actions:
            lines.append(
                f"- `{entry.get('at')}` **{entry.get('actor')}** {entry.get('action')}: {entry.get('note')}"
            )

    return "\n\n".join(lines)
