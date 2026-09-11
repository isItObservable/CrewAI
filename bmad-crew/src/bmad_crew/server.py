"""FastAPI service wrapping the BMAD crew for Kubernetes.

Crews are batch-y (a kickoff can run minutes), so the production shape is an HTTP
service. Two kickoff modes are exposed:

* ``POST /kickoff``       — synchronous (blocks until done; simplest for quick tests)
* ``POST /kickoff/async`` — returns a run_id immediately; poll progress via SSE
* ``GET  /stream/{run_id}`` — Server-Sent Events stream of agent lifecycle events

The async path is what the CopilotKit UI uses to drive the real-time agent timeline.

    uv run uvicorn bmad_crew.server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import json
import queue as stdlib_queue
import threading
import uuid
from typing import Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from bmad_crew.crew import BmadCrew, build_github_instruction
from bmad_crew.observability import init_observability

# Initialise telemetry once at import so every request is instrumented.
_TELEMETRY_ON = init_observability()

app = FastAPI(title="BMAD Crew (CrewAI)", version="1.0.0")

# Allow the CopilotKit UI (Next.js dev server + in-cluster) to reach the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory run registry — maps run_id -> stdlib Queue of SSE event dicts.
# Each dict has at minimum a "type" key.  The final event has type "done" or "error".
# ---------------------------------------------------------------------------
_run_queues: dict[str, stdlib_queue.Queue] = {}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class KickoffRequest(BaseModel):
    project: str
    brief: str
    hierarchical: bool = False
    github_repo: str = ""   # e.g. "isItObservable/sympozium-todo-demo"


class KickoffResponse(BaseModel):
    project: str
    result: str


class AsyncKickoffResponse(BaseModel):
    run_id: str


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/healthz")
def healthz() -> dict:
    """Liveness/readiness probe target."""
    return {"status": "ok", "telemetry": _TELEMETRY_ON}


# ---------------------------------------------------------------------------
# Synchronous kickoff (original — kept for CLI / curl tests)
# ---------------------------------------------------------------------------

@app.post("/kickoff", response_model=KickoffResponse)
def kickoff(req: KickoffRequest) -> KickoffResponse:
    """Run the BMAD pipeline synchronously and return the final QA report."""
    bmad = BmadCrew()
    crew = bmad.hierarchical_crew() if req.hierarchical else bmad.crew()
    inputs: dict = {
        "project": req.project,
        "brief": req.brief,
        "github_repo_instruction": build_github_instruction(req.github_repo),
    }
    result = crew.kickoff(inputs=inputs)
    return KickoffResponse(project=req.project, result=str(result))


# ---------------------------------------------------------------------------
# Async kickoff — returns run_id immediately; progress via /stream/{run_id}
# ---------------------------------------------------------------------------

def _crew_thread(run_id: str, req: KickoffRequest) -> None:
    """Worker thread: runs the crew and pushes lifecycle events to the SSE queue."""
    q = _run_queues[run_id]

    # Import event types from CrewAI's native event bus.
    try:
        from crewai.events import crewai_event_bus
        from crewai.events.event_types import (
            CrewKickoffStartedEvent, CrewKickoffCompletedEvent, CrewKickoffFailedEvent,
            TaskStartedEvent, TaskCompletedEvent, TaskFailedEvent,
            AgentExecutionStartedEvent, AgentExecutionCompletedEvent,
        )

        @crewai_event_bus.on(CrewKickoffStartedEvent)
        def on_crew_start(source, event):
            q.put({"type": "crew_start"})

        @crewai_event_bus.on(TaskStartedEvent)
        def on_task_start(source, event):
            name = getattr(event, "task_name", None) or getattr(event, "name", "task")
            q.put({"type": "task_start", "task": str(name)})

        @crewai_event_bus.on(TaskCompletedEvent)
        def on_task_done(source, event):
            name = getattr(event, "task_name", None) or getattr(event, "name", "task")
            q.put({"type": "task_done", "task": str(name)})

        @crewai_event_bus.on(TaskFailedEvent)
        def on_task_fail(source, event):
            name = getattr(event, "task_name", None) or getattr(event, "name", "task")
            q.put({"type": "task_error", "task": str(name)})

        @crewai_event_bus.on(AgentExecutionStartedEvent)
        def on_agent_start(source, event):
            role = getattr(event.agent, "role", str(event.agent))
            q.put({"type": "agent_start", "agent": str(role)})

        @crewai_event_bus.on(AgentExecutionCompletedEvent)
        def on_agent_done(source, event):
            role = getattr(event.agent, "role", str(event.agent))
            output = ""
            if hasattr(event, "output") and event.output:
                raw = getattr(event.output, "raw", None) or str(event.output)
                output = raw[:2000]  # cap at 2 kB — enough for the UI, not overwhelming
            q.put({"type": "agent_done", "agent": str(role), "output": output})

    except Exception as exc:  # pragma: no cover — degrade if event bus API changed
        print(f"[bmad-crew] SSE event subscription failed ({exc}); events will be minimal")

    # Run the crew.
    try:
        bmad = BmadCrew()
        crew = bmad.hierarchical_crew() if req.hierarchical else bmad.crew()
        inputs: dict = {
            "project": req.project,
            "brief": req.brief,
            "github_repo_instruction": build_github_instruction(req.github_repo),
        }
        result = crew.kickoff(inputs=inputs)
        q.put({"type": "done", "result": str(result)})
    except Exception as exc:
        q.put({"type": "error", "message": str(exc)})


@app.post("/kickoff/async", response_model=AsyncKickoffResponse)
def kickoff_async(req: KickoffRequest) -> AsyncKickoffResponse:
    """Start a crew run in the background and return a run_id for SSE polling."""
    run_id = str(uuid.uuid4())
    _run_queues[run_id] = stdlib_queue.Queue()
    thread = threading.Thread(target=_crew_thread, args=(run_id, req), daemon=True)
    thread.start()
    return AsyncKickoffResponse(run_id=run_id)


# ---------------------------------------------------------------------------
# SSE stream — agent lifecycle events for the CopilotKit UI
# ---------------------------------------------------------------------------

@app.get("/stream/{run_id}")
def stream_events(run_id: str) -> StreamingResponse:
    """Server-Sent Events stream of crew lifecycle events for a given run."""
    if run_id not in _run_queues:
        raise HTTPException(status_code=404, detail="run_id not found")

    def _generate() -> Iterator[str]:
        q = _run_queues[run_id]
        # Heartbeat every 15 s keeps the connection alive through proxies/k8s ingress.
        while True:
            try:
                event = q.get(timeout=15)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("done", "error"):
                    break
            except stdlib_queue.Empty:
                yield "data: {\"type\":\"ping\"}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


# ---------------------------------------------------------------------------
# Run status — fetch final result after done event received
# ---------------------------------------------------------------------------

@app.get("/run/{run_id}/result")
def get_result(run_id: str) -> dict:
    """Non-streaming fallback: drain the queue and return the final result.

    Intended for polling clients that can't do SSE (e.g. curl in the demo).
    """
    if run_id not in _run_queues:
        raise HTTPException(status_code=404, detail="run_id not found")
    q = _run_queues[run_id]
    events: list[dict] = []
    while True:
        try:
            ev = q.get(timeout=1)
            events.append(ev)
            if ev.get("type") in ("done", "error"):
                return {"run_id": run_id, "events": events, "final": ev}
        except stdlib_queue.Empty:
            return {"run_id": run_id, "events": events, "status": "running"}
