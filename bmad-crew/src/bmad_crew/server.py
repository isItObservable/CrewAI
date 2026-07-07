"""FastAPI service wrapping the BMAD crew for Kubernetes.

Crews are batch-y (a kickoff can run minutes), so the production shape is an HTTP
service. This exposes a synchronous `POST /kickoff` (clearest for the demo) plus a
`GET /healthz` for k8s probes. For long crews in production, swap to an async
enqueue -> worker -> poll pattern (noted in TUTORIAL.md).

    uv run uvicorn bmad_crew.server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from bmad_crew.crew import BmadCrew
from bmad_crew.observability import init_observability

# Initialise telemetry once at import so every request is instrumented.
_TELEMETRY_ON = init_observability()

app = FastAPI(title="BMAD Crew (CrewAI)", version="1.0.0")


class KickoffRequest(BaseModel):
    project: str
    brief: str
    hierarchical: bool = False


class KickoffResponse(BaseModel):
    project: str
    result: str


@app.get("/healthz")
def healthz() -> dict:
    """Liveness/readiness probe target."""
    return {"status": "ok", "telemetry": _TELEMETRY_ON}


@app.post("/kickoff", response_model=KickoffResponse)
def kickoff(req: KickoffRequest) -> KickoffResponse:
    """Run the BMAD pipeline synchronously and return the final QA report."""
    bmad = BmadCrew()
    crew = bmad.hierarchical_crew() if req.hierarchical else bmad.crew()
    result = crew.kickoff(inputs={"project": req.project, "brief": req.brief})
    return KickoffResponse(project=req.project, result=str(result))
