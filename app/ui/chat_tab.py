"""Traveler Chat tab (Epic 7) — 03_UI_UX_Design.md SS2.

Each browser session gets its own AssistantSession + conversation_id (created
on `demo.load`), all sharing the one process-wide MCP server/case store in
backend.py — so a case this tab opens is immediately visible in the Reviewer
Queue tab without an app restart. No separate UI for a clarifying question or
a guardrail trip: both surface as an ordinary assistant chat turn, per
03_UI_UX_Design.md's "no dead ends" rule — AssistantSession.send already
guarantees that (guardrail trips fall back to an escalation reply rather than
raising), so this tab just renders whatever `reply` comes back.
"""

from __future__ import annotations

import gradio as gr

from app.agents.session import AssistantSession
from app.ui.backend import Backend
from app.ui.formatting import (
    render_case_banner,
    render_context_panel,
    render_sources_panel,
    style_citations,
)

WELCOME = "Hi! How can I help with your SkyNova booking today?"


def build_chat_tab(backend: Backend, demo: gr.Blocks) -> None:
    session_state = gr.State()
    sources_state = gr.State([])

    gr.Markdown("## ResolveAI · SkyNova Travel Support")
    banner = gr.Markdown(visible=False)

    with gr.Row():
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(height=480, show_label=False)
            with gr.Row():
                msg = gr.Textbox(
                    placeholder="Type your message...", show_label=False, scale=4, container=False
                )
                send_btn = gr.Button("Send", scale=1)
        with gr.Column(scale=1):
            context_panel = gr.Markdown(render_context_panel({}, None))
            sources_panel = gr.Markdown(render_sources_panel([]))

    async def on_load():
        session = backend.new_chat_session()
        backend.append_transcript(session.conversation_id, "assistant", WELCOME)
        history = [{"role": "assistant", "content": WELCOME}]
        return (
            session,
            [],
            history,
            render_context_panel({}, None),
            render_sources_panel([]),
            gr.update(value="", visible=False),
        )

    demo.load(
        on_load,
        outputs=[session_state, sources_state, chatbot, context_panel, sources_panel, banner],
    )

    async def on_send(message: str, history: list, session: AssistantSession, sources: list):
        message = (message or "").strip()
        if not message or session is None:
            return gr.update(), history, sources, gr.update(), gr.update(), gr.update()

        history = history + [{"role": "user", "content": message}]
        result = await session.send(message)
        backend.append_transcript(session.conversation_id, "user", message)
        backend.append_transcript(session.conversation_id, "assistant", result.get("reply", ""))

        styled_reply = style_citations(result.get("reply", ""), result.get("citations") or [])
        history = history + [{"role": "assistant", "content": styled_reply}]

        sources = list(sources)
        for source_id in result.get("citations") or []:
            if source_id not in sources:
                sources.append(source_id)

        state = await session.get_state()
        booking = await backend.get_booking_safe(state.get("pnr_in_focus"))
        context_md = render_context_panel(state, booking)
        sources_md = render_sources_panel(sources)

        banner_update = gr.update(value="", visible=False)
        case_id = result.get("case_id")
        if case_id:
            case = await backend.get_case(case_id)
            banner_update = gr.update(value=render_case_banner(case), visible=True)

        return "", history, sources, context_md, sources_md, banner_update

    send_inputs = [msg, chatbot, session_state, sources_state]
    send_outputs = [msg, chatbot, sources_state, context_panel, sources_panel, banner]
    send_btn.click(on_send, inputs=send_inputs, outputs=send_outputs)
    msg.submit(on_send, inputs=send_inputs, outputs=send_outputs)
