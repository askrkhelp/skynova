"""Read-only booking lookups from data/bookings.json.

Bookings data is static mock data — this module never writes to it (see
CLAUDE.md conventions).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BOOKINGS_PATH = REPO_ROOT / "data" / "bookings.json"


class BookingNotFoundError(KeyError):
    """Raised when a PNR doesn't exist in the bookings dataset."""


class BookingLookup:
    """Read-only, in-memory index over the static bookings dataset."""

    def __init__(self, path: str | Path = DEFAULT_BOOKINGS_PATH):
        self._path = Path(path)
        records = json.loads(self._path.read_text(encoding="utf-8"))
        self._by_pnr: dict[str, dict[str, Any]] = {record["pnr"]: record for record in records}

    def get(self, pnr: str) -> dict[str, Any]:
        try:
            return dict(self._by_pnr[pnr])
        except KeyError:
            raise BookingNotFoundError(pnr) from None
