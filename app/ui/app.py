"""ResolveAI Gradio app (Epic 7) — one Blocks app, two tabs, sharing the same
in-process backend (app/ui/backend.py), per 03_UI_UX_Design.md SS1/SS4.
"""

from __future__ import annotations

import os

import gradio as gr

from app.ui.backend import Backend
from app.ui.chat_tab import build_chat_tab
from app.ui.reviewer_tab import build_reviewer_tab


def build_app(backend: Backend | None = None) -> gr.Blocks:
    backend = backend or Backend()
    with gr.Blocks(title="ResolveAI · SkyNova Travel Support") as demo:
        with gr.Tab("Traveler Chat"):
            build_chat_tab(backend, demo)
        with gr.Tab("Reviewer Queue"):
            build_reviewer_tab(backend, demo)
    return demo


demo = build_app()

if __name__ == "__main__":
    # Cloud Run injects PORT and requires binding 0.0.0.0, not 127.0.0.1.
    demo.queue().launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 8080)))
