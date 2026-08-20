"""Anti-hallucination guardrail — post-hoc check of numeric claims in an
assistant reply against the chunks retrieved during that turn.

Per 01_Architecture_and_Design.md SS3.6: "a lightweight post-hoc check: any
numeric claim (Rs, kg, hours) in the assistant's reply must match a
retrieved chunk's numbers, else the reply is rejected and regenerated once,
then escalated." This module is the pure/offline half of that guardrail —
extracting claims and comparing them against chunk text needs no model or
network call, so it's fully unit-testable. The wiring that owns "regenerate
once, then escalate" lives in app/agents/session.py's AssistantSession.send,
since only the session has a Runner to re-invoke.

Deliberately a symbol-level check (does this number appear anywhere in the
retrieved text), not semantic entailment — matching SS3.6's "lightweight"
framing rather than a second LLM-judge call.
"""

from __future__ import annotations

import re
from typing import Any

_MONEY_RE = re.compile(r"(?:₹|inr)\s?([\d,]+(?:\.\d+)?)", re.IGNORECASE)
_KG_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s?kg\b", re.IGNORECASE)
_HOUR_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s?(?:hours?|hrs?|hr)\b", re.IGNORECASE)

_CLAIM_PATTERNS = [_MONEY_RE, _KG_RE, _HOUR_RE]
_NUMBER_RE = re.compile(r"[\d,]+(?:\.\d+)?")


def _normalize(number_text: str) -> str:
    return number_text.replace(",", "").rstrip(".")


def extract_numeric_claims(text: str) -> list[str]:
    """Every Rs/kg/hour figure stated in `text`, normalized (no commas)."""
    claims: list[str] = []
    for pattern in _CLAIM_PATTERNS:
        claims.extend(_normalize(m) for m in pattern.findall(text or ""))
    return claims


def _chunk_numbers(chunks: list[dict[str, Any]]) -> set[str]:
    combined_text = " ".join(chunk.get("text", "") or "" for chunk in chunks)
    return {_normalize(n) for n in _NUMBER_RE.findall(combined_text)}


def verify_numeric_claims(reply: str, chunks: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Returns (ok, unverified_claims). ok is True iff every Rs/kg/hour
    figure stated in `reply` also appears as a number somewhere in the text
    of `chunks` (the search_policy results retrieved this turn). A reply
    with no numeric claims trivially passes; a reply with numeric claims but
    no retrieved chunks at all fails outright — there's nothing to ground
    the claim in.
    """
    claims = extract_numeric_claims(reply)
    if not claims:
        return True, []

    available = _chunk_numbers(chunks)
    unverified = [claim for claim in claims if claim not in available]
    return not unverified, unverified
