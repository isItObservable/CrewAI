"""BMAD crew rebuilt in CrewAI (v1.15.1).

The full BMAD pipeline expressed as a CrewAI Crew: 8 role-playing agents and 8 tasks
wired via `context` into a linear sequential process:

    analyst -> pm -> ux -> po -> architect -> sm -> dev -> qa

Every agent shares one local LLM (qwen via Ollama) built from environment config, so
the whole crew runs key-free against our Mac Studio Ollama host. An optional
hierarchical variant (a BMad Orchestrator as manager) is provided for the "dynamic
delegation" contrast beat in the episode.
"""

from __future__ import annotations

import os

from crewai import Agent, Crew, LLM, Process, Task
from crewai.project import CrewBase, agent, task, crew


def build_llm() -> LLM:
    """Local qwen via Ollama, configured from the environment.

    MODEL defaults to the tag used across our episodes; OLLAMA_BASE_URL points at the
    Mac Studio Ollama host. Nothing here needs an external API key.
    """
    return LLM(
        model=os.getenv("MODEL", "ollama/qwen3.6"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://10.0.0.185:11434"),
        temperature=float(os.getenv("MODEL_TEMPERATURE", "0.4")),
    )


@CrewBase
class BmadCrew:
    """BMAD software-delivery crew."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(self) -> None:
        self.llm = build_llm()

    # --- Agents -----------------------------------------------------------------
    @agent
    def analyst(self) -> Agent:
        return Agent(config=self.agents_config["analyst"], llm=self.llm, verbose=True)

    @agent
    def pm(self) -> Agent:
        return Agent(config=self.agents_config["pm"], llm=self.llm, verbose=True)

    @agent
    def ux(self) -> Agent:
        return Agent(config=self.agents_config["ux"], llm=self.llm, verbose=True)

    @agent
    def po(self) -> Agent:
        return Agent(config=self.agents_config["po"], llm=self.llm, verbose=True)

    @agent
    def architect(self) -> Agent:
        return Agent(config=self.agents_config["architect"], llm=self.llm, verbose=True)

    @agent
    def sm(self) -> Agent:
        return Agent(config=self.agents_config["sm"], llm=self.llm, verbose=True)

    @agent
    def dev(self) -> Agent:
        return Agent(config=self.agents_config["dev"], llm=self.llm, verbose=True)

    @agent
    def qa(self) -> Agent:
        return Agent(config=self.agents_config["qa"], llm=self.llm, verbose=True)

    # --- Tasks ------------------------------------------------------------------
    @task
    def analyze_brief(self) -> Task:
        return Task(config=self.tasks_config["analyze_brief"])

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
        return Task(config=self.tasks_config["design_architecture"])

    @task
    def slice_stories(self) -> Task:
        return Task(config=self.tasks_config["slice_stories"])

    @task
    def implement_story(self) -> Task:
        return Task(config=self.tasks_config["implement_story"])

    @task
    def qa_review(self) -> Task:
        # Final task writes the full delivery bundle to disk.
        return Task(
            config=self.tasks_config["qa_review"],
            output_file="output/qa_report.md",
        )

    # --- Crew -------------------------------------------------------------------
    @crew
    def crew(self) -> Crew:
        """Sequential BMAD pipeline (Option A — the default, cleanest to observe)."""
        return Crew(
            agents=self.agents,  # auto-collected from @agent methods
            tasks=self.tasks,    # auto-collected from @task methods, in definition order
            process=Process.sequential,
            verbose=True,
        )

    def hierarchical_crew(self) -> Crew:
        """Optional Option B — a BMad Orchestrator manager delegates dynamically.

        Heavier on qwen tool-calling and non-deterministic; use only for the short
        "dynamic delegation" contrast segment, not as the backbone.
        """
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.hierarchical,
            manager_llm=self.llm,
            verbose=True,
        )
