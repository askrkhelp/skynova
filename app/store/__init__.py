import os

from app.store.case_store import (
    CaseNotFoundError,
    CaseStore,
    LocalJSONCaseStore,
)

__all__ = ["CaseNotFoundError", "CaseStore", "LocalJSONCaseStore", "get_case_store"]


def get_case_store() -> CaseStore:
    """Selects the CaseStore backend via CASE_STORE_BACKEND: "local" (default,
    data/cases.json) or "firestore" (Cloud Run/prod), per CLAUDE.md /
    04_GCP_Deployment_Architecture.md SS8. Firestore import is local to this
    branch so local dev never needs GCP credentials to boot.
    """
    backend = os.environ.get("CASE_STORE_BACKEND", "local").lower()
    if backend == "firestore":
        from app.store.firestore_case_store import FirestoreCaseStore

        return FirestoreCaseStore(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    return LocalJSONCaseStore()
