"""Loads the repo-root .env on first import of anything under app.rag, so
GEMINI_API_KEY etc. are in the process environment before GoogleGenerativeAIEmbeddings
is constructed — needed for `python -m app.rag.build` and other entry points that
import this package without first importing app.agents (which does the same thing).
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from app.rag.search import search_policy  # noqa: E402

__all__ = ["search_policy"]
