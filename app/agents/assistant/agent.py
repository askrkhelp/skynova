"""Entry point for `adk web` / `adk run` (per the ADK standard project
layout: <agent_name>/agent.py exposing root_agent). Uses the real MCP server
against data/bookings.json + data/cases.json — for ad-hoc manual tracing
during development, not for tests (see tests/test_assistant_agent.py, which
builds an isolated server per test).
"""

from __future__ import annotations

from app.agents.assistant_agent import build_assistant_agent
from app.agents.mcp_client import MCPBridge
from app.mcp_server.server import build_server

root_agent = build_assistant_agent(MCPBridge(build_server()))
