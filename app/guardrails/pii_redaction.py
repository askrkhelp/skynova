"""PII redaction guardrail — regex-based masking of PNR, card-like digit
sequences, email addresses, and phone numbers in free text.

Per 01_Architecture_and_Design.md SS3.6: "regex + entity check on PNR
(`SN\\d{4}`), card-like digit sequences, email/phone before writing to logs
or the dossier's non-essential fields." Applied only to free text a
traveler typed (log lines, the traveler's-own-words quote inside a
dossier — see triage_orchestrator.build_dossier) — never to a case's own
structured `pnr` field, which is the case's primary business key and stays
in plain text everywhere it's the essential identifier (the dossier's
header line, `get_status` results, etc.). Order matters below: card-like
sequences are masked before the looser phone pattern so a card number
doesn't get mis-tagged as a phone number.
"""

from __future__ import annotations

import re

_PNR_RE = re.compile(r"\bSN\d{4}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_PHONE_RE = re.compile(r"\b\+?\d[\d\-\s]{7,14}\d\b")


def redact_pii(text: str | None) -> str:
    """Masks PNR/card/email/phone patterns in free text. Idempotent."""
    if not text:
        return text or ""
    redacted = _EMAIL_RE.sub("[EMAIL]", text)
    redacted = _CARD_RE.sub("[CARD]", redacted)
    redacted = _PNR_RE.sub("[PNR]", redacted)
    redacted = _PHONE_RE.sub("[PHONE]", redacted)
    return redacted
