# ResolveAI Evaluation Report (Epic 8)

Scenarios run: 2 (from `data/eval_scenarios.json`). 1/2 fully matched their expected outcome.

## Metrics (spec §9)

| # | Metric | Result | Detail |
|---|---|---|---|
| 1 | Resolution rate | 100.0% | 1/1 assistant-alone-resolvable scenarios closed correctly |
| 2 | Routing accuracy | 0.0% | 0/1 route-verdict scenarios sent to the correct team |
| 3 | Escalation calibration | 0.0% | recall(hard→escalated)=n/a, specificity(clear→not escalated)=0.0% (TP=0 FN=0 FP=1 TN=0) |
| 4 | Grounding / hallucination rate | 0.00% | 0/1 numeric claims unverified — target <2%, MEETS target |
| 5 | Justification faithfulness | n/a / 3 | judged 0/1 verdict-bearing cases; low-score (<=1) ids: none |
| 6 | Orchestration reliability | 0.0% | 0/1 decision scenarios completed with a real verdict inside the wall-clock caps |

## Failing / borderline scenarios (1)

### E05 — refund_auto_approve
- Notes: auto-approve
- Expected: Business fare, >1h before departure -> Auto-approve full refund, no fee.
- Expected outcome: case=True verdict=route team=Refunds clarify=False
- Actual outcome: case_id=CASE-000002 verdict=escalate team=None clarify=False guardrail_tripped=True
- Duration: 12.06s
- Mismatch reasons:
  - verdict mismatch: expected=route actual=escalate
  - team mismatch: expected=Refunds actual=None
  - guardrail cap tripped — fallback escalation, not a real verdict
- Transcript:
  1. **User:** I want to cancel SN8803 and get a refund.
     **Assistant:** This is taking longer than expected, so I've opened a case (CASE-000002) for a specialist to review and get back to you.
     _(opened CASE-000002)_
