# ResolveAI — Per-Epic Build Prompts

One self-contained prompt per epic from `02_Feature_Breakdown_and_Backlog.md`. Paste one prompt as the *first* message in a fresh Claude Code session to build just that epic — this keeps each session's context small and its token usage low instead of building the whole system in one long-running conversation.

**How to use this file**

1. Open a new session in this same project folder (so `CLAUDE.md` auto-loads).
2. Check the **Build status** checklist in `CLAUDE.md` — start with the first unchecked epic whose prerequisites are already checked.
3. Copy that epic's prompt block below verbatim as your first message.
4. When the session finishes, make sure it checked the box in `CLAUDE.md` and noted any deviations before you close the session.

Epics 2 and 3 have no dependency on each other — run them in parallel sessions if you like. Everything from Epic 4 onward is sequential.

---

## Epic 0 — Repo & environment setup

```
Build Epic 0 from 02_Feature_Breakdown_and_Backlog.md: repo scaffold and environment setup.

Scope:
- Create the target repo structure under app/ described in CLAUDE.md (agents/, mcp_server/, rag/, guardrails/, ui/, store/ — empty packages with __init__.py is fine, later epics fill them in).
- requirements.txt (or pyproject.toml) with the fixed tech stack from CLAUDE.md — don't add packages outside that stack without flagging it to me.
- .env.example listing GEMINI_API_KEY and any other env vars named in 04_GCP_Deployment_Architecture.md (e.g. CASE_STORE_BACKEND).
- .gitignore covering venv, .env, chroma_db/, __pycache__.
- git init + initial commit if this isn't already a git repo (check first).

Out of scope: don't write any agent, MCP, RAG, or UI logic — this epic is scaffolding only.

Acceptance criteria (from the backlog): `pip install` succeeds; no secret literal in any tracked file; `git status` is clean after the initial commit.

When done, check the Epic 0 box in CLAUDE.md's Build status section.
```

---

## Epic 1 — Mock data: case store schema + eval set growth

```
Build Epic 1 from 02_Feature_Breakdown_and_Backlog.md. Note: the KB articles, fare/policy docs, and bookings dataset already exist under data/ — verify them against data/README.md but don't regenerate them. This epic has two real gaps to fill.

Scope:
1. Case store schema — read the Case entity shape in 01_Architecture_and_Design.md §4.2. Create data/cases.json seeded as an empty array, matching that schema exactly (this is the file the MCP server in Epic 3 will read/write against in local dev).
2. Golden eval set growth — data/eval_scenarios.json currently has 18 hand-authored scenarios. Grow it toward 50-100 per spec §9 / 02_Feature_Breakdown_and_Backlog.md Epic 1, keeping the existing entries and existing format (id, category, turns, pnr, expected, expected_team, notes). Cover all 8 required categories: simple policy question, multi-turn refinement, ambiguous→clarify, refundable auto-approve, non-refundable dispute→escalate, delay-compensation, baggage claim, abuse signal. Reference real PNRs from data/bookings.json (including but not limited to the 12 hero PNRs SN8801-SN8812) and real policy numbers from data/policies/ so scenarios are actually gradeable against ground truth.

Out of scope: don't write ingestion code, MCP server code, or agent code — this epic only touches data/.

Acceptance criteria: data/cases.json exists and matches the schema; eval_scenarios.json has 50+ entries covering all 8 categories.

When done, check the Epic 1 box in CLAUDE.md's Build status section.
```

---

## Epic 2 — RAG layer

```
Build Epic 2 from 02_Feature_Breakdown_and_Backlog.md: the RAG layer. Read 01_Architecture_and_Design.md §3.5 for the exact design (ingestion, embedding, retrieval, grounding contract).

Scope:
- Ingestion pipeline under app/rag/: LangChain loader + splitter over data/kb/*.md and data/policies/*.md. Attach metadata to every chunk: doc_type (kb | fare_rule | policy), fare_class (Saver | Flex | Business | null), source_file, topic.
- Embed with gemini-embedding-001, index into a single Chroma collection with metadata filtering (not separate collections per doc_type — see the architecture doc's stated recommendation).
- Implement the search_policy(query, fare_class=None, doc_type=None, k=4) tool function: returns ranked chunks with source_id, text, score.
- A small retrieval smoke test: 10 known query → expected-source pairs (you can write these from the actual data/kb and data/policies content), asserting >=90% top-2 hit rate.

Out of scope: don't wire this into the Assistant Agent or Orchestrator yet (that's Epic 4/5) — just build and test search_policy as a standalone, importable function.

Acceptance criteria: ingest script runs and produces chunks with 100% non-null metadata; index build completes in <30s; smoke test passes at >=90% hit rate.

When done, check the Epic 2 box in CLAUDE.md's Build status section.
```

---

## Epic 3 — Booking & Case MCP server

```
Build Epic 3 from 02_Feature_Breakdown_and_Backlog.md: the Booking & Case MCP server. Read 01_Architecture_and_Design.md §3.4 for the tool contracts and §4.1-4.2 for the Booking/Case schemas. This server is the single shared dependency for both the Assistant Agent (Epic 4) and the Triage Orchestrator (Epic 5) — build it standalone and well-tested now so neither of those epics has to touch this code later.

Scope:
- FastMCP server under app/mcp_server/ exposing exactly 6 tools: get_booking(pnr), create_case(pnr, issue_type, summary, conversation_id), update_case(case_id, status=None, verdict=None, justification=None), assign_team(case_id, team), escalate(case_id, dossier), get_status(case_id).
- get_booking reads data/bookings.json.
- The case tools read/write through a CaseStore interface (app/store/) with a local-JSON implementation backed by data/cases.json (the file Epic 1 seeded) — design this interface so a Firestore implementation can be swapped in later per 04_GCP_Deployment_Architecture.md §8, but only build the local-JSON one now.
- A dual-client smoke test: instantiate two independent MCP clients concurrently (simulating the Assistant Agent and the Orchestrator) and confirm they can read/write without state corruption.

Out of scope: don't build the Firestore implementation, don't wire this into any agent yet.

Acceptance criteria: server starts and lists all 6 tools; get_booking returns correct records for all 12 hero PNRs (SN8801-SN8812) and a clean not-found for an unknown PNR; create->update->get_status round-trips correctly; dual-client test passes.

When done, check the Epic 3 box in CLAUDE.md's Build status section.
```

---

## Epic 4 — Assistant Agent

```
Build Epic 4 from 02_Feature_Breakdown_and_Backlog.md: the Assistant Agent. Prerequisites: Epic 2 (RAG / search_policy) and Epic 3 (MCP server) must already exist — read what's there before writing new code. Read 01_Architecture_and_Design.md §3.2 for the full loop logic and §5.1-5.3 for the required conversation flows.

Scope:
- ADK ReAct agent under app/agents/ with four tools wired in: search_policy (Epic 2), get_booking, open_case, get_status (Epic 3, as MCP client calls).
- Few-shot intent + entity extraction prompt producing structured JSON: issue_type, pnr, passenger, flight_leg, fare_class, amount, urgency.
- Session memory: persist pnr_in_focus, passenger_in_focus, last_leg, open_case_ids, turn_history per conversation (see the Session schema in 01_Architecture_and_Design.md §4.3).
- Clarify-on-ambiguity: when a required slot is missing, ask exactly one targeted question and stop — don't guess or call a tool.
- Grounded answer generation: only state a fact if it's in a retrieved chunk, with inline citation.
- Handoff logic: when the issue needs a decision (refund, change-fee dispute, delay compensation, baggage claim, special assistance, suspected abuse), call open_case and stop there — do NOT implement the actual triage decision in this epic, that's Epic 5. For now, handoff can be a stub call/interface that Epic 5 will fill in; get the case opened and the interface point correct.

Out of scope: don't implement the Triage Orchestrator itself (Epic 5), don't build guardrails (Epic 6) beyond what's needed to not crash, don't build the UI (Epic 7).

Acceptance criteria: >=90% field-level accuracy on a 20-example hand-labeled extraction set you write; the "return leg too" scenario (see eval_scenarios.json E03) resolves without re-asking the PNR; a no-PNR/no-issue scenario triggers exactly one clarifying question; a decision-requiring scenario results in a case id via open_case.

When done, check the Epic 4 box in CLAUDE.md's Build status section.
```

---

## Epic 5 — Triage Orchestrator

```
Build Epic 5 from 02_Feature_Breakdown_and_Backlog.md: the multi-agent Triage Orchestrator. Prerequisite: Epic 3 (MCP server) and Epic 4 (Assistant Agent, for the handoff interface point) must already exist. Read 01_Architecture_and_Design.md §3.3 in full — it has the sequence diagram, the three specialists' responsibilities, the deterministic verdict rule table, and the exact justification JSON schema. This is the most decision-critical epic — follow that schema exactly, don't improvise a different shape.

Scope:
- Three specialist agents under app/agents/: Intent Agent (second-opinion classifier into the fixed issue types, with confidence — must handle sarcastic/evasive phrasing per the spec's stress-test data), Policy Agent (RAG lookup scoped to the booking's fare class + issue type, returns clause text + source_id — never a paraphrase without a citation), Risk Agent (deterministic score from price_inr, days-to-departure, account_age_days, prior_bookings, prior_refunds_90d, return_to_order_ratio).
- Coordinator that runs the three specialists (in parallel where possible) and applies the deterministic rule table from §3.3 to produce one of: auto_resolve, route, escalate.
- Verdict output exactly matching the JSON schema in §3.3, written via update_case.
- On escalate: also call assign_team and escalate(dossier) with an auto-written human-readable dossier (booking facts + policy clause + risk signals + the traveler's original text).
- Wire this into the Epic 4 handoff stub so the Assistant Agent actually gets a verdict back and can relay it.

Out of scope: don't build guardrails (Epic 6) or the UI (Epic 7).

Acceptance criteria: all scenarios in data/eval_scenarios.json produce the expected verdict category; justification always has a non-null policy_clause; a known high-abuse-signal profile correctly sets abuse_flag=true; verdict JSON validates against the schema in 01_Architecture_and_Design.md §3.3.

When done, check the Epic 5 box in CLAUDE.md's Build status section.
```

---

## Epic 6 — Guardrails

```
Build Epic 6 from 02_Feature_Breakdown_and_Backlog.md: the guardrails layer. Prerequisites: Epics 4 and 5 must already exist — this epic wraps them, it doesn't replace anything. Read 01_Architecture_and_Design.md §3.6.

Scope, under app/guardrails/:
- Input validation: length caps, control-character stripping, basic prompt-injection pattern rejection on user free text before it's placed into any tool-call argument.
- PII redaction: regex-based redaction of PNR (SN\d{4} pattern), card-like digit sequences, email/phone — applied before any logging and before non-essential dossier fields are written.
- Step/cost caps: max 4 tool calls / 12s wall clock on the Assistant Agent loop (Epic 4); max 1 pass per specialist / 20s wall clock on the Orchestrator (Epic 5). On cap trip, fall back to escalation rather than hanging or erroring.
- Anti-hallucination check: post-hoc match of any numeric claim (₹, kg, hours) in an assistant reply against the retrieved chunk(s) it cited; on mismatch, regenerate once, then escalate if it still fails.
- Wire all of the above into the Epic 4 and Epic 5 code paths — this epic is incomplete if it's just standalone functions nobody calls.

Out of scope: don't build the UI (Epic 7).

Acceptance criteria: adversarial injection test strings are neutralized, not executed as instructions; PII redaction unit tests pass with zero raw PII in log output; a forced-timeout scenario falls back to escalation without hanging; an injected wrong-number test case is caught and escalated.

When done, check the Epic 6 box in CLAUDE.md's Build status section.
```

---

## Epic 7 — UI

```
Build Epic 7 from 02_Feature_Breakdown_and_Backlog.md: the Gradio UI. Prerequisites: Epics 3-6 should already exist. Read 03_UI_UX_Design.md in full — it has the exact layout, component list, and UI-to-backend call mapping for both tabs.

Scope, under app/ui/:
- One Gradio Blocks app, two tabs, sharing the same backend session/case objects in-process (not two separate apps).
- Traveler Chat tab: gr.Chatbot, message input, session context sidebar (pnr_in_focus, passenger, fare class, flight, open case id), inline citation chips on assistant messages, a case-opened banner that appears when open_case fires, showing the case id and (once available) the verdict.
- Reviewer Queue tab: filterable case table (status, team, PNR search), row-click detail panel rendering the full justification trail + dossier from the verdict JSON schema, action buttons (Approve / Deny / Reassign / Mark resolved) that call update_case/assign_team through the same MCP server the agents use, and a link to view the originating chat transcript.
- Wire the send/refresh loops to the Assistant Agent (Epic 4) and the case store (Epic 3) per the mapping table at the end of 03_UI_UX_Design.md.

Out of scope: don't build the evaluation harness (Epic 8) or deployment (Epic 9).

Acceptance criteria: run 5 golden scenarios from eval_scenarios.json manually through the chat tab and confirm expected behavior; opening a case in the chat tab makes it visible in the reviewer tab without restarting the app; an approve/deny action in the reviewer tab is reflected in the case's audit trail.

When done, check the Epic 7 box in CLAUDE.md's Build status section.
```

---

## Epic 8 — Evaluation harness

```
Build Epic 8 from 02_Feature_Breakdown_and_Backlog.md: the evaluation harness. Prerequisites: Epics 4-6 (the full agent pipeline) should already exist. Read spec §9 in 00_Problem_Statement_and_Spec.md and the Epic 8 row in 02_Feature_Breakdown_and_Backlog.md for the six metric definitions.

Scope, under eval/:
- A scenario runner that executes every entry in data/eval_scenarios.json against the live agent pipeline (not the UI — call the Assistant Agent/Orchestrator directly), capturing the full transcript and final case state per scenario.
- Compute and report all six metrics: resolution rate, routing accuracy, escalation calibration, grounding/hallucination rate (target <2%), justification faithfulness (0-3 LLM-as-judge rubric), orchestration reliability.
- Generate eval/report.md summarizing all six metrics plus a list of failing/borderline scenarios with enough detail to debug them.

Out of scope: don't fix bugs the harness surfaces as part of this epic unless they're trivial — flag them for a follow-up session instead, since fixing agent logic belongs to Epics 4-6's scope.

Acceptance criteria: harness runs headlessly against the full eval set and produces one result record per scenario; eval/report.md exists with all six metrics computed.

When done, check the Epic 8 box in CLAUDE.md's Build status section.
```

---

## Epic 9 — Deployment

```
Build Epic 9 from 02_Feature_Breakdown_and_Backlog.md: containerize and deploy to Google Cloud Run. Prerequisites: the full app (Epics 0-7 at minimum) should already exist and run locally. Read 04_GCP_Deployment_Architecture.md in full — it has the exact topology, Dockerfile design, IAM roles, and a step-by-step runbook. Follow that runbook; don't improvise a different topology.

Scope:
- Multi-stage Dockerfile per §3: stage 1 installs deps and pre-builds the Chroma index from the bundled corpus, stage 2 is the slim runtime image. Entrypoint starts the MCP server then the Gradio app on $PORT.
- Implement the Firestore CaseStore backend (the interface was set up in Epic 3) behind the same CASE_STORE_BACKEND env var switch described in CLAUDE.md / §8, so local dev still uses the JSON backend.
- Follow the deployment runbook in §9 of that doc: enable APIs, create the Firestore database, create the resolveai-run-sa service account with the two roles in §4, store GEMINI_API_KEY in Secret Manager, push the image to Artifact Registry, deploy with the flags in §6 (min/max instances, concurrency, timeout per §5).
- Smoke-test the live URL against 2-3 golden scenarios from eval_scenarios.json before calling it done.

This step involves creating real cloud resources and a public URL — confirm project id, billing, and region with me before running anything that provisions or deploys, per the standing rule about hard-to-reverse or externally-visible actions.

Acceptance criteria: live HTTPS URL responds; a chat flow works end-to-end against the deployed instance; a case created via the deployed UI persists across a Cloud Run instance restart; no secret literal anywhere in the image or service config.

When done, check the Epic 9 box in CLAUDE.md's Build status section and record the live URL there too.
```

---

## Epic 10 — Documentation & presentation

```
Build Epic 10 from 02_Feature_Breakdown_and_Backlog.md: final documentation deliverables. Prerequisites: Epics 8 and 9 should already exist (need real eval results and a live URL to document).

Scope:
- README.md covering prompt engineering approach, tool design, RAG design, and setup/deploy instructions — written so a new reader can run the app locally from the README alone.
- 3-5 annotated conversation transcripts (pulled from real runs, not invented) demonstrating: query refinement, coreference resolution, grounded answering with citation, and an escalation with its full dossier. Annotate inline what each transcript is demonstrating.
- A failure analysis note documenting at least 3 concrete cases from the Epic 8 eval run where the system underperformed or failed to ground (ambiguous intent, sarcastic reasons, policy edge cases, missing PNR are the categories called out in the spec) — root cause each one.
- Confirm the architecture diagram (already in 01_Architecture_and_Design.md and the published ResolveAI Blueprint artifact) and the live URL (from Epic 9) are both linked from the README.

Acceptance criteria: README alone is sufficient to run the app locally; each transcript has inline annotations; at least 3 documented failure cases with root cause; live URL confirmed working from the README link.

When done, check the Epic 10 box in CLAUDE.md's Build status section.
```
