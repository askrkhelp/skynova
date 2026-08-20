"""Loads the repo-root .env on first import of anything under app.agents, so
GEMINI_API_KEY etc. are in the process environment before any Agent/Runner
is constructed — needed both for ad-hoc `adk web` runs (whose CLI looks for
a per-agent .env we don't have, since ours lives at the repo root per
CLAUDE.md's target structure) and for tests/scripts that import this
package directly.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from app.agents.session import AssistantSession  # noqa: E402

__all__ = ["AssistantSession"]
