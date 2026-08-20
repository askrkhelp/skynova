"""LLM-as-judge for the justification-faithfulness metric (spec §9.5).

A single ADK LlmAgent call per verdict-bearing case, scoring 0-3 whether the
justification's `reasoning` is a faithful application of its own cited
`policy_clause`/`policy_text` and `signals` — not whether the verdict
*category* is correct (that's checked deterministically against
eval/golden.py) but whether the natural-language justification the model
wrote actually follows from what it cites, per 01_Architecture_and_Design.md
SS3.3's "never vibes, traceable to a cited clause."

Mirrors app/agents/intent_agent.py's IntentAgentRunner pattern (throwaway
InMemorySessionService session per call) rather than a shared session, since
each judged case is independent.
"""

from __future__ import annotations

import uuid
from typing import Literal

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types
from pydantic import BaseModel, Field

MODEL = "gemini-3.1-flash-lite"
APP_NAME = "resolveai_eval_judge"
OUTPUT_KEY = "faithfulness_result"


class FaithfulnessScore(BaseModel):
    score: Literal[0, 1, 2, 3]
    rationale: str = Field(description="One short sentence on what earned or cost points.")


INSTRUCTION = """\
You are grading a customer-support verdict's justification for faithfulness,
not for whether the verdict itself was the right call.

You will be given: the issue_type, the verdict category (auto_resolve /
route / escalate), the cited policy_clause id, the cited policy_text (the
retrieved clause, verbatim), the signals used (fare_class, delay_minutes,
risk_score, abuse_flag, etc.), and the reasoning prose.

Score 0-3:
- 0: policy_text does not actually support the reasoning, or the reasoning
  contradicts the cited clause or the listed signals.
- 1: the clause is real and topically relevant, but the reasoning doesn't
  clearly follow from it or ignores a signal that should have mattered.
- 2: mostly faithful — the reasoning correctly applies the clause to the
  case, with a minor gap (e.g. doesn't mention a signal that was present but
  didn't change the outcome).
- 3: fully faithful — the reasoning is a correct, complete application of
  the cited clause to exactly these signals; nothing is asserted that isn't
  grounded in policy_text or the signals.

Judge only faithfulness (does the reasoning follow from what's cited), never
whether you'd have picked a different verdict yourself.
"""


def build_judge_agent() -> Agent:
    return Agent(
        name="eval_faithfulness_judge",
        model=MODEL,
        description="LLM-as-judge for the Epic 8 justification-faithfulness metric.",
        instruction=INSTRUCTION,
        output_schema=FaithfulnessScore,
        output_key=OUTPUT_KEY,
        generate_content_config=genai_types.GenerateContentConfig(temperature=0.0),
    )


def _format_justification(issue_type: str, verdict: str, justification: dict) -> str:
    signals = justification.get("signals", {})
    return (
        f"issue_type: {issue_type}\n"
        f"verdict: {verdict}\n"
        f"policy_clause: {justification.get('policy_clause')}\n"
        f"policy_text: {justification.get('policy_text')}\n"
        f"signals: {signals}\n"
        f"reasoning: {justification.get('reasoning')}"
    )


class JudgeRunner:
    """Runs one faithfulness scoring per `score()` call in a throwaway session."""

    def __init__(self) -> None:
        self._agent = build_judge_agent()
        self._session_service = InMemorySessionService()
        self._runner = Runner(agent=self._agent, app_name=APP_NAME, session_service=self._session_service)

    async def score(self, issue_type: str, verdict: str, justification: dict) -> FaithfulnessScore:
        session_id = f"judge-{uuid.uuid4().hex[:8]}"
        await self._session_service.create_session(
            app_name=APP_NAME, user_id="eval_harness", session_id=session_id, state={}
        )
        prompt = _format_justification(issue_type, verdict, justification)
        message = genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=prompt)])

        async for _event in self._runner.run_async(
            user_id="eval_harness", session_id=session_id, new_message=message
        ):
            pass

        session = await self._session_service.get_session(
            app_name=APP_NAME, user_id="eval_harness", session_id=session_id
        )
        data = dict(session.state.get(OUTPUT_KEY) or {})
        return FaithfulnessScore.model_validate(data)
