"""FirestoreCaseStore — Cloud Run/prod CaseStore backend (Epic 9).

Same CaseStore interface LocalJSONCaseStore implements (app/store/case_store.py),
so MCP tool code (app/mcp_server/server.py) never knows which backend it's
talking to — selection happens once, in app.store.get_case_store(), per
CASE_STORE_BACKEND (04_GCP_Deployment_Architecture.md SS8).

Case IDs (`CASE-000123`) are assigned via a Firestore transaction against a
single counter document rather than "read all cases, take max+1" (the local
JSON store's approach): Firestore is the backend precisely because case
writes can come from multiple concurrent Cloud Run instances (SS2), and a
max-scan has a race two instances can hit at the same time. A transactional
counter increment is atomic across instances.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

from app.store.case_store import (
    VALID_STATUSES,
    VALID_TEAMS,
    VALID_VERDICTS,
    CaseNotFoundError,
    CaseStore,
)

DEFAULT_COLLECTION = "cases"
DEFAULT_COUNTER_DOC = "case_counters/cases"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FirestoreCaseStore(CaseStore):
    def __init__(
        self,
        project: str | None = None,
        collection: str = DEFAULT_COLLECTION,
        counter_doc: str = DEFAULT_COUNTER_DOC,
    ):
        self._client = firestore.Client(project=project)
        self._collection = self._client.collection(collection)
        self._counter_ref = self._client.document(counter_doc)

    def _next_case_id(self) -> str:
        transaction = self._client.transaction()
        counter_ref = self._counter_ref

        @firestore.transactional
        def _increment(transaction: firestore.Transaction) -> int:
            snapshot = counter_ref.get(transaction=transaction)
            current = snapshot.get("value") if snapshot.exists else 0
            next_value = current + 1
            transaction.set(counter_ref, {"value": next_value})
            return next_value

        return f"CASE-{_increment(transaction):06d}"

    def _get_doc(self, case_id: str) -> firestore.DocumentReference:
        doc_ref = self._collection.document(case_id)
        if not doc_ref.get().exists:
            raise CaseNotFoundError(case_id)
        return doc_ref

    def create_case(
        self, pnr: str, issue_type: str, summary: str, conversation_id: str
    ) -> dict[str, Any]:
        now = _now_iso()
        case = {
            "case_id": self._next_case_id(),
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
        self._collection.document(case["case_id"]).set(case)
        return case

    def get_case(self, case_id: str) -> dict[str, Any]:
        return dict(self._get_doc(case_id).get().to_dict())

    def list_cases(self) -> list[dict[str, Any]]:
        return [doc.to_dict() for doc in self._collection.stream()]

    def update_case(
        self,
        case_id: str,
        status: str | None = None,
        verdict: str | None = None,
        justification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        doc_ref = self._get_doc(case_id)
        updates: dict[str, Any] = {}
        if status is not None:
            if status not in VALID_STATUSES:
                raise ValueError(f"invalid status: {status!r} (must be one of {sorted(VALID_STATUSES)})")
            updates["status"] = status
        if verdict is not None:
            if verdict not in VALID_VERDICTS:
                raise ValueError(f"invalid verdict: {verdict!r} (must be one of {sorted(VALID_VERDICTS)})")
            updates["verdict"] = verdict
        if justification is not None:
            updates["justification"] = justification
        updates["updated_at"] = _now_iso()
        doc_ref.update(updates)
        return dict(doc_ref.get().to_dict())

    def assign_team(self, case_id: str, team: str) -> dict[str, Any]:
        if team not in VALID_TEAMS:
            raise ValueError(f"invalid team: {team!r} (must be one of {sorted(VALID_TEAMS)})")
        doc_ref = self._get_doc(case_id)
        doc_ref.update({"assigned_team": team, "status": "routed", "updated_at": _now_iso()})
        return dict(doc_ref.get().to_dict())

    def escalate(self, case_id: str, dossier: str) -> dict[str, Any]:
        doc_ref = self._get_doc(case_id)
        doc_ref.update({"dossier": dossier, "status": "escalated", "updated_at": _now_iso()})
        return dict(doc_ref.get().to_dict())
