"""CLI entrypoint — run the BMAD crew locally.

    uv run bmad-crew --project "Observability portal" --brief "..."
    uv run bmad-crew --project "Todo app" --brief "..." --github-repo owner/repo

Falls back to a built-in sample brief so `crewai run` / `uv run bmad-crew` works with
zero arguments for the on-screen "watch it work" moment.
"""

from __future__ import annotations

import argparse
import os

from bmad_crew.crew import BmadCrew, build_github_instruction
from bmad_crew.observability import init_observability

SAMPLE_PROJECT = "TaskPing — a lightweight team stand-up reminder bot"
SAMPLE_BRIEF = (
    "Small engineering teams forget to post async stand-ups. We want a simple bot that "
    "pings each team member in Slack at a configurable time, collects their yesterday / "
    "today / blockers, and posts a single digest to a channel. Must be self-hostable and "
    "not depend on any paid SaaS. First version: one team, one channel."
)


def build_inputs(args: argparse.Namespace) -> dict:
    github_repo = (args.github_repo or "").strip()
    return {
        "project": args.project or SAMPLE_PROJECT,
        "brief": args.brief or SAMPLE_BRIEF,
        "github_repo_instruction": build_github_instruction(github_repo),
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
    parser.add_argument(
        "--no-hitl",
        action="store_true",
        help=(
            "Disable human-in-the-loop checkpoints (runs fully automated). "
            "Equivalent to setting BMAD_HUMAN_IN_LOOP=false. "
            "Useful for CI or scripted test runs."
        ),
    )
    parser.add_argument(
        "--github-repo",
        metavar="OWNER/REPO",
        help=(
            "GitHub repository for the dev agent to commit code to (e.g. myorg/myrepo). "
            "Requires GITHUB_PERSONAL_ACCESS_TOKEN and GITHUB_MCP_MODE to be set."
        ),
    )
    args = parser.parse_args()

    # Apply --no-hitl before BmadCrew() reads the env var.
    if args.no_hitl:
        os.environ["BMAD_HUMAN_IN_LOOP"] = "false"

    telemetry_on = init_observability()
    print(f"[bmad-crew] OpenTelemetry instrumentation: {'ON' if telemetry_on else 'off'}")

    inputs = build_inputs(args)
    print(f"[bmad-crew] Kicking off BMAD pipeline for: {inputs['project']}")
    if args.github_repo:
        print(f"[bmad-crew] GitHub target repo: {args.github_repo}")

    bmad = BmadCrew()
    crew = bmad.hierarchical_crew() if args.hierarchical else bmad.crew()
    result = crew.kickoff(inputs=inputs)

    print("\n" + "=" * 72)
    print("BMAD crew finished. Final QA report:\n")
    print(result)


if __name__ == "__main__":
    main()
