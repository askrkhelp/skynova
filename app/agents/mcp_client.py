"""MCPBridge — the Assistant Agent's MCP client connection to the shared
Booking & Case FastMCP server (Epic 3).

Uses fastmcp's in-memory Client transport (the same pattern as
tests/test_mcp_server.py) rather than a subprocess/stdio hop: the server and
agent share one container/process (per 01_Architecture_and_Design.md SS3.4),
so there's no separate process to shell out to. A fresh Client is opened per
call, which is cheap over an in-memory transport and keeps the bridge
stateless and safe to share across concurrent tool calls.

Bound to a specific server instance (rather than a module-level singleton)
so tests can hand it an isolated build_server(cases=..., bookings=...)
instead of touching the real data/cases.json — same reasoning as
build_server() itself.
"""

from __future__ import annotations

from typing import Any

from fastmcp import Client, FastMCP


class MCPBridge:
    def __init__(self, server: FastMCP):
        self._server = server

    async def call(self, tool_name: str, **kwargs: Any) -> Any:
        async with Client(self._server) as client:
            result = await client.call_tool(tool_name, kwargs)
            return result.data
