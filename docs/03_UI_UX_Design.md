# ResolveAI — UI/UX Design

One Gradio web app, two tabs, one shared backend state (session store + case store). This is the "UI to run the workflow" — a traveler can hold a full conversation and trigger triage, and a reviewer can watch and act on the resulting queue, in the same running app.

---

## 1. Information architecture

```
ResolveAI (single Gradio Blocks app, single Cloud Run service)
├── Tab 1: Traveler Chat        ← the "converse & resolve" half of the spec
└── Tab 2: Reviewer Queue       ← the "triage & decide" half, human-in-the-loop
```

Both tabs call the same Python backend objects (Assistant Agent, Orchestrator, MCP client) in-process — there is no separate frontend/backend deployment to keep in sync.

---

## 2. Tab 1 — Traveler Chat

### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  ResolveAI · SkyNova Travel Support                    [PNR: —] │
├───────────────────────────────────────┬───────────────────────┤
│                                         │  Session context       │
│   [assistant] Hi! How can I help       │  ──────────────────    │
│   with your SkyNova booking today?     │  PNR: SN8804            │
│                                         │  Passenger: —           │
│   [you] I'm on SN8804, can I change    │  Fare class: Flex        │
│   my flight?                            │  Flight: SN-624          │
│                                         │  Open case: —            │
│   [assistant] Your Flex fare includes  │  ──────────────────    │
│   one free change. Since you've used   │  Sources cited:          │
│   it, a second change costs ₹3,000.    │  • fare_rules_flex.md    │
│   [source: fare_rules_flex.md] Want    │                          │
│   me to proceed?                       │                          │
│                                         │                          │
│   [you] What about my return leg too?  │                          │
│                                         │                          │
│   [assistant] Same Flex rule applies   │                          │
│   to the return leg — one free change  │                          │
│   already used there too.              │                          │
│   [source: fare_rules_flex.md]         │                          │
│                                         │                          │
│  ┌───────────────────────────────────┐│                          │
│  │ Type your message...        [Send]││                          │
│  └───────────────────────────────────┘│                          │
└─────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Gradio building block | Behavior |
|---|---|---|
| Chat window | `gr.Chatbot` | Renders assistant/traveler turns; assistant messages render citation chips inline (`[source: file.md]` as styled markdown, not a bare filename) |
| Message input | `gr.Textbox` + `gr.Button("Send")` | Submits to Assistant Agent; disabled while a response is streaming |
| Session context panel | `gr.Markdown`/`gr.JSON`, right sidebar | Live view of `pnr_in_focus`, passenger, fare class, flight, open case id — updates after every turn so the traveler (and a developer debugging) can see what the agent "remembers" |
| Clarifying-question state | Same chat window | No separate UI — a clarifying question is just an assistant turn; the send box stays focused so the traveler can answer immediately |
| Case-opened banner | `gr.Markdown` banner above chat, appears conditionally | "Case CASE-000123 opened — [Auto-resolved ✅ / Routed to Refunds → / Escalated to a human reviewer ⚠]" with the verdict's one-line justification |
| Sources-cited list | `gr.Markdown`, sidebar | Running list of every `source_id` cited this session, for transparency |

### Key interaction flows

- **Grounded answer:** user asks → assistant replies inline in the chat, citation chip attached, sidebar's "Sources cited" grows. No case is opened.
- **Clarify:** user's request is missing a required slot → assistant's next chat turn *is* the clarifying question. No modal, no separate form — keeps it conversational per spec requirement.
- **Triage handoff:** user's request needs a decision → banner appears above the chat with the case id and verdict as soon as the Orchestrator returns; the assistant's chat reply explains the verdict in plain language. If escalated, the banner also says "a specialist will follow up" and the case is now visible in Tab 2.

---

## 3. Tab 2 — Reviewer Queue

### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  Reviewer Queue                                                  │
│  Filter: [Status: Escalated ▾] [Team: All ▾] [Search PNR/case]   │
├─────────────────────────────────────────────────────────────────┤
│  Case ID       PNR      Issue            Team        Status      │
│  CASE-000119   SN8802   refund (Saver)   Refunds     Escalated ▶ │
│  CASE-000121   SN8807   baggage_claim    Baggage     Escalated ▶ │
│  CASE-000123   SN8804   change_fee       Rebooking   Routed    ▶ │
├─────────────────────────────────────────────────────────────────┤
│  ▼ CASE-000119 detail                                            │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ Booking: SN8802 · Diya Rao · Saver · SN-505 · ₹4,300        │ │
│  │ Issue: refund request (non-refundable dispute)              │ │
│  │                                                                │ │
│  │ Justification trail                                          │ │
│  │  • Policy: fare_rules_saver.md — "non-refundable, taxes only" │ │
│  │  • Risk signals: value=₹4,300 (low), prior_refunds_90d=1,     │ │
│  │    return_to_order_ratio=0.03 (low), no abuse flag            │ │
│  │  • Reasoning: Saver is non-refundable; traveler disputes —    │ │
│  │    needs human judgment call, not auto-rejectable.             │ │
│  │                                                                │ │
│  │ Dossier (auto-written)                                        │ │
│  │  "Traveler requests refund on non-refundable Saver fare,      │ │
│  │   citing [reason]. No prior abuse signals. Recommend goodwill │ │
│  │   review per case value."                                      │ │
│  │                                                                │ │
│  │ [Approve refund]  [Deny — cite policy]  [Reassign team ▾]     │ │
│  │ [Mark resolved]                          [View full transcript]│ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Gradio building block | Behavior |
|---|---|---|
| Filter bar | `gr.Dropdown` (status, team) + `gr.Textbox` (search) | Filters the table client-side against the case list pulled from the MCP `get_status`/list endpoint |
| Case table | `gr.Dataframe` (or `gr.Dataset` for row-click) | One row per case; clicking a row expands the detail panel below |
| Case detail panel | `gr.Markdown` (booking + justification + dossier, generated from the verdict JSON in [01_Architecture_and_Design.md](01_Architecture_and_Design.md) §3.3) | Renders the full justification trail human-readable — this is the "auditable justification" deliverable made visible |
| Action buttons | `gr.Button` × (Approve / Deny / Reassign / Resolve) | Each calls `update_case`/`assign_team` via the same MCP server the agents use — human actions are first-class case-store writes, appended to the audit trail, not a UI-only state change |
| Transcript link | `gr.Button` → opens the originating chat transcript (read-only) | Lets the reviewer see exactly what the traveler said, in context |
| Auto-refresh | Gradio `every=` polling or manual "Refresh" button | New escalations appear without restarting the app |

### Key interaction flows

- **New escalation appears:** Orchestrator calls `escalate()` on the MCP server → next queue refresh shows the case with status `Escalated`.
- **Reviewer acts:** clicking "Approve refund" calls `update_case(status=resolved, verdict=...)` — same write path the Orchestrator uses, so the case's audit trail shows both the AI's original verdict and the human override, satisfying the "explainable justification trail" requirement end-to-end.
- **Reassign:** dropdown of the four teams (Refunds / Rebooking / Baggage / Special Assistance) → `assign_team`.

---

## 4. Cross-cutting UI concerns

- **Single source of truth:** neither tab holds verdict/case state locally beyond what it just fetched — both read/write through the same MCP-backed case store, so a case opened in the chat tab is immediately visible in the reviewer tab (Epic 7 acceptance criterion in [02_Feature_Breakdown_and_Backlog.md](02_Feature_Breakdown_and_Backlog.md)).
- **Citations are never hidden:** every grounded claim shows its source in both the chat and the reviewer detail panel — this is a design decision, not just a compliance checkbox, since it's what makes the "no hallucination" requirement demonstrable to a reader.
- **No dead ends:** every path either produces a grounded answer, a clarifying question, or a case with a visible next step (auto-resolved / routed / escalated) — never a silent failure. Guardrail trips (timeouts, injection attempts) surface as a normal chat message ("I'm having trouble with that — I've opened a case for a specialist to review"), not an error screen.
- **Accessibility:** Gradio's default components are keyboard-navigable; keep color never as the sole status signal (status column uses text labels, not color-only badges) for the reviewer table.
- **Responsiveness:** Gradio Blocks with `gr.Row`/`gr.Column` reflow; sidebar collapses under the chat on narrow viewports (Gradio default behavior).

---

## 5. UI → backend mapping (quick reference)

| UI action | Backend call |
|---|---|
| Send chat message | `AssistantAgent.handle_turn(session_id, text)` |
| Sidebar context refresh | reads `SessionStore.get(session_id)` |
| Case-opened banner | populated from `open_case` + orchestrator verdict returned in the same turn |
| Queue table load | `MCP.list_cases(filter)` |
| Row expand | `MCP.get_status(case_id)` (full verdict/justification/dossier) |
| Approve / Deny / Resolve | `MCP.update_case(case_id, ...)` |
| Reassign | `MCP.assign_team(case_id, team)` |
| View transcript | reads stored `conversation_id` turn history |
