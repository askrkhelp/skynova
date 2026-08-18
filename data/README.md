# SkyNova Mock Data — ResolveAI

All fictional. Consistent numbers so RAG answers and triage decisions are testable.

## Folders / files
- `kb/` — 15 knowledge-base articles (customer-facing how-to answers).
- `policies/` — fare rules (Saver/Flex/Business) + refund, delay-compensation, baggage, special-assistance, check-in policies. **This is the RAG grounding corpus.**
- `bookings.csv` / `bookings.json` — 302 bookings (PNRs). Includes 12 fixed "hero" PNRs (SN8801–SN8812) referenced by the eval set.
- `eval_scenarios.json` — 18 golden scenarios with expected outcomes (grow toward 50–100).

## bookings fields
pnr · passenger · flight_no · origin · destination · international · depart_datetime · booked_datetime ·
fare_class (Saver/Flex/Business) · price_inr · status (confirmed/completed/cancelled/no_show/delayed/cancelled_by_airline) ·
delay_minutes · checked_baggage_kg · account_age_days · prior_bookings · prior_refunds_90d · return_to_order_ratio · scenario_note

## How the build uses this
- **RAG corpus** = `kb/` + `policies/` → chunk → embed → Chroma. Retrieve, filtered by fare class where relevant.
- **get_booking(PNR)** (the MCP tool) reads `bookings.json`.
- **Triage** combines the booking facts + retrieved policy + risk signals (account_age, prior_refunds_90d, return_to_order_ratio, value) → verdict.
- **Evaluation** runs `eval_scenarios.json` and scores resolution / routing / grounding / escalation.

## Key policy numbers (single source of truth)
- Saver: non-refundable (taxes only); change ₹3,000; 15 kg. Flex: refundable −₹1,500 up to 2h; one free change; 25 kg. Business: full refund no fee up to 1h; free changes; 35 kg.
- 24h free cancellation if booked 7+ days before departure (all fares).
- Delay 2–3h → ₹500 meal voucher; 3h+ → full refund / rebook / 110% credit; 6h+/overnight → hotel+meals.
- Airline cancellation → full refund or rebook, any fare. No-show → taxes only.
- Excess baggage ₹600/kg. Lost-baggage liability ₹20,000; report within 7 days. Damaged: report in 24h.
