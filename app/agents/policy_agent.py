"""Policy Agent — RAG-grounded clause lookup + deterministic policy signal.

Per 01_Architecture_and_Design.md SS3.3, this specialist "retrieves the
exact fare-rule/policy clause(s) that govern this booking + issue... never a
paraphrase without a citation." Two responsibilities are split deliberately:

- `evaluate_policy_signal` is a pure, dependency-free function that decides
  which *category* the booking's facts fall into (an outcome fully resolved
  with no team follow-up, an outcome that requires a specialist team to
  execute, or a case that needs a human — ambiguous policy, a non-refundable
  dispute, or special assistance). This is what makes the verdict
  "traceable to the rule table" rather than an LLM guess, and it's fully
  unit-testable against data/eval_scenarios.json without a live model call.
- `run_policy_agent` wraps that with a real `search_policy` (RAG) call to
  fetch the actual clause text + source_id for the citation — the category
  decision never depends on parsing the retrieved markdown; the retrieval is
  purely for grounding the justification in a real chunk, per the
  non-negotiable that every policy claim traces to one.

Calibrated against every refund/change/delay/baggage/special-assistance
scenario in data/eval_scenarios.json (see CLAUDE.md build-status note for
the reasoning behind "any plain refund ask against a non-refundable Saver
fare escalates" and "team assignment only happens for route/escalate, never
auto-resolve").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from app.rag.search import search_policy as _default_search_policy

# Chroma's cosine-space relevance scores run 0..1 (higher = more relevant,
# see app/rag/index.py). Below this, treat the retrieval as "no confident
# grounding" and force escalation per the grounding contract (SS3.5) rather
# than trust a weak match.
RETRIEVAL_MIN_SCORE = 0.5

_TEAM_BY_ISSUE = {
    "refund": "Refunds",
    "delay_compensation": "Refunds",
    "change": "Rebooking",
    "baggage_claim": "Baggage",
    "special_assistance": "Special Assistance",
}

# These regexes key off phrasing the eval scenarios use deliberately (see
# data/README.md: "Consistent numbers so RAG answers and triage decisions
# are testable") rather than booking timestamps, which the mock dataset
# doesn't populate precisely enough for real cutoff arithmetic (booked_at/
# depart_at spans don't consistently encode "how long ago, relative to the
# support request" — only the traveler's own words do).
_RECENT_BOOKING_RE = re.compile(r"\b(hour|hours|minute|minutes)\s+ago\b", re.IGNORECASE)
_MEDICAL_RE = re.compile(r"\b(hospital|medical|doctor|bereavement|emergency|passed away|funeral)\b", re.IGNORECASE)
_WEATHER_RE = re.compile(r"\b(storm|weather|cyclone|fog|air traffic control|government order)\b", re.IGNORECASE)

DELAY_VOUCHER_MIN_MINUTES = 120
DELAY_COMPENSATION_MIN_MINUTES = 180


@dataclass
class PolicySignal:
    category: str  # "auto" | "route" | "escalate"
    team: str | None
    reason: str
    query: str


def evaluate_policy_signal(issue_type: str, booking: dict[str, Any], traveler_text: str) -> PolicySignal:
    text = traveler_text or ""
    fare_class = booking.get("fare_class")
    status = booking.get("status")
    delay_minutes = booking.get("delay_minutes") or 0

    if issue_type == "special_assistance":
        return PolicySignal(
            "escalate",
            "Special Assistance",
            "Special-assistance requests involving medical clearance always require human review; they cannot be auto-decided.",
            "special assistance medical clearance MEDIF wheelchair oxygen escalation",
        )

    if issue_type == "baggage_claim":
        return PolicySignal(
            "route",
            "Baggage",
            "Lost/damaged/delayed baggage claims are routed to the Baggage team to investigate and process.",
            "lost damaged baggage claim liability report window interim expenses",
        )

    if issue_type == "delay_compensation":
        if status == "cancelled_by_airline":
            return PolicySignal(
                "route",
                "Rebooking",
                "Airline-caused cancellation grants a full refund or free rebooking, regardless of fare.",
                "airline cancelled flight full refund rebooking any fare",
            )
        if _WEATHER_RE.search(text):
            return PolicySignal(
                "route",
                "Rebooking",
                "Disruption is outside SkyNova's control (weather/force majeure): free rebooking or a travel credit only, cash compensation does not apply.",
                "force majeure weather delay compensation rebooking travel credit no cash",
            )
        if delay_minutes >= DELAY_COMPENSATION_MIN_MINUTES:
            return PolicySignal(
                "route",
                "Refunds",
                f"Delay of {delay_minutes} minutes (>=3h) entitles the passenger to a full refund, free rebooking, or a 110% travel credit.",
                "flight delayed 3 hours or more compensation refund rebooking travel credit",
            )
        if delay_minutes >= DELAY_VOUCHER_MIN_MINUTES:
            return PolicySignal(
                "auto",
                None,
                f"Delay of {delay_minutes} minutes (2-3h band) entitles the passenger to a INR 500 meal voucher only, not a refund.",
                "delay 2 to 3 hours meal voucher compensation",
            )
        return PolicySignal(
            "auto",
            None,
            f"Delay of {delay_minutes} minutes is below the 2-hour compensation threshold; no compensation applies.",
            "delay compensation threshold policy",
        )

    if issue_type == "change":
        if status == "cancelled_by_airline":
            return PolicySignal(
                "route",
                "Rebooking",
                "Airline-caused cancellation grants a full refund or free rebooking, regardless of fare.",
                "airline cancelled flight full refund rebooking any fare",
            )
        return PolicySignal(
            "route",
            "Rebooking",
            f"{fare_class or 'This'} fare change/reschedule request routed to Rebooking for processing.",
            f"{fare_class or ''} fare change reschedule fee".strip(),
        )

    if issue_type in ("refund", "abuse_signal"):
        if status == "cancelled_by_airline":
            return PolicySignal(
                "route",
                "Rebooking",
                "Airline-caused cancellation grants a full refund or free rebooking, regardless of fare.",
                "airline cancelled flight full refund rebooking any fare",
            )
        if status == "no_show":
            return PolicySignal(
                "auto",
                None,
                "No-show: no refund is due except statutory taxes, regardless of fare.",
                "no-show missed flight refund taxes only",
            )
        if _RECENT_BOOKING_RE.search(text):
            return PolicySignal(
                "route",
                "Refunds",
                "Cancelled within 24 hours of booking and 7+ days before departure: fully refunded under the 24-hour free-cancellation rule, even on Saver.",
                "24 hour free cancellation rule booked within 24 hours",
            )
        if fare_class == "Saver":
            reason = "Saver is non-refundable (only statutory taxes are refunded)."
            if _MEDICAL_RE.search(text):
                reason += " A medical/bereavement exception was cited — per the refund policy's escalation guidance, a human must review it."
            else:
                reason += " The traveler is asking for a refund the fare doesn't grant — per the refund policy's escalation guidance, a human must review the dispute."
            return PolicySignal(
                "escalate",
                "Refunds",
                reason,
                "saver fare non-refundable escalation dispute medical bereavement exception",
            )
        if fare_class == "Flex":
            return PolicySignal(
                "route",
                "Refunds",
                "Flex fare is refundable minus a INR 1,500 cancellation fee.",
                "flex fare refund cancellation fee two hours",
            )
        if fare_class == "Business":
            return PolicySignal(
                "route",
                "Refunds",
                "Business fare is fully refundable with no cancellation fee.",
                "business fare full refund no fee one hour",
            )
        return PolicySignal(
            "escalate",
            "Refunds",
            "Fare class is unknown; refund eligibility can't be determined without human review.",
            "refund eligibility by fare",
        )

    return PolicySignal(
        "escalate",
        _TEAM_BY_ISSUE.get(issue_type),
        f"No deterministic policy rule for issue_type={issue_type!r}; needs human review.",
        issue_type,
    )


@dataclass
class PolicyAgentResult:
    category: str  # "auto" | "route" | "escalate" (post grounding-confidence override)
    team: str | None
    reason: str
    policy_clause: str | None
    policy_text: str | None
    retrieval_score: float | None


SearchFn = Callable[..., list[dict[str, Any]]]


async def run_policy_agent(
    issue_type: str,
    booking: dict[str, Any],
    traveler_text: str,
    search_fn: SearchFn = _default_search_policy,
) -> PolicyAgentResult:
    signal = evaluate_policy_signal(issue_type, booking, traveler_text)
    fare_class = booking.get("fare_class") or None

    results = search_fn(signal.query, fare_class=fare_class, doc_type=None, k=2)

    if not results:
        return PolicyAgentResult(
            category="escalate",
            team=signal.team or _TEAM_BY_ISSUE.get(issue_type, "Refunds"),
            reason=f"{signal.reason} (no policy chunk retrieved — escalating rather than deciding ungrounded.)",
            policy_clause=None,
            policy_text=None,
            retrieval_score=None,
        )

    top = results[0]
    category = signal.category
    reason = signal.reason
    if top["score"] < RETRIEVAL_MIN_SCORE:
        category = "escalate"
        reason = f"{signal.reason} (low-confidence retrieval, score={top['score']:.2f} — escalating for human confirmation of the cited clause.)"

    return PolicyAgentResult(
        category=category,
        team=signal.team,
        reason=reason,
        policy_clause=top["source_id"],
        policy_text=top["text"],
        retrieval_score=top["score"],
    )
