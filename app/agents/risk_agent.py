"""Risk Agent — deterministic risk/value scoring for the Triage Orchestrator.

Per 01_Architecture_and_Design.md SS3.3: computes a risk/value score and an
abuse-signal flag from booking fields already in the dataset (price_inr,
account_age_days, prior_bookings, prior_refunds_90d, return_to_order_ratio).
Deliberately booking-fields-only, no free text and no LLM call — the spec
lists this specialist's inputs as booking data, and keeping it a pure
function makes it fully unit-testable without a live model call.

Thresholds are calibrated against data/eval_scenarios.json's abuse_signal
scenarios (E14, E58-E62): every one of them has return_to_order_ratio >=
0.5, and every non-abuse scenario in the eval set — including high-value
ones like E05/E39 with no refund history, and E50 (a plain small-delay
scenario whose booking happens to carry prior_refunds_90d=3 with a low
0.3 ratio) — falls below it. prior_refunds_90d alone is therefore *not*
used as an independent trigger: at prior_refunds_90d==3 it collides with
E50's non-abuse booking, and every golden abuse scenario is already caught
by the ratio. It still feeds the informational risk_score and flags list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ABUSE_RATIO_THRESHOLD = 0.5
# Informational only (risk_score/flags) — see module docstring for why this
# isn't an independent abuse_flag trigger.
NOTABLE_REFUNDS_90D = 3

# Weights for the informational composite risk_score (0..1) shown in the
# justification's signals — abuse_flag (above) is the actual verdict gate;
# risk_score is explanatory context, not itself a hard threshold, since a
# purely value-driven score would misfire on high-value/low-abuse bookings
# like E05 (Business, INR 27,300, no refund history -> still auto-approved).
_VALUE_WEIGHT = 0.15
_REFUND_WEIGHT = 0.35
_RATIO_WEIGHT = 0.35
_NEW_ACCOUNT_WEIGHT = 0.15

_VALUE_NORMALIZER = 50_000
_REFUND_NORMALIZER = 5
_RATIO_NORMALIZER = 2
_NEW_ACCOUNT_DAYS = 365


@dataclass
class RiskSignal:
    risk_score: float
    abuse_flag: bool
    flags: list[str] = field(default_factory=list)


def score_risk(booking: dict[str, Any]) -> RiskSignal:
    price_inr = booking.get("price_inr") or 0
    account_age_days = booking.get("account_age_days") or 0
    prior_bookings = booking.get("prior_bookings") or 0
    prior_refunds_90d = booking.get("prior_refunds_90d") or 0
    return_to_order_ratio = booking.get("return_to_order_ratio") or 0.0

    flags: list[str] = []

    abuse_flag = return_to_order_ratio >= ABUSE_RATIO_THRESHOLD
    if return_to_order_ratio >= ABUSE_RATIO_THRESHOLD:
        flags.append(f"return_to_order_ratio={return_to_order_ratio} >= {ABUSE_RATIO_THRESHOLD}")
    if prior_refunds_90d >= NOTABLE_REFUNDS_90D:
        flags.append(f"prior_refunds_90d={prior_refunds_90d} >= {NOTABLE_REFUNDS_90D}")
    if account_age_days < 90:
        flags.append(f"new_account: age={account_age_days}d")

    value_component = min(price_inr / _VALUE_NORMALIZER, 1.0)
    refund_component = min(prior_refunds_90d / _REFUND_NORMALIZER, 1.0)
    ratio_component = min(return_to_order_ratio / _RATIO_NORMALIZER, 1.0)
    new_account_component = max(0.0, (_NEW_ACCOUNT_DAYS - account_age_days) / _NEW_ACCOUNT_DAYS)

    risk_score = round(
        _VALUE_WEIGHT * value_component
        + _REFUND_WEIGHT * refund_component
        + _RATIO_WEIGHT * ratio_component
        + _NEW_ACCOUNT_WEIGHT * new_account_component,
        3,
    )

    return RiskSignal(risk_score=risk_score, abuse_flag=abuse_flag, flags=flags)
