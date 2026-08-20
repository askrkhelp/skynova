"""CLI entry point for the Epic 8 evaluation harness.

    python -m eval.run_eval                       # full 62-scenario run
    python -m eval.run_eval --limit 10             # smoke test, first 10
    python -m eval.run_eval --ids E01,E05,E11      # just these scenarios
    python -m eval.run_eval --skip-judge           # skip the faithfulness LLM-judge calls
    python -m eval.run_eval --pace 8               # seconds between scenarios (default 8)

Needs GEMINI_API_KEY (or GOOGLE_API_KEY) set — every scenario makes at least
one live model call, several make 3+ (assistant turn, search_policy
embedding, Intent Agent, faithfulness judge), against the same shared
free-tier 15 req/min key CLAUDE.md warns about. `--pace` sets the delay
between scenario starts (not within a scenario — that's the agent
pipeline's own concern); a scenario-level failure (including a 429) is
caught in eval/runner.py and recorded on that scenario's result rather than
aborting the run, so raise --pace and re-run rather than assuming a partial
results.json means the harness is broken.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from eval.judge import JudgeRunner
from eval.metrics import compute_metrics
from eval.report import render_report
from eval.runner import DEFAULT_SCENARIOS_PATH, load_scenarios, run_scenario

REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ResolveAI evaluation harness.")
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS_PATH)
    parser.add_argument("--ids", type=str, default=None, help="Comma-separated scenario ids to run, e.g. E01,E05")
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N scenarios")
    parser.add_argument("--skip-judge", action="store_true", help="Skip the LLM-as-judge faithfulness calls")
    parser.add_argument("--pace", type=float, default=8.0, help="Seconds to wait between scenario starts")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "eval")
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        print("GEMINI_API_KEY (or GOOGLE_API_KEY) is not set — the eval harness needs a live model key.", file=sys.stderr)
        return 1

    scenarios = load_scenarios(args.scenarios)
    if args.ids:
        wanted = {s.strip() for s in args.ids.split(",") if s.strip()}
        scenarios = [s for s in scenarios if s["id"] in wanted]
    if args.limit:
        scenarios = scenarios[: args.limit]
    if not scenarios:
        print("No scenarios selected.", file=sys.stderr)
        return 1

    judge = None if args.skip_judge else JudgeRunner()

    results = []
    for i, scenario in enumerate(scenarios):
        if i > 0:
            await asyncio.sleep(args.pace)
        t0 = time.monotonic()
        result = await run_scenario(scenario, judge=judge)
        elapsed = time.monotonic() - t0
        status = "OK" if not result["error"] else f"ERROR: {result['error']}"
        print(f"[{i + 1}/{len(scenarios)}] {scenario['id']} ({elapsed:.1f}s) {status}")
        results.append(result)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    results_path = args.out_dir / "results.json"
    results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    metrics = compute_metrics(results)
    report_path = args.out_dir / "report.md"
    report_path.write_text(render_report(results, metrics), encoding="utf-8")

    print(f"\nWrote {results_path}")
    print(f"Wrote {report_path}")
    print(json.dumps(metrics, indent=2))
    return 0


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(run(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
