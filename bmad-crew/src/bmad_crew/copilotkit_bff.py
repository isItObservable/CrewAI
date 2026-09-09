"""CopilotKit backend-for-frontend (BFF) for the BMAD crew — AG-UI over SSE.

This is the self-hosted, OSS-only UI path (ISI-4095, board-approved 2026-09-09):
a CopilotKit chat front-end (``frontend/``) talks **directly** to this endpoint
via ``HttpAgent`` from ``@ag-ui/client`` — no CopilotKit Cloud, no AMP, and no
Node runtime in between. Under the hood the BFF is a thin front door: it calls
the crew service's existing ``POST /kickoff`` API (``server.py``) and streams
the run back to the browser as [AG-UI](https://docs.ag-ui.com) Server-Sent
Events.

Wire contract (AG-UI HTTP+SSE binding):

* ``POST`` with the run input as one JSON object
  (``{"threadId": ..., "runId": ..., "messages": [...]}``).
* Reply ``200`` + ``text/event-stream``; each SSE ``data:`` payload is exactly
  one protocol event: RUN_STARTED, (STEP_STARTED/STEP_FINISHED),
  TEXT_MESSAGE_START / TEXT_MESSAGE_CONTENT / TEXT_MESSAGE_END, RUN_FINISHED
  (or RUN_ERROR). SSE comment lines (``: keep-alive``) are sent while the crew
  works so proxies don't close the idle stream.

The user's chat message is the crew brief. Optional first line
``project: <name>`` sets the project name (default: "Crew request").

Environment:

  KICKOFF_URL      crew service endpoint (default http://localhost:8000/kickoff)
  KICKOFF_TIMEOUT  seconds to wait for the crew (default 900; a full 8-agent
                   sequential run takes minutes)
  BFF_ECHO_MODE    =true to answer without calling the crew (UI smoke-test, no
                   LLM needed)
  BFF_CORS_ORIGINS comma-separated browser origins allowed to call the BFF
                   (default * for the tutorial; restrict in production)

Run it:

    uv run bmad-crew-bff                 # serves http://0.0.0.0:8100
    # or: uv run uvicorn bmad_crew.copilotkit_bff:app --port 8100

Smoke-test without a browser (echo mode):

    BFF_ECHO_MODE=true uv run bmad-crew-bff &
    curl -N localhost:8100/copilotkit -H 'content-type: application/json' \
      -d '{"threadId":"t1","runId":"r1","messages":[{"id":"m1","role":"user","content":"project: Demo — a status page for our SLOs"}]}'
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

KICKOFF_URL = os.getenv("KICKOFF_URL", "http://localhost:8000/kickoff")
KICKOFF_TIMEOUT = float(os.getenv("KICKOFF_TIMEOUT", "900"))
ECHO_MODE = os.getenv("BFF_ECHO_MODE", "").lower() == "true"
CORS_ORIGINS = [o.strip() for o in os.getenv("BFF_CORS_ORIGINS", "*").split(",")]

AGENT_ID = "bmad-crew"

app = FastAPI(title="BMAD Crew — CopilotKit BFF (AG-UI)", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_PROJECT_LINE = re.compile(r"^\s*project\s*:\s*(.+?)\s*$", re.IGNORECASE)


def _sse(event: dict[str, Any]) -> str:
    """Frame one AG-UI event as an SSE ``data:`` line (LF-terminated)."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _parse_brief(body: dict[str, Any]) -> tuple[str, str]:
    """Take the last user message as the brief; optional 'project:' first line."""
    messages = body.get("messages") or []
    text = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            text = str(msg.get("content") or "").strip()
            break
    if not text:
        text = "No brief provided — run the BMAD crew on a small example project."
    project = "Crew request"
    lines = text.splitlines()
    if lines and (m := _PROJECT_LINE.match(lines[0])):
        project = m.group(1)
        text = "\n".join(lines[1:]).strip() or project
    return project, text


async def _run_kickoff(project: str, brief: str) -> str:
    """Call the crew service's /kickoff and return the final report."""
    async with httpx.AsyncClient(timeout=KICKOFF_TIMEOUT) as client:
        resp = await client.post(KICKOFF_URL, json={"project": project, "brief": brief})
        resp.raise_for_status()
        return str(resp.json().get("result", "")).strip()


async def _events(body: dict[str, Any]) -> AsyncIterator[str]:
    thread_id = str(body.get("threadId") or f"thread-{uuid.uuid4().hex[:12]}")
    run_id = str(body.get("runId") or f"run-{uuid.uuid4().hex[:12]}")
    project, brief = _parse_brief(body)

    yield _sse({"type": "RUN_STARTED", "threadId": thread_id, "runId": run_id})
    yield _sse({"type": "STEP_STARTED", "stepName": "kickoff"})
    yield _sse(
        {
            "type": "TEXT_MESSAGE_START",
            "messageId": "crew-status",
            "role": "assistant",
        }
    )
    status = (
        f"Crew kicked off — **{project}**. Eight BMAD agents run sequentially "
        "(analyst → pm → ux → po → architect → sm → dev → qa); a full run takes "
        "a few minutes. Keep this tab open — the QA report lands here."
        if not ECHO_MODE
        else f"(echo mode — no crew call) Brief received for **{project}**: {brief[:300]}"
    )
    for chunk in (status[i : i + 90] for i in range(0, len(status), 90)):
        yield _sse({"type": "TEXT_MESSAGE_CONTENT", "messageId": "crew-status", "delta": chunk})
        await asyncio.sleep(0)  # yield to the event loop between frames
    yield _sse({"type": "TEXT_MESSAGE_END", "messageId": "crew-status"})

    try:
        if ECHO_MODE:
            await asyncio.sleep(1.0)
            result = f"(echo mode) The crew would now run with project={project!r}, brief={brief!r}"
        else:
            result = await _run_kickoff(project, brief)
    except Exception as exc:  # noqa: BLE001 — surface any failure in-stream
        yield _sse({"type": "STEP_FINISHED", "stepName": "kickoff"})
        yield _sse({"type": "RUN_ERROR", "message": f"crew kickoff failed: {exc}", "code": "KICKOFF_FAILED"})
        return

    yield _sse(
        {
            "type": "TEXT_MESSAGE_START",
            "messageId": "crew-report",
            "role": "assistant",
        }
    )
    report = result or "(crew returned an empty report)"
    for chunk in (report[i : i + 220] for i in range(0, len(report), 220)):
        yield _sse({"type": "TEXT_MESSAGE_CONTENT", "messageId": "crew-report", "delta": chunk})
        await asyncio.sleep(0)
    yield _sse({"type": "TEXT_MESSAGE_END", "messageId": "crew-report"})
    yield _sse({"type": "STEP_FINISHED", "stepName": "kickoff"})
    yield _sse({"type": "RUN_FINISHED", "threadId": thread_id, "runId": run_id})


async def _stream(body: dict[str, Any]) -> StreamingResponse:
    return StreamingResponse(
        _events(body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/")
async def root(request: Request) -> StreamingResponse:
    """AG-UI endpoint — agents addressed by URL root POST here (HttpAgent default)."""
    return await _stream(await request.json())


@app.post("/copilotkit")
async def copilotkit(request: Request) -> StreamingResponse:
    """AG-UI endpoint — explicit path variant (mirrors the CopilotKit convention)."""
    return await _stream(await request.json())


@app.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok",
        "agent": AGENT_ID,
        "kickoff_url": KICKOFF_URL,
        "echo_mode": ECHO_MODE,
    }


def main() -> None:
    """Entry point: ``uv run bmad-crew-bff``."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("BFF_PORT", "8100")))


if __name__ == "__main__":
    main()
