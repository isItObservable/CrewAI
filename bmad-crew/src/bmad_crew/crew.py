"""BMAD crew rebuilt in CrewAI (v1.15.1) — improved edition.

The full BMAD pipeline expressed as a CrewAI Crew: 8 role-playing agents and 8 tasks
wired via `context` into a linear sequential process:

    analyst -> pm -> ux -> po -> architect -> sm -> dev -> qa

New in this revision (informed by crewaiinc/skills):
  * Pydantic typed outputs on key handoffs (analyst, architect, qa) so downstream
    agents receive structured data, not free-form markdown.
  * Task guardrail on qa_review — enforces a clear SHIP / NO-SHIP verdict.
  * PlanningConfig on the dev agent — plan-then-execute mode with failure recovery,
    critical when the dev agent is using the GitHub MCP to commit multiple files.
  * Human-in-the-loop (HITL) at three meaningful checkpoints:
      1. After analyze_brief  → validate requirements before the full pipeline runs.
      2. After design_architecture → validate the tech stack before dev starts.
      3. After qa_review      → final human sign-off on ship / no-ship.
    HITL is ON by default (good for CLI demo). Set BMAD_HUMAN_IN_LOOP=false to
    disable for server / API mode (e.g. when driven from the CopilotKit UI).
  * inject_date=True on analyst — temporal context for requirements grounding.
"""

from __future__ import annotations

import datetime
import os
from typing import Any

from crewai import Agent, Crew, LLM, Process, Task
from crewai.project import CrewBase, agent, task, crew
from pydantic import BaseModel

from .tools import github_tools

# ---------------------------------------------------------------------------
# BMAD-style memlog — append-only decision record
# ---------------------------------------------------------------------------
# Every human-validated task appends to this file with a stable decision ID.
# Pattern sourced from BMAD-METHOD: https://github.com/bmad-code-org/BMAD-METHOD
# The memlog is the single source of truth for what was decided vs. assumed.
MEMLOG_PATH = "output/decisions.memlog.md"
_decision_counter: list[int] = [0]   # mutable default avoids global statement


def _memlog_callback(stage: str):
    """Return a CrewAI task callback that appends the validated output to the memlog.

    Called automatically after human_input is collected and the agent finalises
    its response.  Each entry gets a stable DEC-N id for traceability.
    """
    def _callback(output) -> None:
        _decision_counter[0] += 1
        dec_id = f"DEC-{_decision_counter[0]:03d}"
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        os.makedirs(os.path.dirname(MEMLOG_PATH), exist_ok=True)
        with open(MEMLOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n## {dec_id} · {stage} · {ts}\n\n")
            f.write(output.raw or "*(no output)*")
            f.write("\n\n---\n")
        print(f"[bmad-crew] Memlog: {dec_id} recorded for stage '{stage}' → {MEMLOG_PATH}")
    return _callback


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

def _human_in_loop() -> bool:
    """Return True unless BMAD_HUMAN_IN_LOOP is explicitly set to 'false'."""
    return os.getenv("BMAD_HUMAN_IN_LOOP", "true").strip().lower() not in ("false", "0", "no")


# ---------------------------------------------------------------------------
# Pydantic output models — typed handoffs between key pipeline stages
# ---------------------------------------------------------------------------

class BriefAnalysis(BaseModel):
    """Structured output from the analyst (Mary) — feeds into PRD and UX work."""
    problem: str
    target_users: str
    constraints: list[str]
    success_signals: list[str]
    open_questions: list[str]


class ArchitectureDecision(BaseModel):
    """Structured output from the architect (Winston) — feeds into dev implementation."""
    components: list[str]
    technology_choices: list[str]   # "Technology: rationale" strings — keep flat for qwen
    top_risks: list[str]
    data_flow_summary: str


class QAVerdict(BaseModel):
    """Structured output from QA (Quinn) — the final ship / no-ship decision."""
    decision: str           # Must be exactly "SHIP" or "NO-SHIP"
    rationale: str
    verified: list[str]
    residual_risks: list[str]


# ---------------------------------------------------------------------------
# Task guardrails
# ---------------------------------------------------------------------------

def _qa_verdict_guardrail(output: Any):
    """Reject QA output that doesn't contain a clear SHIP or NO-SHIP decision.

    The agent will retry (up to guardrail_max_retries times) with the error
    message as additional context, ensuring Quinn always produces an actionable
    verdict rather than hedging.
    """
    text = (output.raw or "").upper()
    if "NO-SHIP" in text or "SHIP" in text:
        return (True, output)
    return (
        False,
        "Your QA report must include a clear 'SHIP' or 'NO-SHIP' decision "
        "(in its own line or section). Revise your report and add the verdict explicitly.",
    )


# ---------------------------------------------------------------------------
# GitHub instruction builder (shared with main.py and server.py)
# ---------------------------------------------------------------------------

def build_github_instruction(github_repo: str) -> str:
    """Return the GitHub-specific instruction fragment injected into the dev task.

    When no repo is provided the dev agent writes code to ./output/ as markdown.
    When a repo is provided the dev agent uses the GitHub MCP tools to create a
    branch, commit files, and open a pull request.
    """
    if not github_repo:
        return (
            "Write the implementation as full source code in markdown code blocks. "
            "Output every file to the ./output/ folder so the result is locally inspectable."
        )
    return (
        f"Target GitHub repository: **{github_repo}**. "
        "Use your GitHub tools to:\n"
        "1. Create a feature branch named `feature/bmad-crew-impl`.\n"
        "2. Commit each source file to that branch using `create_or_update_file` "
        "(one commit per file, include a descriptive message).\n"
        "3. Open a pull request titled 'BMAD crew: implement highest-priority story' "
        "against the default branch.\n"
        "Include the branch name, each commit SHA, and the PR URL in your output."
    )


# ---------------------------------------------------------------------------
# LLM builder
# ---------------------------------------------------------------------------

def build_llm() -> LLM:
    """Local qwen via Ollama, configured from the environment."""
    return LLM(
        model=os.getenv("MODEL", "ollama/qwen3.6"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://<your-ollama-host>:11434"),
        temperature=float(os.getenv("MODEL_TEMPERATURE", "0.4")),
    )


def _build_planning_config():
    """Return a PlanningConfig for the dev agent, or None if unavailable.

    PlanningConfig is in crewai.agent.planning_config (1.15+). The try/except
    degrades gracefully if the module path shifts in a future release.
    """
    try:
        from crewai.agent.planning_config import PlanningConfig  # type: ignore
        return PlanningConfig(
            reasoning_effort="medium",   # replan on tool failure, not on every step
            max_steps=20,
            max_replans=3,
        )
    except ImportError:
        print("[bmad-crew] PlanningConfig not found in this CrewAI version — dev agent runs without planning mode")
        return None


# ---------------------------------------------------------------------------
# Crew definition
# ---------------------------------------------------------------------------

@CrewBase
class BmadCrew:
    """BMAD software-delivery crew."""

    agents_config = "config/agents.yaml"
    tasks_config  = "config/tasks.yaml"

    def __init__(self) -> None:
        self.llm          = build_llm()
        self.github_tools = github_tools()
        self.hitl         = _human_in_loop()
        self._dev_planning = _build_planning_config()

        if self.hitl:
            print("[bmad-crew] Human-in-the-loop: ON  (checkpoints: requirements · architecture · QA verdict)")
        else:
            print("[bmad-crew] Human-in-the-loop: OFF (set BMAD_HUMAN_IN_LOOP=true to enable)")

        # Initialise memlog for this run (append-only, survives multiple runs).
        self._init_memlog()

    def _init_memlog(self) -> None:
        """Write a run header to the decision memlog (BMAD-METHOD pattern)."""
        os.makedirs("output", exist_ok=True)
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        header = (
            f"\n# BMAD Crew Run — {ts}\n"
            f"Human-in-the-loop: {'ON' if self.hitl else 'OFF'}\n\n"
            "| Decision ID | Stage | Outcome |\n"
            "|-------------|-------|---------|\n"
            "| DEC-001 | requirements-validation | pending |\n"
            "| DEC-002 | architecture-validation  | pending |\n"
            "| DEC-003 | qa-sign-off              | pending |\n\n"
            "---\n"
        )
        with open(MEMLOG_PATH, "a", encoding="utf-8") as f:
            f.write(header)

    # ── Agents ──────────────────────────────────────────────────────────────

    @agent
    def analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["analyst"],
            llm=self.llm,
            verbose=True,
            inject_date=True,       # Grounds requirements in today's date
        )

    @agent
    def pm(self) -> Agent:
        return Agent(
            config=self.agents_config["pm"],
            llm=self.llm,
            tools=self.github_tools,
            verbose=True,
        )

    @agent
    def ux(self) -> Agent:
        return Agent(config=self.agents_config["ux"], llm=self.llm, verbose=True)

    @agent
    def po(self) -> Agent:
        return Agent(config=self.agents_config["po"], llm=self.llm, verbose=True)

    @agent
    def architect(self) -> Agent:
        return Agent(
            config=self.agents_config["architect"],
            llm=self.llm,
            tools=self.github_tools,
            verbose=True,
        )

    @agent
    def sm(self) -> Agent:
        return Agent(
            config=self.agents_config["sm"],
            llm=self.llm,
            tools=self.github_tools,
            verbose=True,
        )

    @agent
    def dev(self) -> Agent:
        """Senior engineer — plan-then-execute mode for reliable multi-file commits."""
        kwargs: dict = dict(
            config=self.agents_config["dev"],
            llm=self.llm,
            tools=self.github_tools,
            verbose=True,
            allow_code_execution=False,   # code runs in the GitHub repo, not locally
        )
        if self._dev_planning:
            kwargs["planning_config"] = self._dev_planning
        return Agent(**kwargs)

    @agent
    def qa(self) -> Agent:
        return Agent(config=self.agents_config["qa"], llm=self.llm, verbose=True)

    # ── Tasks ────────────────────────────────────────────────────────────────

    @task
    def analyze_brief(self) -> Task:
        """HITL checkpoint 1 — human validates requirements before the pipeline runs.

        BMAD pattern: analyst surfaces BLOCKERS (one at a time) + DEFERRALS.
        Human resolves or presses Enter to accept with conservative defaults.
        Decision is appended to decisions.memlog.md (DEC-001).
        """
        return Task(
            config=self.tasks_config["analyze_brief"],
            output_pydantic=BriefAnalysis,
            human_input=self.hitl,
            callback=_memlog_callback("requirements-validation"),
        )

    @task
    def write_prd(self) -> Task:
        return Task(config=self.tasks_config["write_prd"])

    @task
    def ux_spec(self) -> Task:
        return Task(config=self.tasks_config["ux_spec"])

    @task
    def refine_backlog(self) -> Task:
        return Task(config=self.tasks_config["refine_backlog"])

    @task
    def design_architecture(self) -> Task:
        """HITL checkpoint 2 — human validates tech direction before dev starts.

        BMAD pattern: architect presents one BLOCKER at a time (tech choices,
        component boundaries, risks requiring a human call). DEFERRALS logged
        with stated assumptions. Decision recorded in memlog (DEC-002).
        """
        return Task(
            config=self.tasks_config["design_architecture"],
            output_pydantic=ArchitectureDecision,
            human_input=self.hitl,
            callback=_memlog_callback("architecture-validation"),
        )

    @task
    def slice_stories(self) -> Task:
        return Task(config=self.tasks_config["slice_stories"])

    @task
    def implement_story(self) -> Task:
        return Task(config=self.tasks_config["implement_story"])

    @task
    def qa_review(self) -> Task:
        """HITL checkpoint 3 — human makes the final ship / no-ship call.

        BMAD pattern: Quinn presents verdict + SIGN-OFF REQUEST. Human may:
          A) Accept Quinn's recommendation (press Enter)
          B) Override with "SHIP" or "NO-SHIP"
          C) Provide feedback → Quinn revises and resubmits (up to 3 retries via guardrail)
        Final decision recorded in memlog (DEC-003). Output written to qa_report.md.
        """
        return Task(
            config=self.tasks_config["qa_review"],
            output_pydantic=QAVerdict,
            output_file="output/qa_report.md",
            guardrail=_qa_verdict_guardrail,
            guardrail_max_retries=3,
            human_input=self.hitl,
            callback=_memlog_callback("qa-sign-off"),
        )

    # ── Crew ─────────────────────────────────────────────────────────────────

    @crew
    def crew(self) -> Crew:
        """Sequential BMAD pipeline (Option A — the default, cleanest to observe)."""
        return Crew(
            agents=[
                self.analyst(),
                self.pm(),
                self.ux(),
                self.po(),
                self.architect(),
                self.sm(),
                self.dev(),
                self.qa(),
            ],
            tasks=[
                self.analyze_brief(),
                self.write_prd(),
                self.ux_spec(),
                self.refine_backlog(),
                self.design_architecture(),
                self.slice_stories(),
                self.implement_story(),
                self.qa_review(),
            ],
            process=Process.sequential,
            verbose=True,
        )

    def hierarchical_crew(self) -> Crew:
        """Option B — BMad Orchestrator manager delegates dynamically.

        Use for the 'dynamic delegation' contrast segment of the episode.
        Note: human_input tasks still pause in hierarchical mode.
        """
        return Crew(
            agents=[
                self.analyst(),
                self.pm(),
                self.ux(),
                self.po(),
                self.architect(),
                self.sm(),
                self.dev(),
                self.qa(),
            ],
            tasks=[
                self.analyze_brief(),
                self.write_prd(),
                self.ux_spec(),
                self.refine_backlog(),
                self.design_architecture(),
                self.slice_stories(),
                self.implement_story(),
                self.qa_review(),
            ],
            process=Process.hierarchical,
            manager_llm=self.llm,
            verbose=True,
        )
