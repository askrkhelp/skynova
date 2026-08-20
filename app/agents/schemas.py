"""Structured JSON contracts for the Assistant Agent's turn output and the
Triage Orchestrator's verdict.

`ExtractedRequest` is the intent+entity extraction schema from
01_Architecture_and_Design.md SS3.2 step 2. `AssistantTurnOutput` wraps it
together with the agent's reply and handoff bookkeeping so a single LlmAgent
call (output_schema + tools together, per installed google-adk>=2.5) can
both extract structure and answer/act in one turn.

`Verdict`/`Justification`/`VerdictSignals` are the pydantic mirror of the
verdict JSON schema in 01_Architecture_and_Design.md SS3.3 — constructing
one of these from a Triage Orchestrator run's output is the acceptance
criterion "verdict JSON validates against the schema" (pydantic raises
ValidationError on any missing/wrong-shaped required field, in particular
`justification.policy_clause`/`policy_text`/`reasoning`, which cannot be
null per SS3.3's non-negotiable that every verdict cites a real clause).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# "unclear" covers ambiguous free text with no resolvable issue (SS5.3).
# "policy_question" covers grounded Q&A that never needs a case.
IssueType = Literal[
    "policy_question",
    "refund",
    "change",
    "delay_compensation",
    "baggage_claim",
    "special_assistance",
    "unclear",
]

# Per CLAUDE.md/architecture SS3.2 step 5 — these always route through
# open_case rather than a direct grounded answer.
DECISION_ISSUE_TYPES = {
    "refund",
    "change",
    "delay_compensation",
    "baggage_claim",
    "special_assistance",
}

FareClass = Literal["Saver", "Flex", "Business"]
Urgency = Literal["low", "medium", "high"]


class ExtractedRequest(BaseModel):
    issue_type: IssueType
    pnr: str | None = Field(default=None, description="Booking reference, e.g. SN8804.")
    passenger: str | None = None
    flight_leg: str | None = Field(
        default=None,
        description="e.g. 'outbound', 'return', a flight number, or null if not applicable.",
    )
    fare_class: FareClass | None = None
    amount: float | None = Field(default=None, description="Rupee amount mentioned, if any.")
    urgency: Urgency | None = None


class AssistantTurnOutput(BaseModel):
    extracted: ExtractedRequest
    needs_clarification: bool = Field(
        description="True if a required slot is missing and one targeted question must be asked instead of acting."
    )
    clarifying_question: str | None = Field(
        default=None, description="Set only when needs_clarification is true."
    )
    reply: str = Field(description="The message to show the traveler.")
    case_id: str | None = Field(
        default=None, description="Set when open_case was called this turn."
    )
    citations: list[str] = Field(
        default_factory=list, description="source_id values from search_policy results used in the reply."
    )


VerdictCategory = Literal["auto_resolve", "route", "escalate"]


class VerdictSignals(BaseModel):
    """The specialist outputs the verdict is traceable to (SS3.3)."""

    issue_type: str
    intent_confidence: float
    fare_class: str | None = None
    price_inr: float | None = None
    delay_minutes: int | None = None
    risk_score: float
    abuse_flag: bool


class Justification(BaseModel):
    policy_clause: str = Field(description="source_id of the retrieved policy chunk, e.g. 'policy_delay_compensation.md#3-hours-or-more'.")
    policy_text: str = Field(description="The retrieved clause text — never a paraphrase.")
    signals: VerdictSignals
    reasoning: str = Field(description="Natural-language justification tying the signals to the verdict.")


class Verdict(BaseModel):
    case_id: str
    pnr: str
    issue_type: str
    verdict: VerdictCategory
    justification: Justification
    assigned_team: str | None = None
    dossier: str | None = None
    created_at: str
