"""CaseStore — storage interface for the Case system + local-JSON impl.

The MCP server's case tools (create_case/update_case/assign_team/escalate/
get_status) talk only to this interface, never to a backend directly, so a
Firestore implementation (per 04_GCP_Deployment_Architecture.md SS8) can be
swapped in later without touching MCP tool code. Only the local-JSON
implementation is built for now.

Case schema per 01_Architecture_and_Design.md SS4.2, plus a `summary` field
to hold the free-text passed into create_case (the architecture doc's
example case JSON omits it, but the tool contract in SS3.4 takes it as a
required arg, so it needs somewhere to live).
"""

from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES_PATH = REPO_ROOT / "data" / "cases.json"

VALID_STATUSES = {"open", "routed", "escalated", "resolved"}
VALID_VERDICTS = {"auto_resolve", "route", "escalate"}
VALID_TEAMS = {"Refunds", "Rebooking", "Baggage", "Special Assistance"}


class CaseNotFoundError(KeyError):
    """Raised when a case_id doesn't exist in the store."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CaseStore(ABC):
    """Storage interface shared by the Assistant Agent and Orchestrator's MCP tools."""

    @abstractmethod
    def create_case(
        self, pnr: str, issue_type: str, summary: str, conversation_id: str
    ) -> dict[str, Any]: ...

    @abstractmethod
    def get_case(self, case_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def list_cases(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def update_case(
        self,
        case_id: str,
        status: str | None = None,
        verdict: str | None = None,
        justification: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def assign_team(self, case_id: str, team: str) -> dict[str, Any]: ...

    @abstractmethod
    def escalate(self, case_id: str, dossier: str) -> dict[str, Any]: ...


class LocalJSONCaseStore(CaseStore):
    """Dev-mode case store backed by a single JSON file (data/cases.json).

    A lock around every read-modify-write cycle keeps two concurrent callers
    (e.g. the Assistant Agent and the Orchestrator, each holding their own
    MCP client) from corrupting the file or clobbering each other's update.
    Writes go to a temp file and are atomically renamed into place.
    """

    def __init__(self, path: str | Path = DEFAULT_CASES_PATH):
        self._path = Path(path)
        self._lock = threading.Lock()
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text("[]", encoding="utf-8")

    def _read_all(self) -> list[dict[str, Any]]:
        text = self._path.read_text(encoding="utf-8")
        return json.loads(text) if text.strip() else []

    def _write_all(self, cases: list[dict[str, Any]]) -> None:
        tmp_path = self._path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(cases, indent=2), encoding="utf-8")
        tmp_path.replace(self._path)

    @staticmethod
    def _find(cases: list[dict[str, Any]], case_id: str) -> dict[str, Any]:
        for case in cases:
            if case["case_id"] == case_id:
                return case
        raise CaseNotFoundError(case_id)

    @staticmethod
    def _next_case_id(cases: list[dict[str, Any]]) -> str:
        max_n = 0
        for case in cases:
            try:
                n = int(case["case_id"].split("-")[1])
            except (KeyError, IndexError, ValueError):
                continue
            max_n = max(max_n, n)
        return f"CASE-{max_n + 1:06d}"

    def create_case(
        self, pnr: str, issue_type: str, summary: str, conversation_id: str
    ) -> dict[str, Any]:
        with self._lock:
            cases = self._read_all()
            now = _now_iso()
            case = {
                "case_id": self._next_case_id(cases),
                "pnr": pnr,
                "conversation_id": conversation_id,
                "issue_type": issue_type,
                "summary": summary,
                "status": "open",
                "assigned_team": None,
                "verdict": None,
                "justification": None,
                "dossier": None,
                "created_at": now,
                "updated_at": now,
            }
            cases.append(case)
            self._write_all(cases)
            return case

    def get_case(self, case_id: str) -> dict[str, Any]:
        with self._lock:
            cases = self._read_all()
            return dict(self._find(cases, case_id))

    def list_cases(self) -> list[dict[str, Any]]:
        with self._lock:
            cases = self._read_all()
            return [dict(case) for case in cases]

    def update_case(
        self,
        case_id: str,
        status: str | None = None,
        verdict: str | None = None,
        justification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            cases = self._read_all()
            case = self._find(cases, case_id)
            if status is not None:
                if status not in VALID_STATUSES:
                    raise ValueError(f"invalid status: {status!r} (must be one of {sorted(VALID_STATUSES)})")
                case["status"] = status
            if verdict is not None:
                if verdict not in VALID_VERDICTS:
                    raise ValueError(f"invalid verdict: {verdict!r} (must be one of {sorted(VALID_VERDICTS)})")
                case["verdict"] = verdict
            if justification is not None:
                case["justification"] = justification
            case["updated_at"] = _now_iso()
            self._write_all(cases)
            return dict(case)

    def assign_team(self, case_id: str, team: str) -> dict[str, Any]:
        if team not in VALID_TEAMS:
            raise ValueError(f"invalid team: {team!r} (must be one of {sorted(VALID_TEAMS)})")
        with self._lock:
            cases = self._read_all()
            case = self._find(cases, case_id)
            case["assigned_team"] = team
            case["status"] = "routed"
            case["updated_at"] = _now_iso()
            self._write_all(cases)
            return dict(case)

    def escalate(self, case_id: str, dossier: str) -> dict[str, Any]:
        with self._lock:
            cases = self._read_all()
            case = self._find(cases, case_id)
            case["dossier"] = dossier
            case["status"] = "escalated"
            case["updated_at"] = _now_iso()
            self._write_all(cases)
            return dict(case)
