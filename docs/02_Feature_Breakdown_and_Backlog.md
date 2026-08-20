# ResolveAI — Feature Breakdown & Build Backlog

Breaks [00_Problem_Statement_and_Spec.md](00_Problem_Statement_and_Spec.md) §10 (build plan) and [01_Architecture_and_Design.md](01_Architecture_and_Design.md) into epics → features → tasks with acceptance criteria, so each milestone is a single AI-assisted build session with a clear "done" line. Ordered by dependency — later epics assume earlier ones are done.

---

## Epic 0 — Repo & environment setup
*Maps to spec milestone 1 (partial), Module M0.*

| Feature | Tasks | Acceptance criteria |
|---|---|---|
| Project scaffold | `pyproject.toml`/`requirements.txt`, `.env.example` with `GEMINI_API_KEY`, folder layout (`app/agents`, `app/mcp_server`, `app/rag`, `app/ui`, `app/guardrails`, `data/`, `eval/`) | `pip install -e .` succeeds; app boots with a placeholder "hello" endpoint |
| Secrets handling | Load Gemini key from env, never hardcoded; `.env` gitignored | No secret present in any tracked file (grep check) |
| Git init | `git init`, initial commit, `.gitignore` (venv, `.env`, `chroma_db/`, `__pycache__`) | `git status` clean after commit |

---

## Epic 1 — Mock data (already largely done)
*Maps to spec milestone 1. Data already exists under `data/`; this epic is verification + the one gap.*

| Feature | Tasks | Acceptance criteria |
|---|---|---|
| KB articles | Verify 15 articles cover baggage, check-in, seats, add-ons, flight status | ✅ present (`data/kb/*.md`, 15 files) |
| Fare rules + policies | Verify Saver/Flex/Business + refund/delay/baggage/special-assistance docs | ✅ present (`data/policies/*.md`) |
| Bookings dataset | Verify 302 PNRs incl. 12 hero PNRs SN8801–SN8812 | ✅ present (`data/bookings.json/.csv`) |
| **Case store schema (gap)** | Define `cases.json`/Firestore schema per [01_Architecture_and_Design.md](01_Architecture_and_Design.md) §4.2; seed empty store | New file `data/cases.json` (dev) exists with `[]` and matches schema |
| Golden eval set | Grow `eval_scenarios.json` from 18 → 50–100 per spec §9 | File has ≥50 entries covering all 8 required categories (policy_qa, multi_turn, clarify, auto-approve, escalate-nonrefundable, delay-comp, baggage, abuse) |

---

## Epic 2 — RAG layer
*Maps to spec milestone 2.*

| Feature | Tasks | Acceptance criteria |
|---|---|---|
| Ingestion pipeline | LangChain loader + splitter over `data/kb` + `data/policies`; attach metadata (`doc_type`, `fare_class`, `source_file`) | Running the ingest script produces N chunks with non-null metadata for 100% of chunks |
| Embedding + index | `gemini-embedding-001` → Chroma collection, persisted locally for dev | Index build completes < 30s on the full corpus |
| `search_policy` tool | Query + optional `fare_class`/`doc_type` filters → top-k ranked chunks with `source_id` | Unit test: query "excess baggage fee" returns `policy_baggage.md` chunk in top-2 |
| Retrieval eval smoke test | 10 known Q→expected-source pairs | ≥90% hit rate on the known set before moving on |

---

## Epic 3 — Booking & Case MCP server
*Maps to spec milestone 4 (built early since both agents depend on it — see dependency note below).*

> **Sequencing note:** the spec lists MCP as milestone 4, after the Assistant Agent (3). In practice, build the MCP server *before* wiring either agent, since both the Assistant Agent and the Orchestrator are MCP clients — this backlog reorders it earlier to avoid a rework pass. Functionally equivalent to the spec; only the build order differs.

| Feature | Tasks | Acceptance criteria |
|---|---|---|
| FastMCP server skeleton | Server process exposing the 6 tools from [01_Architecture_and_Design.md](01_Architecture_and_Design.md) §3.4 | Server starts; MCP client can list tools |
| `get_booking` | Reads `bookings.json` by PNR | Returns correct record for all 12 hero PNRs; 404-equivalent for unknown PNR |
| `create_case` / `update_case` / `get_status` | CRUD against case store | Round-trip test: create → update status → get_status reflects change |
| `assign_team` / `escalate` | Writes team/escalation fields, dossier | Escalated case appears with non-null dossier field |
| Dual-client smoke test | Connect two independent MCP clients (simulating Assistant + Orchestrator) concurrently | Both clients can read/write without state corruption |

---

## Epic 4 — Assistant Agent (ADK, ReAct)
*Maps to spec milestone 3.*

| Feature | Tasks | Acceptance criteria |
|---|---|---|
| Intent + entity extraction | Few-shot prompt → structured JSON (`issue_type, pnr, passenger, flight_leg, fare_class, amount, urgency`) | ≥90% field-level accuracy on a 20-example hand-labeled set |
| Tool-using agent loop | Wire `search_policy`, `get_booking`, `open_case`, `get_status` as ADK tools | Agent correctly chooses `search_policy` vs `get_booking` vs both across 10 scripted scenarios |
| Session memory | Persist `pnr_in_focus`, `last_leg`, `open_case_ids`, turn history | E03-style scenario ("return leg too") resolves without re-asking PNR |
| Clarify-on-ambiguity | Detect missing required slot → ask one targeted question, don't guess | Scenario with no PNR/issue triggers exactly one clarifying question, not a tool call |
| Grounded answer generation | Answer only from retrieved chunks, inline citation | Manual spot-check: every numeric claim traces to a chunk |
| Handoff to Orchestrator | When issue requires a decision, open case + invoke Orchestrator (Epic 5), relay verdict | Refund-type request results in a case id + a final verdict-based reply, not an assistant-invented answer |

---

## Epic 5 — Triage Orchestrator (multi-agent)
*Maps to spec milestone 5.*

| Feature | Tasks | Acceptance criteria |
|---|---|---|
| Intent Agent (specialist) | Second-opinion classifier into fixed issue types + confidence | Correctly reclassifies at least the sarcastic/evasive stress-test examples the Assistant misreads |
| Policy Agent (specialist) | RAG lookup scoped to booking's fare class + issue type, returns clause + `source_id` | Verdict justification always contains a non-null `policy_clause` |
| Risk Agent (specialist) | Score from `price_inr`, days-to-departure, `account_age_days`, `prior_refunds_90d`, `return_to_order_ratio` | Deterministic unit tests: known high-abuse profile → `abuse_flag=true` |
| Coordinator + verdict rule table | Combine specialist outputs via the rule table in [01_Architecture_and_Design.md](01_Architecture_and_Design.md) §3.3 | All 18(+) golden scenarios produce the expected verdict category |
| Verdict + justification schema | Emit the JSON schema from §3.3, write via `update_case` | Schema validates against a JSON Schema definition; no missing required fields |
| Dossier generation | Auto-written human-readable summary on escalate | Dossier includes booking facts, policy clause, risk signals, and the traveler's original text |

---

## Epic 6 — Guardrails
*Maps to spec milestone 6.*

| Feature | Tasks | Acceptance criteria |
|---|---|---|
| Input validation | Length caps, control-char stripping, basic injection-pattern rejection | Adversarial test strings (from M4 injection-defense examples) are neutralized, not executed as instructions |
| PII redaction | Regex-based redaction of PNR/card/contact in logs and non-essential dossier fields | Redaction unit tests pass; raw PII never appears in log output |
| Step/cost caps | Max tool calls + wall-clock timeout on both Assistant loop and Orchestrator pass | Forced-timeout scenario falls back to escalation, doesn't hang or error |
| Anti-hallucination check | Post-hoc numeric-claim vs. retrieved-chunk match | Injected "wrong number" test case is caught and regenerated/escalated |
| Human-in-the-loop fallback | Any guardrail trip routes to escalation, never a silent failure | 100% of guardrail-triggered paths produce a case, not a dropped request |

---

## Epic 7 — UI
*Maps to spec milestone 7. Full detail in [03_UI_UX_Design.md](03_UI_UX_Design.md).*

| Feature | Tasks | Acceptance criteria |
|---|---|---|
| Traveler chat tab | Gradio chat + session context panel + citation display + case-opened banner | Manual run of 5 golden scenarios end-to-end in the UI matches expected behavior |
| Reviewer queue tab | Filterable case table + case detail drawer (dossier, justification, actions) | Escalated case from Epic 5 appears in queue within one refresh cycle |
| Human actions | Approve / override verdict / reassign team / mark resolved, writes back via MCP | Action updates case store and is reflected in the case's audit trail |
| Shared session/case store wiring | Both tabs read the same backend state | Opening a case in chat tab immediately shows it in reviewer tab (same store) |

---

## Epic 8 — Evaluation harness
*Maps to spec milestone 8, spec §9 metrics.*

| Feature | Tasks | Acceptance criteria |
|---|---|---|
| Scenario runner | Executes `eval_scenarios.json` turns against the live app, captures transcript + final state | Runs headlessly, produces one result record per scenario |
| Metric: resolution rate | % correctly closed without human | Computed and reported per run |
| Metric: routing accuracy | % routed to correct team | Computed and reported per run |
| Metric: escalation calibration | Hard cases escalated vs. clear cases auto-decided | Computed and reported per run |
| Metric: grounding/hallucination rate | % of numeric claims traceable to a retrieved chunk (target <2%) | Computed and reported per run |
| Metric: justification faithfulness | 0–3 LLM-as-judge rubric vs. real clause + signals | Computed and reported per run |
| Metric: orchestration reliability | % runs where all specialists complete + verdict produced in time | Computed and reported per run |
| Evaluation report | Markdown/HTML report with all six metrics + failure examples | Report file generated in `eval/report.md` |

---

## Epic 9 — Deployment
*Maps to spec milestone 9. Full detail in [04_GCP_Deployment_Architecture.md](04_GCP_Deployment_Architecture.md).*

| Feature | Tasks | Acceptance criteria |
|---|---|---|
| Dockerfile | Single-image build: UI + agents + MCP server + Chroma build step | `docker build` succeeds; `docker run` serves the UI locally |
| Cloud Run deploy | `gcloud run deploy` with env vars/secrets wired | Live HTTPS URL responds; chat flow works end-to-end against deployed instance |
| Firestore wiring | Case/session persistence swapped from local file to Firestore in prod config | Case created via deployed UI persists across a Cloud Run instance restart |
| Secret Manager | `GEMINI_API_KEY` mounted from Secret Manager, not env literal | No secret value present in Cloud Run service YAML or image layers |
| CI/CD (stretch) | Cloud Build trigger on push → build → deploy | Push to `main` results in a new revision without manual `gcloud` command |

---

## Epic 10 — Documentation & presentation
*Maps to spec milestone 10, deliverables in spec §11.*

| Feature | Tasks | Acceptance criteria |
|---|---|---|
| README | Prompt/tool/RAG design + deploy instructions | A new reader can run the app locally from the README alone |
| Architecture diagram | Exported from [01_Architecture_and_Design.md](01_Architecture_and_Design.md) | Included in README/submission |
| Transcript samples | 3–5 annotated conversations (refinement, coreference, grounding, escalation+dossier) | Each transcript has inline annotations explaining what's being demonstrated |
| Failure analysis note | Document ambiguous-intent, sarcastic-reason, policy-edge-case, missing-PNR failures found during Epic 8 | At least 3 concrete documented failure cases with root cause |
| Live URL | Cloud Run URL in README | URL resolves to the working app |

---

## Suggested critical path

```
Epic 0 → Epic 1 → Epic 2 (RAG) ─┐
                   Epic 3 (MCP) ─┼→ Epic 4 (Assistant) → Epic 5 (Orchestrator) → Epic 6 (Guardrails)
                                 ┘                                                      │
                                                                                         ▼
                                                                    Epic 7 (UI) → Epic 8 (Eval) → Epic 9 (Deploy) → Epic 10 (Docs)
```

Epics 2 and 3 have no dependency on each other and can be built in parallel (RAG needs only the corpus; MCP needs only the bookings/case schema).
