"""Tests for the Booking & Case MCP server (Epic 3).

Uses fastmcp's in-memory Client transport (Client(mcp_instance)) so no
subprocess/network is needed. Each test builds its own server against a
temp cases.json via build_server() so tests never touch data/cases.json.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.mcp_server.bookings import BookingLookup
from app.mcp_server.server import build_server
from app.store import LocalJSONCaseStore

HERO_PNRS = [f"SN88{n:02d}" for n in range(1, 13)]  # SN8801..SN8812


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def cases_path(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text("[]", encoding="utf-8")
    return path


@pytest.fixture
def server(cases_path):
    return build_server(cases=LocalJSONCaseStore(cases_path), bookings=BookingLookup())


def test_server_lists_all_seven_tools(server):
    async def _run():
        async with Client(server) as client:
            tools = await client.list_tools()
            return {t.name for t in tools}

    names = run(_run())
    assert names == {
        "get_booking",
        "create_case",
        "update_case",
        "assign_team",
        "escalate",
        "get_status",
        "list_cases",
    }


def test_list_cases_returns_every_case(server):
    async def _run():
        async with Client(server) as client:
            await client.call_tool(
                "create_case",
                {
                    "pnr": "SN8801",
                    "issue_type": "delay_compensation",
                    "summary": "case one",
                    "conversation_id": "conv-list-1",
                },
            )
            await client.call_tool(
                "create_case",
                {
                    "pnr": "SN8802",
                    "issue_type": "refund",
                    "summary": "case two",
                    "conversation_id": "conv-list-2",
                },
            )
            listed = await client.call_tool("list_cases", {})
            return listed.data

    result = run(_run())
    assert result["count"] == 2
    assert {c["pnr"] for c in result["cases"]} == {"SN8801", "SN8802"}


def test_get_booking_returns_all_hero_pnrs(server):
    async def _run():
        async with Client(server) as client:
            results = {}
            for pnr in HERO_PNRS:
                result = await client.call_tool("get_booking", {"pnr": pnr})
                results[pnr] = result.data
            return results

    results = run(_run())

    with open("data/bookings.json", encoding="utf-8") as f:
        expected_by_pnr = {b["pnr"]: b for b in json.load(f)}

    assert set(results) == set(HERO_PNRS)
    for pnr in HERO_PNRS:
        assert results[pnr] == expected_by_pnr[pnr]


def test_get_booking_unknown_pnr_raises_clean_error(server):
    async def _run():
        async with Client(server) as client:
            await client.call_tool("get_booking", {"pnr": "SN0000"})

    with pytest.raises(ToolError, match="SN0000"):
        run(_run())


def test_create_update_get_status_round_trip(server):
    async def _run():
        async with Client(server) as client:
            created = await client.call_tool(
                "create_case",
                {
                    "pnr": "SN8804",
                    "issue_type": "delay_compensation",
                    "summary": "Flight delayed 5h, wants refund",
                    "conversation_id": "conv-test-1",
                },
            )
            case_id = created.data["case_id"]

            assert created.data["status"] == "open"
            assert created.data["verdict"] is None

            updated = await client.call_tool(
                "update_case",
                {
                    "case_id": case_id,
                    "status": "resolved",
                    "verdict": "auto_resolve",
                    "justification": {"policy_clause": "policy_delay_compensation.md#3-hours-or-more"},
                },
            )
            assert updated.data["status"] == "resolved"
            assert updated.data["verdict"] == "auto_resolve"

            status = await client.call_tool("get_status", {"case_id": case_id})
            return status.data

    final = run(_run())
    assert final["status"] == "resolved"
    assert final["verdict"] == "auto_resolve"
    assert final["justification"]["policy_clause"] == "policy_delay_compensation.md#3-hours-or-more"


def test_get_status_unknown_case_raises_clean_error(server):
    async def _run():
        async with Client(server) as client:
            await client.call_tool("get_status", {"case_id": "CASE-999999"})

    with pytest.raises(ToolError, match="CASE-999999"):
        run(_run())


def test_assign_team_and_escalate(server):
    async def _run():
        async with Client(server) as client:
            created = await client.call_tool(
                "create_case",
                {
                    "pnr": "SN8802",
                    "issue_type": "refund",
                    "summary": "Non-refundable Saver dispute",
                    "conversation_id": "conv-test-2",
                },
            )
            case_id = created.data["case_id"]

            routed = await client.call_tool("assign_team", {"case_id": case_id, "team": "Refunds"})
            assert routed.data["assigned_team"] == "Refunds"
            assert routed.data["status"] == "routed"

            escalated = await client.call_tool(
                "escalate",
                {"case_id": case_id, "dossier": "Traveler disputes non-refundable Saver fare denial."},
            )
            return escalated.data

    final = run(_run())
    assert final["status"] == "escalated"
    assert final["dossier"] is not None
    assert "non-refundable" in final["dossier"].lower()


def test_assign_team_invalid_team_raises_clean_error(server):
    async def _run():
        async with Client(server) as client:
            created = await client.call_tool(
                "create_case",
                {
                    "pnr": "SN8801",
                    "issue_type": "refund",
                    "summary": "test",
                    "conversation_id": "conv-test-3",
                },
            )
            case_id = created.data["case_id"]
            await client.call_tool("assign_team", {"case_id": case_id, "team": "Not A Real Team"})

    with pytest.raises(ToolError, match="invalid team"):
        run(_run())


def test_dual_client_concurrent_read_write_no_corruption(server):
    """Two independent MCP clients (simulating the Assistant Agent and the
    Triage Orchestrator) hit the same server concurrently and must not
    corrupt state or clobber each other's writes."""

    async def client_a():
        async with Client(server) as client:
            created = await client.call_tool(
                "create_case",
                {
                    "pnr": "SN8801",
                    "issue_type": "delay_compensation",
                    "summary": "client A case",
                    "conversation_id": "conv-a",
                },
            )
            case_id = created.data["case_id"]
            for _ in range(5):
                await client.call_tool("get_booking", {"pnr": "SN8801"})
                await client.call_tool("get_status", {"case_id": case_id})
            return case_id

    async def client_b():
        async with Client(server) as client:
            created = await client.call_tool(
                "create_case",
                {
                    "pnr": "SN8802",
                    "issue_type": "refund",
                    "summary": "client B case",
                    "conversation_id": "conv-b",
                },
            )
            case_id = created.data["case_id"]
            for _ in range(5):
                await client.call_tool("get_booking", {"pnr": "SN8802"})
                await client.call_tool(
                    "update_case", {"case_id": case_id, "status": "routed"}
                )
            return case_id

    async def _run():
        return await asyncio.gather(client_a(), client_b())

    case_id_a, case_id_b = run(_run())

    assert case_id_a != case_id_b

    async def _verify():
        async with Client(server) as client:
            status_a = await client.call_tool("get_status", {"case_id": case_id_a})
            status_b = await client.call_tool("get_status", {"case_id": case_id_b})
            return status_a.data, status_b.data

    final_a, final_b = run(_verify())
    assert final_a["pnr"] == "SN8801"
    assert final_a["conversation_id"] == "conv-a"
    assert final_b["pnr"] == "SN8802"
    assert final_b["conversation_id"] == "conv-b"
    assert final_b["status"] == "routed"
