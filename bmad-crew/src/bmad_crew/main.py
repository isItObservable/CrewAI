"""CLI entrypoint — run the BMAD crew locally.

    uv run bmad-crew --project "Observability portal" --brief "..."

Falls back to a built-in sample brief so `crewai run` / `uv run bmad-crew` works with
zero arguments for the on-screen "watch it work" moment.
"""

from __future__ import annotations

import argparse

from bmad_crew.crew import BmadCrew
from bmad_crew.observability import init_observability

SAMPLE_PROJECT = "TaskPing — a lightweight team stand-up reminder bot"
SAMPLE_BRIEF = (
    "Small engineering teams forget to post async stand-ups. We want a simple bot that "
    "pings each team member in Slack at a configurable time, collects their yesterday / "
    "today / blockers, and posts a single digest to a channel. Must be self-hostable and "
    "not depend on any paid SaaS. First version: one team, one channel."
)


def build_inputs(args: argparse.Namespace) -> dict:
    return {
        "project": args.project or SAMPLE_PROJECT,
        "brief": args.brief or SAMPLE_BRIEF,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the BMAD crew (CrewAI).")
    parser.add_argument("--project", help="Project name/title.")
    parser.add_argument("--brief", help="The incoming brief to run through the pipeline.")
    parser.add_argument(
        "--hierarchical",
        action="store_true",
        help="Use the BMad Orchestrator (manager) hierarchical process instead of sequential.",
    )
    args = parser.parse_args()

    telemetry_on = init_observability()
    print(f"[bmad-crew] OpenTelemetry instrumentation: {'ON' if telemetry_on else 'off'}")

    inputs = build_inputs(args)
    print(f"[bmad-crew] Kicking off BMAD pipeline for: {inputs['project']}")

    bmad = BmadCrew()
    crew = bmad.hierarchical_crew() if args.hierarchical else bmad.crew()
    result = crew.kickoff(inputs=inputs)

    print("\n" + "=" * 72)
    print("BMAD crew finished. Final QA report:\n")
    print(result)


if __name__ == "__main__":
    main()
