"""Tests for FirestoreCaseStore (Epic 9) against the local Firestore emulator.

Mirrors the CRUD round-trip coverage tests/test_mcp_server.py already has
for LocalJSONCaseStore, but at the CaseStore level (no MCP layer) since the
point here is confirming the Firestore-backed implementation of the same
interface behaves identically, not re-testing MCP tool wiring.

Skipped entirely if `gcloud emulators firestore` isn't available locally —
this never touches a real GCP project or costs anything; it's a pure local
process. Session-scoped so the emulator starts once for the whole file.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("gcloud") is None,
    reason="gcloud CLI not on PATH; can't run the Firestore emulator",
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((host, port)) == 0:
                return
        time.sleep(0.5)
    raise RuntimeError(f"Firestore emulator did not open {host}:{port} within {timeout}s")


def _java21_plus_bin() -> str | None:
    """The emulator requires a Java 21+ JRE on PATH; the machine's default
    `java` may be older (e.g. 17) while a newer JDK is installed elsewhere.
    Prefer PATH's own java if it's already 21+, else search common install
    roots for one, so the fixture doesn't depend on a specific machine's
    default PATH ordering."""
    import re

    def _major_version(java_bin: str) -> int | None:
        try:
            out = subprocess.run([java_bin, "-version"], capture_output=True, text=True, timeout=10)
        except OSError:
            return None
        match = re.search(r'version "(\d+)', out.stderr or out.stdout)
        return int(match.group(1)) if match else None

    default_java = shutil.which("java")
    if default_java and (_major_version(default_java) or 0) >= 21:
        return None  # PATH is already fine

    search_roots = [
        r"C:\Program Files\Eclipse Adoptium",
        r"C:\Program Files\Java",
    ]
    best: tuple[int, str] | None = None
    for root in search_roots:
        root_path = os.path.join(root)
        if not os.path.isdir(root_path):
            continue
        for entry in os.listdir(root_path):
            java_bin = os.path.join(root_path, entry, "bin")
            java_exe = os.path.join(java_bin, "java.exe")
            if not os.path.exists(java_exe):
                continue
            version = _major_version(java_exe)
            if version and version >= 21 and (best is None or version > best[0]):
                best = (version, java_bin)
    return best[1] if best else None


@pytest.fixture(scope="module")
def firestore_emulator():
    port = _free_port()
    host_port = f"localhost:{port}"
    env = {**os.environ, "CLOUDSDK_CORE_DISABLE_PROMPTS": "1"}
    java21_bin = _java21_plus_bin()
    if java21_bin:
        env["PATH"] = java21_bin + os.pathsep + env["PATH"]
    gcloud = shutil.which("gcloud")
    proc = subprocess.Popen(
        [
            gcloud,
            "emulators",
            "firestore",
            "start",
            "--host-port",
            host_port,
            "--database-mode=firestore-native",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port("localhost", port)
        yield host_port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def store(firestore_emulator, monkeypatch):
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", firestore_emulator)
    # Imported here, not module-level: the google.cloud.firestore.Client()
    # constructed inside FirestoreCaseStore.__init__ must see
    # FIRESTORE_EMULATOR_HOST already set.
    from app.store.firestore_case_store import FirestoreCaseStore

    suffix = str(time.time_ns())
    return FirestoreCaseStore(
        project="resolveai-test",
        collection=f"cases_test_{suffix}",
        counter_doc=f"case_counters_test/cases_{suffix}",
    )


def test_create_case_returns_expected_shape(store):
    case = store.create_case(
        pnr="SN8801", issue_type="refund", summary="test case", conversation_id="conv-1"
    )
    assert case["case_id"].startswith("CASE-")
    assert case["pnr"] == "SN8801"
    assert case["status"] == "open"
    assert case["verdict"] is None


def test_case_ids_increment_across_creates(store):
    first = store.create_case(pnr="SN8801", issue_type="refund", summary="a", conversation_id="c1")
    second = store.create_case(pnr="SN8802", issue_type="refund", summary="b", conversation_id="c2")
    first_n = int(first["case_id"].split("-")[1])
    second_n = int(second["case_id"].split("-")[1])
    assert second_n == first_n + 1


def test_create_update_get_status_round_trip(store):
    created = store.create_case(
        pnr="SN8804", issue_type="delay_compensation", summary="delayed", conversation_id="conv-2"
    )
    case_id = created["case_id"]

    updated = store.update_case(
        case_id,
        status="resolved",
        verdict="auto_resolve",
        justification={"policy_clause": "policy_delay_compensation.md#3-hours-or-more"},
    )
    assert updated["status"] == "resolved"
    assert updated["verdict"] == "auto_resolve"

    fetched = store.get_case(case_id)
    assert fetched["status"] == "resolved"
    assert fetched["justification"]["policy_clause"] == "policy_delay_compensation.md#3-hours-or-more"


def test_assign_team_sets_status_routed(store):
    created = store.create_case(pnr="SN8801", issue_type="baggage", summary="x", conversation_id="c3")
    updated = store.assign_team(created["case_id"], "Baggage")
    assert updated["assigned_team"] == "Baggage"
    assert updated["status"] == "routed"


def test_escalate_sets_dossier_and_status(store):
    created = store.create_case(pnr="SN8801", issue_type="refund", summary="x", conversation_id="c4")
    updated = store.escalate(created["case_id"], dossier="human-readable summary")
    assert updated["dossier"] == "human-readable summary"
    assert updated["status"] == "escalated"


def test_list_cases_returns_every_case(store):
    store.create_case(pnr="SN8801", issue_type="refund", summary="one", conversation_id="c5")
    store.create_case(pnr="SN8802", issue_type="baggage", summary="two", conversation_id="c6")
    cases = store.list_cases()
    assert {c["pnr"] for c in cases} == {"SN8801", "SN8802"}


def test_get_case_unknown_id_raises(store):
    from app.store.case_store import CaseNotFoundError

    with pytest.raises(CaseNotFoundError):
        store.get_case("CASE-999999")


def test_update_case_invalid_status_raises(store):
    created = store.create_case(pnr="SN8801", issue_type="refund", summary="x", conversation_id="c7")
    with pytest.raises(ValueError):
        store.update_case(created["case_id"], status="not-a-real-status")
