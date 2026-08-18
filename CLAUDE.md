# ResolveAI — SkyNova Airlines AI Travel Support Desk

Project instructions for any Claude Code session working in this repo. This file is auto-loaded every session — the per-epic build prompts in `05_Build_Prompts.md` intentionally don't repeat what's here.

## What this project is

ResolveAI is a two-in-one product: a grounded conversational assistant (answers from SkyNova's KB/fare/policy docs, never hallucinated) fused with a multi-agent triage pipeline (Auto-resolve / Route-to-team / Escalate-to-human, with an explainable justification trail). Both halves share one Booking & Case system exposed over MCP. Deploys to Google Cloud Run.

Full requirements: `ResolveAI_Capstone_Challenge.pdf` + `00_Problem_Statement_and_Spec.md` (spec is the faithful, build-ready expansion of the PDF — confirmed matching, no conflicts).

## Read before you build

| Doc | Read it when touching |
|---|---|
| `00_Problem_Statement_and_Spec.md` | Anything — the source requirements |
| `01_Architecture_and_Design.md` | Agent logic, MCP tool contracts, RAG design, data model, guardrails |
| `02_Feature_Breakdown_and_Backlog.md` | Scoping any epic — task list + acceptance criteria per feature |
| `03_UI_UX_Design.md` | The Gradio UI (chat tab + reviewer queue tab) |
| `04_GCP_Deployment_Architecture.md` | Docker, Cloud Run, Firestore, Secret Manager, CI/CD |
| `05_Build_Prompts.md` | Per-epic prompts for starting a fresh session on one piece of the system |
| `data/README.md` | The existing mock dataset (bookings, KB, policies, eval scenarios) — don't regenerate what's already there |

## Tech stack (fixed — don't substitute without asking)

Python 3.11 · Google Gemini (`gemini-3.1-flash-lite`) · Google ADK (agents) · LangChain (loaders/splitters/retriever) · Chroma (vector store) · `gemini-embedding-001` (embeddings) · FastMCP (Booking & Case server) · Gradio (UI) · Docker → Google Cloud Run · Firestore (cases/sessions, prod only).

## Non-negotiables

- **Never fabricate a policy fact.** Every price/fee/allowance/refund claim must trace to a retrieved chunk. If retrieval finds nothing relevant, say so and offer to open a case — don't guess.
- **One shared Booking & Case system.** Both the Assistant Agent and the Triage Orchestrator are MCP clients of the *same* FastMCP server — never a second implementation of booking/case logic.
- **Triage is not a single prompt.** The Orchestrator runs three specialist agents (Intent, Policy/RAG, Risk) whose outputs feed a deterministic rule table (see `01_Architecture_and_Design.md` §3.3) — the LLM classifies and writes prose justification, it doesn't freelance the verdict category.
- **Every verdict is explainable.** The justification schema (§3.3 of the architecture doc) always includes a `policy_clause` citation and the signals used — never a bare verdict.
- **Guardrails trip to escalation, never to a dead end.** Timeouts, injection attempts, and hallucination-check failures all route to a human case, not an error screen or a dropped request.

## Target repo structure

```
app/
  agents/        Assistant Agent (ADK ReAct loop) + Triage Orchestrator (Intent/Policy/Risk specialists)
  mcp_server/     FastMCP Booking & Case server (get_booking, create_case, update_case, assign_team, escalate, get_status)
  rag/            Ingestion, Chroma index build, search_policy tool
  guardrails/     Input validation, PII redaction, step/cost caps, anti-hallucination check
  ui/             Gradio app — traveler chat tab + reviewer queue tab
  store/          CaseStore interface: local JSON (dev) / Firestore (prod), selected by env var
data/             Existing mock dataset — kb/, policies/, bookings.json/.csv, eval_scenarios.json
eval/             Evaluation harness + generated report
Dockerfile
requirements.txt / pyproject.toml
.env.example
```

Nothing under `app/` exists yet — epics build it incrementally. Check what's already there before writing new code; don't recreate or conflict with a prior epic's work.

## Conventions

- Secrets via env vars only (`GEMINI_API_KEY`), never hardcoded. `.env` is gitignored.
- Case store is behind one `CaseStore` interface so local dev (JSON/SQLite) and Cloud Run (Firestore) share the same calling code — see `04_GCP_Deployment_Architecture.md` §8.
- Bookings data (`data/bookings.json`) is static and read-only — don't add a write path to it.
- Keep the verdict JSON schema in `01_Architecture_and_Design.md` §3.3 as the contract — if a build session needs to change it, update that doc in the same session.

## Running & testing locally

- `adk web` for tracing the agent loop during development.
- Local case store defaults to a JSON file under `data/cases.json` unless `CASE_STORE_BACKEND=firestore` is set.
- Evaluation harness: run against `data/eval_scenarios.json`, report in `eval/report.md`.

## Build status

Update the box for your epic when its acceptance criteria (per `02_Feature_Breakdown_and_Backlog.md`) are met. Leave a one-line note if you deviated from a design doc, so the next session isn't surprised.

- [x] Epic 0 — Repo & environment setup
- [ ] Epic 1 — Mock data (case store schema + eval set growth — bookings/KB/policies already exist)
- [ ] Epic 2 — RAG layer
- [ ] Epic 3 — Booking & Case MCP server
- [ ] Epic 4 — Assistant Agent
- [ ] Epic 5 — Triage Orchestrator
- [ ] Epic 6 — Guardrails
- [ ] Epic 7 — UI
- [ ] Epic 8 — Evaluation harness
- [ ] Epic 9 — Deployment
- [ ] Epic 10 — Documentation & presentation

## Multi-session workflow

This project is built across separate Claude Code sessions, one epic at a time, to keep each session's context small. Each epic has a ready-to-paste starting prompt in `05_Build_Prompts.md`. Since this file loads automatically, those prompts don't restate the stack, non-negotiables, or repo layout — they only state that epic's scope. Before starting work in any session: check the **Build status** checklist above so you know what already exists.
