# Flagship Capstone — ResolveAI for SkyNova Airlines

**Product:** ResolveAI — the AI Travel Support Desk for **SkyNova Airlines** (a fictional full-service carrier).
**Format:** one end-to-end project, built the *spec-driven* way (problem → spec → design → build-with-AI → evaluate → deploy), deployed to **Google Cloud Run**.
**Why it exists:** it puts everything from Modules 0–9 into one real, resume-grade product, and teaches students *how to solve any problem* — not just how to copy code.

> Our own problem — not Flipkart, not e-commerce. It merges the two skills companies test — a **conversational assistant** and a **multi-agent decision system** — into a single premium product: airline customer support.

---

## 1. Problem Statement (the brief)

Airline support is where customer patience goes to die. A traveler messages in plain language — *"my flight got delayed 5 hours, do I get a refund?"*, *"I want to cancel SN-204 and get my money back,"* *"my bag didn't arrive."* Today a human agent must read the request, look up the **booking (PNR)**, find the right **fare rule** (a Saver ticket and a Flex ticket have completely different refund and change rights), check timing and value, and then decide: answer it now, route it to the right team, or escalate to a senior agent. It's slow, inconsistent, and — with fare rules and compensation policies — easy to get wrong. Two traps:

- **Over-automate with rigid rules** → a passenger owed a refund gets auto-rejected → complaints, brand damage.
- **Under-automate** → every request piles into a human queue → costs scale with passenger volume, travelers wait for hours.

**Your task:** build **ResolveAI**, SkyNova's AI Travel Support Desk — it behaves like an experienced airline support agent, *at the speed of an API call.*

It does two things as one product:

1. **Converse & resolve.** A chat assistant that understands the traveler's request, looks up their **actual booking**, and answers **strictly from SkyNova's knowledge base and fare/policy documents** — never a hallucinated refund amount, baggage allowance, or change fee. It **remembers the conversation** (so *"and my return flight?"* works without repeating the PNR), and asks a clarifying question when a detail (PNR, which passenger, which leg) is missing.
2. **Triage & decide.** When a request needs a decision the assistant can't safely make alone — a refund, a compensation claim, a baggage claim — it hands the case to a **multi-agent triage pipeline** that reads the booking, checks the **fare rule / policy via RAG**, scores value and risk, and returns a verdict: **Auto-resolve · Route-to-team · Escalate-to-human** — with an **explainable justification trail** citing the exact policy clause and signals, plus a summarized dossier when it escalates.

Every case action (look up a PNR, open a case, update it, assign a team, escalate) goes through **one shared Booking & Case system exposed over MCP**, reused by both the assistant and the triage orchestrator. Then you **deploy it to Google Cloud.**

---

## 2. The status-quo journey (the "before" — draw as a flowchart)

1. **Ask** — traveler describes the problem in natural language.
2. **Manual lookup** — agent finds the PNR, fare class, flight status.
3. **Policy hunt** — agent searches fare rules & compensation policy.
4. **The bottleneck** — grey-area cases (non-refundable disputes, high-value refunds, medical exceptions, delay compensation) pile into a manual queue.
5. **Decision** — resolve, route, or escalate — slow and inconsistent.

**The "after" with ResolveAI:** seconds instead of hours, most cases auto-resolved or auto-routed, and humans see only the genuinely hard cases — each with a ready-made dossier.

---

## 3. Scope — the issues ResolveAI handles

**Answer / troubleshoot (assistant + KB/policy RAG):**
baggage allowance & excess fees · web check-in window & gate closure · seat selection & upgrades · what each fare class includes · flight status · add-ons (meals, extra bag) · "what's my refund/change policy?"

**Decide / triage (multi-agent + policy RAG + escalation):**
- **Refund request** → check fare-class refundability + cancellation window → Auto-approve · Route to Refunds · Escalate (non-refundable dispute / high value / medical exception).
- **Change / reschedule** → change-fee eligibility per fare rules → resolve or route to Rebooking.
- **Delay / cancellation compensation** → check delay length vs policy → auto-credit, route, or escalate.
- **Baggage loss / damage claim** → route to Baggage team / escalate high-value.
- **Special assistance / medical / grievance** → escalate to human.
- **Abuse signal** (repeat refund abuse, chargeback risk) → escalate.

---

## 4. How it covers every module (the whole toolbox, on purpose)

| Module | How ResolveAI uses it |
|---|---|
| **M0 · Python & setup** | Env, Gemini key in secrets, typed + documented tool functions |
| **M1 · Agent fundamentals** | The assistant *is* an agent — LLM + tools + loop (ReAct); function calling runs the tools; its failure modes drive the guardrails |
| **M2 · The 5 patterns** | **Routing** (triage classifier), **Hierarchical/Multi-Agent** (orchestrator + specialists), **Autonomous** (resolve-or-escalate loop), **Sequential** (triage steps) — all five appear naturally |
| **M3 · ADK + memory** | Agents in ADK; **session memory** for multi-turn ("my return leg", "the same passenger") |
| **M4 · Prompt & context** | Few-shot **intent + entity extraction** (PNR, fare class, issue), **structured JSON** verdicts, grounding instructions, delimiters on free-text (injection defense) |
| **M5 · LangChain** | Loaders + splitters + retriever for the KB and fare/policy docs |
| **M6 · RAG** | Ground every answer and decision in the KB/fare rules — **no hallucinated refund, fee, or baggage allowance**; RAG evaluation |
| **M7 · MCP** | The **Booking & Case system is one MCP server** (get_booking, create_case, update_case, assign_team, escalate) reused by the assistant *and* the orchestrator — the textbook "write once, reuse everywhere" |
| **M8 · Deploy + guardrails + debug** | Deploy to **Google Cloud Run** (Docker — so MCP ships too), guardrails, and `adk web` tracing to debug the loop |
| **M9 · Interview mastery** | Whiteboard the architecture, defend the tradeoffs — a project you can *sell* |
| **+ Evaluation** | Resolution rate, routing accuracy, escalation calibration, grounding/hallucination rate, justification faithfulness, orchestration reliability |
| **+ Spec-driven design** | The entire method below — the real gap in most courses |

---

## 5. The spec-driven method (the lesson: how to solve *any* problem)

Students watch us build ResolveAI in this exact order — the transferable skill:

1. **Understand the problem** — user, pain, what "good" means (Sections 1–3).
2. **Write the spec** — requirements, the decisions the system makes, success metrics, constraints *before any code* (Sections 6–9).
3. **Design the architecture** — agent loop, multi-agent triage, RAG pipeline, MCP server, data model, UI — with a diagram (Section 7).
4. **Break into tasks** — a build plan, module by module (Section 10).
5. **Build with AI** — use **Antigravity / Claude** to implement each piece from the spec: describe → plan → build → verify.
6. **Evaluate** — run the metrics on a golden set; find weak spots; iterate (Section 9).
7. **Deploy** — ship to Google Cloud Run.
8. **Present** — tell the project story like an engineer (M9).

> The message: *"You don't start by writing code. You start by understanding the problem and writing a spec. AI writes the code — you own the thinking."*

---

## 6. Functional requirements

- **Intent + entity extraction** — map free text into a structured request (issue type, PNR, passenger, flight/leg, fare class, amount, sentiment/urgency).
- **Booking-grounded, policy-grounded answers** — pull the real booking and answer only from retrieved fare rules/KB; cite the source; if not covered, say so and offer to open a case.
- **Session memory** — resolve follow-ups ("and the return leg?") using prior turns.
- **Clarify on ambiguity** — ask one targeted question when a required detail is missing (which PNR? which passenger?).
- **Triage decision** — Auto-resolve / Route-to-team / Escalate-to-human, each with a justification citing the fare-rule/policy clause and the signals (fare class, time-to-departure, value, history).
- **Escalation dossier** — auto-written case summary for the human.
- **Shared Booking & Case system over MCP** — one server, two clients (assistant + orchestrator).
- **Guardrails** — validate input, redact PII (PNR, card, contact), cap steps/cost, never fabricate a policy, escalate when unsure.

## 7. Architecture (design → diagram)

```
                 ┌──────────────┐
 traveler chat ─▶│  Assistant   │  agent loop (ReAct) · session memory
                 │  Agent (ADK) │  tools: search_policy (RAG), get_booking (MCP), open_case (MCP)
                 └──────┬───────┘
     can answer safely? │  no / needs a decision / risky / ambiguous
     yes → grounded     ▼
     reply       ┌──────────────────────────┐
                 │  Triage Orchestrator      │  (Hierarchical / Multi-Agent)
                 │   • Intent Agent          │  classify + extract PNR/fare/issue (JSON)
                 │   • Policy Agent (RAG)     │  fare rule / refund / compensation clause
                 │   • Risk Agent            │  value + time-to-departure + history score
                 │   → Verdict + Justification│  Auto-resolve / Route / Escalate
                 └──────┬────────────────────┘
                        ▼
                 ┌───────────────────┐        ┌───────────────────────┐
                 │ Booking & Case    │◀──MCP──│ same server, 2 clients │
                 │ system (MCP)      │        │ (assistant + triage)  │
                 └───────────────────┘        └───────────────────────┘

  RAG corpus: KB articles + fare rules + refund/compensation/baggage policy → chunk → embed → Chroma
  UI: traveler chat + a reviewer view of the escalation queue          Deploy: Google Cloud Run
```

## 8. Tech stack

Python 3.11 · **Google Gemini** (`gemini-3.1-flash-lite`) · **Google ADK** for the agents · **LangChain** loaders/splitters/retriever · **Chroma** vector store · `gemini-embedding-001` embeddings · **FastMCP** for the Booking & Case MCP server · **Gradio** (traveler chat + reviewer view) · **Docker** → **Google Cloud Run**. (On Cloud Run we control the container, so — unlike the free-tier course deploy — MCP ships with it.)

## 9. Evaluation criteria (the metrics that prove it works)

1. **Resolution rate** — % of requests correctly closed by the assistant without a human.
2. **Routing accuracy** — % of cases sent to the correct team (Refunds / Rebooking / Baggage / Special Assistance).
3. **Escalation calibration** — high coverage of truly-hard cases escalated + high automation on clear ones.
4. **Grounding / hallucination rate** — % of factual claims (refund amount, fee, baggage allowance, compensation) traceable to a retrieved fare-rule/booking record (target: very low).
5. **Justification faithfulness** — does the reasoning cite the real fare clause + signals? (LLM-as-judge rubric.)
6. **Orchestration reliability** — % of runs where all agents complete, tools fire in order, and a structured verdict is produced in time.

Golden set: ~50–100 hand-authored scenarios — simple policy question, multi-turn ("return leg too"), ambiguous → clarify, refundable auto-approve, non-refundable → escalate, delay-compensation, baggage claim, abuse signal.

## 10. Build plan (milestones — one AI-assisted build session each)

1. **Spec & data** — this doc; generate SkyNova mock data: KB articles, fare rules (Saver/Flex/Business), refund/compensation/baggage policies, a bookings (PNR) dataset, and cases.
2. **RAG layer** — ingest KB + policies → Chroma → grounded `search_policy` tool.
3. **Assistant agent** — ADK agent, session memory, `search_policy` + `get_booking`, clarify-on-ambiguity.
4. **Booking & Case as MCP** — FastMCP server (get_booking / create / update / assign / escalate); wire into the assistant.
5. **Triage pipeline** — orchestrator + Intent/Policy/Risk agents → verdict + justification; reuse the *same* MCP server.
6. **Guardrails + escalation dossier** — input/PII checks, step/cost caps, human-in-the-loop.
7. **UI** — traveler chat + reviewer queue view.
8. **Evaluation harness** — golden set + the six metrics.
9. **Deploy** — Docker → Google Cloud Run.
10. **Present** — architecture whiteboard + tradeoffs (M9 style).

## 11. Deliverables

Working web app (chat + reviewer view) · the Booking & Case MCP server · RAG corpus + ingestion · the triage pipeline · a guardrails layer · an evaluation report (six metrics) · an architecture diagram · a README covering prompt/tool/RAG design · 3–5 annotated conversation transcripts · a failure-analysis note · a live Google Cloud URL.

---

*Next step: confirm this brief, then we generate the SkyNova mock data and build it module-by-module with AI, spec-first.*
