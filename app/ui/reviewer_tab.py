"""Reviewer Queue tab (Epic 7) — 03_UI_UX_Design.md SS3.

Filter bar -> gr.Dataframe (row click reads the case_id straight off
evt.row_value[0], since Case ID is the table's first column) -> detail panel
rendered from the verdict JSON (justification trail + dossier + human review
audit trail, see formatting.render_case_detail) -> action buttons that write
back through the same MCP server the agents use (backend.py), so a human
approve/deny is a first-class case-store write, not a UI-only state change.
A gr.Timer polls the table every 5s in addition to the manual Refresh button,
so a new escalation from the chat tab shows up without either tab being
touched.
"""

from __future__ import annotations

from typing import Any

import gradio as gr

from app.store.case_store import VALID_TEAMS
from app.ui.backend import Backend
from app.ui.formatting import render_case_detail

STATUS_CHOICES = ["All", "open", "routed", "escalated", "resolved"]
TEAM_CHOICES = ["All", *sorted(VALID_TEAMS)]
HEADERS = ["Case ID", "PNR", "Issue", "Team", "Status"]


def _filter_cases(cases: list[dict[str, Any]], status: str, team: str, search: str) -> list[dict[str, Any]]:
    search = (search or "").strip().lower()
    out = []
    for case in cases:
        if status != "All" and case.get("status") != status:
            continue
        if team != "All" and (case.get("assigned_team") or "") != team:
            continue
        if search and search not in (case.get("pnr") or "").lower() and search not in (case.get("case_id") or "").lower():
            continue
        out.append(case)
    return out


def build_reviewer_tab(backend: Backend, demo: gr.Blocks) -> None:
    gr.Markdown("## Reviewer Queue")

    with gr.Row():
        status_filter = gr.Dropdown(STATUS_CHOICES, value="All", label="Status")
        team_filter = gr.Dropdown(TEAM_CHOICES, value="All", label="Team")
        search_box = gr.Textbox(label="Search PNR/case", placeholder="SN8804 or CASE-000123")
        refresh_btn = gr.Button("Refresh")

    case_table = gr.Dataframe(headers=HEADERS, datatype=["str"] * 5, interactive=False)
    selected_case_id = gr.State(None)

    detail_panel = gr.Markdown("_Select a case row to see its detail._")

    with gr.Row():
        note_box = gr.Textbox(label="Reviewer note (recommended for Deny, optional otherwise)", scale=3)
        reassign_dropdown = gr.Dropdown(sorted(VALID_TEAMS), label="Reassign to", scale=1)
    with gr.Row():
        approve_btn = gr.Button("Approve")
        deny_btn = gr.Button("Deny — cite policy")
        reassign_btn = gr.Button("Reassign")
        resolve_btn = gr.Button("Mark resolved")
        transcript_btn = gr.Button("View full transcript")

    action_status = gr.Markdown()
    transcript_panel = gr.Markdown(visible=False)

    timer = gr.Timer(5)

    async def refresh_table(status: str, team: str, search: str):
        cases = await backend.list_cases()
        filtered = _filter_cases(cases, status, team, search)
        rows = [
            [c["case_id"], c["pnr"], c.get("issue_type"), c.get("assigned_team") or "—", c["status"]]
            for c in filtered
        ]
        return rows

    refresh_inputs = [status_filter, team_filter, search_box]
    refresh_outputs = [case_table]
    demo.load(refresh_table, inputs=refresh_inputs, outputs=refresh_outputs)
    refresh_btn.click(refresh_table, inputs=refresh_inputs, outputs=refresh_outputs)
    status_filter.change(refresh_table, inputs=refresh_inputs, outputs=refresh_outputs)
    team_filter.change(refresh_table, inputs=refresh_inputs, outputs=refresh_outputs)
    search_box.change(refresh_table, inputs=refresh_inputs, outputs=refresh_outputs)
    timer.tick(refresh_table, inputs=refresh_inputs, outputs=refresh_outputs)

    async def render_detail(case_id: str | None) -> str:
        if not case_id:
            return "_Select a case row to see its detail._"
        case = await backend.get_case(case_id)
        booking = await backend.get_booking_safe(case.get("pnr"))
        return render_case_detail(case, booking)

    async def on_select(evt: gr.SelectData):
        row = evt.row_value
        if not row:
            return None, "_Select a case row to see its detail._", gr.update(visible=False)
        case_id = row[0]
        detail_md = await render_detail(case_id)
        return case_id, detail_md, gr.update(visible=False)

    case_table.select(on_select, inputs=None, outputs=[selected_case_id, detail_panel, transcript_panel])

    async def run_action(action_fn, case_id, *args):
        if not case_id:
            return "No case selected.", "_Select a case row to see its detail._"
        await action_fn(case_id, *args)
        detail_md = await render_detail(case_id)
        return f"{case_id} updated.", detail_md

    async def on_approve(case_id, note):
        return await run_action(backend.approve_case, case_id, note)

    async def on_deny(case_id, note):
        return await run_action(backend.deny_case, case_id, note)

    async def on_resolve(case_id, note):
        return await run_action(backend.resolve_case, case_id, note)

    async def on_reassign(case_id, note, team):
        if not team:
            return "Pick a team to reassign to.", await render_detail(case_id)
        return await run_action(backend.reassign_case, case_id, team, note)

    action_outputs = [action_status, detail_panel]
    approve_btn.click(on_approve, inputs=[selected_case_id, note_box], outputs=action_outputs).then(
        refresh_table, inputs=refresh_inputs, outputs=refresh_outputs
    )
    deny_btn.click(on_deny, inputs=[selected_case_id, note_box], outputs=action_outputs).then(
        refresh_table, inputs=refresh_inputs, outputs=refresh_outputs
    )
    resolve_btn.click(on_resolve, inputs=[selected_case_id, note_box], outputs=action_outputs).then(
        refresh_table, inputs=refresh_inputs, outputs=refresh_outputs
    )
    reassign_btn.click(
        on_reassign, inputs=[selected_case_id, note_box, reassign_dropdown], outputs=action_outputs
    ).then(refresh_table, inputs=refresh_inputs, outputs=refresh_outputs)

    async def on_view_transcript(case_id: str | None):
        if not case_id:
            return gr.update(value="No case selected.", visible=True)
        case = await backend.get_case(case_id)
        conv_id = case.get("conversation_id")
        transcript = backend.transcripts.get(conv_id)
        if not transcript:
            md = f"_No transcript available for conversation `{conv_id}` (predates this app run)._"
        else:
            lines = [f"**{'Traveler' if role == 'user' else 'ResolveAI'}:** {text}" for role, text in transcript]
            md = f"#### Transcript — {conv_id}\n\n" + "\n\n".join(lines)
        return gr.update(value=md, visible=True)

    transcript_btn.click(on_view_transcript, inputs=[selected_case_id], outputs=[transcript_panel])
