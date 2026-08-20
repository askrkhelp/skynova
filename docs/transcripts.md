# Annotated Conversation Transcripts

Three transcripts, pulled verbatim from real captured runs (not invented) — `eval/results.json`, `eval/report.md`, and `data/cases.json`. Each is annotated inline with what it's demonstrating.

A note on scope: two categories called for by the backlog — **query refinement** (a clarify turn followed by a refined follow-up) and **coreference resolution** (e.g. E03's "return leg too") — are exercised in `tests/test_assistant_agent.py` (`test_return_leg_scenario_resolves_without_reasking_pnr`, the clarify tests) but no run's literal reply text was ever logged to a persisted file, only asserted against in-memory. Rather than reconstruct plausible-sounding dialogue for those two, this doc ships three transcripts backed by real, on-disk text and calls out the gap here instead.

---

## Transcript 1 — Grounded answering with citation (E01)

Source: `eval/results.json`, scenario `E01`, live run, 9.51s, `claims_total: 1`, `unverified_claims: []`.

> **Traveler:** What is my cabin baggage limit on a Saver fare?
>
> **Assistant:** On a Saver fare, your cabin baggage allowance is 7 kg (1 piece) [policies/policy_baggage.md#allowances-by-fare].

**What this demonstrates:**
- No PNR needed — this is a pure policy question, so the agent never calls `get_booking`, only `search_policy`.
- The extracted `fare_class: "Saver"` came from the traveler's own wording, not a lookup.
- The reply's one numeric claim (7 kg) is inline-cited to the exact retrieved chunk (`policies/policy_baggage.md#allowances-by-fare`) and passed the anti-hallucination check (`app/guardrails/hallucination_check.py`) that runs after every turn — the claim was verified against the chunk actually retrieved, not just asserted by the model.
- No case is opened — per the non-negotiable in [CLAUDE.md](../CLAUDE.md), a grounded answer doesn't need one.

---

## Transcript 2 — A guardrail trip that escalates instead of dead-ending (E05)

Source: `eval/report.md` / `eval/results.json`, scenario `E05`, live run 2026-08-19T16:48:52Z, 12.06s.

> **Traveler:** I want to cancel SN8803 and get a refund.
>
> **Assistant:** This is taking longer than expected, so I've opened a case (CASE-000002) for a specialist to review and get back to you.

**What this demonstrates:**
- The non-negotiable that guardrail trips (here, the Assistant's wall-clock cap) always resolve to a human case, never a dropped request or an error screen — see `app/agents/session.py::_escalate_turn`.
- **This transcript is also the evidence behind [failure case #1](failure_analysis.md#1-decision-flow-turns-tripped-the-assistants-wall-clock-cap-by-construction) in the failure analysis.** At the time this ran, `ASSISTANT_WALL_CLOCK_CAP_S` was 12s — strictly smaller than the Orchestrator's own 20s cap that `open_case` invokes synchronously, so this exact input (a decision needing `get_booking` + the full Triage Orchestrator) was guaranteed to trip the outer cap before the verdict could complete. It should have auto-approved (Business fare, outside the 1h cutoff) as `route`/`Refunds`, not escalated.
- The cap has since been raised to 35s (`app/guardrails/caps.py:43`); Epic 9's later live smoke test against the deployed app ran the equivalent input (`SN8803` cancel) and it did auto-approve correctly as `CASE-000001` routed to Refunds — a different session/case ID, not a re-run of this exact transcript, but consistent with the fix.

---

## Transcript 3 — Escalation with its full dossier (CASE-000004)

Source: `data/cases.json`, `CASE-000004` (PNR `SN8802`), a live Epic 7 UI-testing run. The input text matches `eval_scenarios.json`'s `E06` exactly.

> **Traveler:** Cancel SN8802 and refund me fully, I changed my mind.

The literal chat-UI reply text for this run wasn't persisted anywhere on disk (only the case record was) — so rather than reconstruct it, here is the real artifact a reviewer actually sees in the Reviewer Queue tab, verbatim:

```
Case CASE-000004 — refund — PNR SN8802 (Diya Rao)
Flight SN-505 BLR->DEL on 2026-08-19 15:00 | fare=Saver | price=INR 4300 | status=confirmed | delay=0min
Account: age=216d, prior_bookings=8, prior_refunds_90d=1, return_to_order_ratio=0.03
Policy clause: policies/policy_refund_cancellation.md#escalation-guidance
Policy text: ## Escalation guidance
Escalate to a human when: the fare is non-refundable but the customer cites a medical/bereavement exception; the refund value is unusually high; or there are signs of repeat-refund abuse.
Risk score: 0.149 | abuse_flag=False
Reasoning: Saver is non-refundable (only statutory taxes are refunded). The traveler is asking for a refund the fare doesn't grant — per the refund policy's escalation guidance, a human must review the dispute.
Traveler's original message: "Cancel [PNR] and refund me fully, I changed my mind."
```

The reviewer then denied it:

```json
{"action": "deny", "note": "Saver fare is non-refundable per policy; denying full refund.", "actor": "reviewer", "at": "2026-08-19T16:25:31Z"}
```

**What this demonstrates:**
- The full justification schema from `01_Architecture_and_Design.md` §3.3 in the wild: a `policy_clause` citation, the actual retrieved `policy_text`, the `signals` the Risk/Policy Agents used (fare class, price, risk score, abuse flag), and a `reasoning` string — never a bare verdict.
- PII redaction (`app/guardrails/pii_redaction.py`) applied selectively: the PNR appears in plain text in the structured header (`PNR SN8802`) because it's an essential field, but the same PNR is redacted to `[PNR]` inside the traveler's-own-words quote at the bottom — per Epic 6's design, only the free-text quote gets redacted, not structured fields.
- The human-review audit trail (Epic 7): the reviewer's `deny` action is appended to `justification.human_actions` alongside the AI's original reasoning, rather than overwriting it — both are visible together on the same case.
