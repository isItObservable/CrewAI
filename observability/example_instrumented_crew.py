"""
Minimal reference: wire OpenTelemetry into a CrewAI crew in two lines.

This is the exact seam the BMAD crew (ISI-1585) uses. Drop these two calls at the
top of your entrypoint (main.py / server.py), BEFORE building or kicking off the
crew. Everything else is your normal CrewAI code.

Run against the local collector:
    export CREWAI_DISABLE_TELEMETRY=true                  # silence anon analytics
    export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
    export OTEL_SERVICE_NAME=crewai-bmad-crew
    python observability/example_instrumented_crew.py
"""
import os

# 1) Configure the OTel SDK (OTLP -> collector -> Dynatrace).
# 2) Install the CrewAI event-bus -> OTel listener (gen_ai.* traces/metrics/logs).
from observability.instrumentation import init_otel, instrument_crewai

init_otel(service_name=os.getenv("OTEL_SERVICE_NAME", "crewai-bmad-crew"))
instrument_crewai()

# ---- your normal crew below ------------------------------------------------
from crewai import Agent, Task, Crew, LLM, Process

llm = LLM(model="ollama/qwen3.6:latest", base_url="http://10.0.0.185:11434")

analyst = Agent(role="Analyst", goal="Analyze the request into a crisp brief.",
                backstory="A meticulous business analyst.", llm=llm)
pm = Agent(role="Product Manager", goal="Turn the brief into a short PRD.",
           backstory="Pragmatic PM who scopes ruthlessly.", llm=llm)

t_brief = Task(description="Analyze: {topic}. Produce a one-paragraph brief.",
               expected_output="A one-paragraph brief.", agent=analyst)
t_prd = Task(description="Turn the brief into a 3-bullet PRD.",
             expected_output="Three bullets.", agent=pm, context=[t_brief])

crew = Crew(agents=[analyst, pm], tasks=[t_brief, t_prd],
            process=Process.sequential, name="bmad-crew", verbose=True)

if __name__ == "__main__":
    print(crew.kickoff(inputs={"topic": "observability for AI agents"}))
    # BatchSpanProcessor/metric reader flush on process exit; for short scripts
    # you may force a flush via the SDK providers if needed.
