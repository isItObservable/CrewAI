"""
CrewAI -> OpenTelemetry instrumentation (OTel GenAI semantic conventions).

Why this exists (see the telemetry-gap research):
  * CrewAI 1.15.x ships NO OTLP metrics and, by default, only two coarse spans
    (Crew.kickoff, Task._execute_core). The OpenInference instrumentor can add an
    LLM span but tags it with `llm.token_count.*` (OpenInference semconv), NOT the
    `gen_ai.*` OpenTelemetry GenAI semconv that Dynatrace (<your-tenant>) reads natively.
  * The richest, most reliable telemetry source in CrewAI is its native event bus
    (`crewai.events.crewai_event_bus`): LLMCallCompletedEvent carries real token
    usage {prompt_tokens, completion_tokens, total_tokens}, finish_reason, model.

This listener subscribes to the native event bus and emits, with correct parent/child
nesting, standards-compliant telemetry:
  * TRACES  - crew -> task -> agent -> {llm_call, tool_call} span tree, gen_ai.* attrs
  * METRICS - gen_ai.client.token.usage, gen_ai.client.operation.duration (histograms)
              + crewai.{crew,task,tool}.executions and crewai.errors counters
  * LOGS    - structured OTel LogRecords on lifecycle + failures

Nesting uses EXPLICIT parent context (trace.set_span_in_context) rather than
contextvars attach/detach: CrewAI executes agents across worker threads, so
contextvars do not propagate a parent from the crew thread to the agent/LLM
threads. We instead track the active crew/task/agent span and start each child
with its parent passed explicitly. This yields a correct crew -> task -> agent ->
{llm,tool} tree for the sequential process. For hierarchical/parallel crews the
"current agent" pointer is best-effort (documented limitation).

This module is the reference implementation for the upstream contribution scoped in
a first-party OTel-GenAI exporter over the CrewAI event bus).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

try:  # metrics are optional - degrade gracefully if a MeterProvider is absent
    from opentelemetry import metrics
except Exception:  # pragma: no cover
    metrics = None  # type: ignore

try:
    from opentelemetry._logs import get_logger, std_to_otel  # type: ignore
    from opentelemetry._logs import SeverityNumber
    from opentelemetry.sdk._logs import LogRecord as _OTelLogRecord  # noqa: F401
    _LOGS_OK = True
except Exception:  # pragma: no cover
    _LOGS_OK = False

from crewai.events import BaseEventListener, crewai_event_bus
from crewai.events.event_types import (
    CrewKickoffStartedEvent, CrewKickoffCompletedEvent, CrewKickoffFailedEvent,
    TaskStartedEvent, TaskCompletedEvent, TaskFailedEvent,
    AgentExecutionStartedEvent, AgentExecutionCompletedEvent, AgentExecutionErrorEvent,
    LLMCallStartedEvent, LLMCallCompletedEvent, LLMCallFailedEvent,
    ToolUsageStartedEvent, ToolUsageFinishedEvent, ToolUsageErrorEvent,
)

# OTel GenAI semantic-convention system value.
GEN_AI_SYSTEM = "crewai"


def _get(obj: Any, *names: str, default=None):
    """Read the first present attribute/key from an event (pydantic model or dict)."""
    for n in names:
        if isinstance(obj, dict):
            if obj.get(n) is not None:
                return obj[n]
        else:
            v = getattr(obj, n, None)
            if v is not None:
                return v
    return default


def _usage(event: Any) -> Dict[str, int]:
    """Normalize LLMCallCompletedEvent.usage -> {input, output, total} tokens."""
    u = _get(event, "usage", default={}) or {}
    if not isinstance(u, dict):
        u = getattr(u, "__dict__", {}) or {}
    inp = int(u.get("prompt_tokens", u.get("input_tokens", 0)) or 0)
    out = int(u.get("completion_tokens", u.get("output_tokens", 0)) or 0)
    tot = int(u.get("total_tokens", inp + out) or (inp + out))
    return {"input": inp, "output": out, "total": tot}


class OTelCrewAIListener(BaseEventListener):
    """Maps CrewAI native events to OpenTelemetry traces/metrics/logs (gen_ai semconv)."""

    def __init__(self, service_name: str = "crewai-bmad-crew") -> None:
        super().__init__()
        self._service_name = service_name
        self._tracer = trace.get_tracer("crewai.otel.instrumentation", "0.1.0")
        self._lock = threading.Lock()
        # span registry for correct end(): key -> (span, start_time)
        self._spans: Dict[str, Any] = {}
        # "current" active span per level, for explicit parenting + agent attribution
        self._cur: Dict[str, Any] = {"crew": None, "task": None, "agent": None, "role": None}
        # LIFO stacks for events whose start/complete carry no stable id
        # (CrewAI emits agent_id/task_id as None on agent+llm+tool events).
        self._agent_stack: list = []
        self._llm_stack: list = []
        self._tool_stack: list = []
        self._setup_metrics()
        self._setup_logs()

    # ----------------------------------------------------------------- metrics
    def _setup_metrics(self) -> None:
        self._token_hist = self._dur_hist = None
        self._crew_ctr = self._task_ctr = self._tool_ctr = self._err_ctr = None
        if metrics is None:
            return
        meter = metrics.get_meter("crewai.otel.instrumentation", "0.1.0")
        # OTel GenAI semconv metric names (Dynatrace-native).
        self._token_hist = meter.create_histogram(
            "gen_ai.client.token.usage", unit="{token}",
            description="Number of input/output tokens used per LLM call")
        self._dur_hist = meter.create_histogram(
            "gen_ai.client.operation.duration", unit="s",
            description="Duration of GenAI client operations")
        # CrewAI operational counters (agentic-efficiency).
        self._crew_ctr = meter.create_counter(
            "crewai.crew.executions", unit="{execution}",
            description="Crew kickoff executions")
        self._task_ctr = meter.create_counter(
            "crewai.task.executions", unit="{execution}",
            description="Task executions")
        self._tool_ctr = meter.create_counter(
            "crewai.tool.executions", unit="{execution}",
            description="Tool executions")
        self._err_ctr = meter.create_counter(
            "crewai.errors", unit="{error}",
            description="Errors by signal (crew/task/agent/llm/tool)")

    def _setup_logs(self) -> None:
        self._otel_logger = get_logger(__name__) if _LOGS_OK else None

    def _emit_log(self, body: str, severity: str = "INFO", **attrs) -> None:
        if not self._otel_logger:
            return
        try:
            sev = getattr(SeverityNumber, severity, SeverityNumber.INFO)
            rec = _OTelLogRecord(
                body=body, severity_text=severity, severity_number=sev,
                attributes={"gen_ai.system": GEN_AI_SYSTEM, **attrs})
            self._otel_logger.emit(rec)
        except Exception:
            pass

    # ------------------------------------------------------------- span helpers
    def _ctx(self, parent):
        """OTel context that parents a new span under `parent` (None -> root)."""
        return trace.set_span_in_context(parent) if parent is not None else None

    def _start(self, key: str, name: str, kind: SpanKind,
               attrs: Dict[str, Any], parent=None) -> Any:
        span = self._tracer.start_span(
            name, kind=kind, attributes=_clean(attrs), context=self._ctx(parent))
        with self._lock:
            self._spans[key] = (span, time.time())
        return span

    def _end(self, key: str, attrs: Optional[Dict[str, Any]] = None,
             status: Optional[Status] = None) -> Optional[float]:
        with self._lock:
            entry = self._spans.pop(key, None)
        if not entry:
            return None
        span, started = entry
        if attrs:
            for k, v in _clean(attrs).items():
                span.set_attribute(k, v)
        if status is not None:
            span.set_status(status)
        span.end()
        return time.time() - started

    def _pop_agent(self, status: Status, attrs: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            entry = self._agent_stack.pop() if self._agent_stack else None
            top = self._agent_stack[-1] if self._agent_stack else None
            self._cur["agent"] = top[0] if top else None
            self._cur["role"] = top[1] if top else None
        if entry is None:
            return
        span = entry[0]
        if attrs:
            for k, v in _clean(attrs).items():
                span.set_attribute(k, v)
        span.set_status(status)
        span.end()

    # ------------------------------------------------------------- registration
    def setup_listeners(self, bus) -> None:  # noqa: C901 - explicit is clearer here
        # ---- Crew lifecycle -------------------------------------------------
        @bus.on(CrewKickoffStartedEvent)
        def _(source, event):
            name = _get(event, "crew_name", default="crew")
            span = self._start(_ck(event), f"crew {name}", SpanKind.SERVER, {
                "gen_ai.system": GEN_AI_SYSTEM,
                "gen_ai.operation.name": "invoke_agent",
                "crewai.crew.name": name,
                "service.name": self._service_name,
            }, parent=None)
            with self._lock:
                self._cur["crew"] = span
            if self._crew_ctr:
                self._crew_ctr.add(1, {"crew.name": str(name)})
            self._emit_log(f"crew kickoff started: {name}", "INFO",
                           **{"crewai.crew.name": str(name)})

        @bus.on(CrewKickoffCompletedEvent)
        def _(source, event):
            self._end(_ck(event), status=Status(StatusCode.OK))
            with self._lock:
                self._cur["crew"] = None

        @bus.on(CrewKickoffFailedEvent)
        def _(source, event):
            err = str(_get(event, "error", default="crew failed"))
            self._end(_ck(event), {"error.type": "CrewKickoffFailed"},
                      Status(StatusCode.ERROR, err))
            with self._lock:
                self._cur["crew"] = None
            if self._err_ctr:
                self._err_ctr.add(1, {"signal": "crew"})
            self._emit_log(f"crew failed: {err}", "ERROR")

        # ---- Task lifecycle -------------------------------------------------
        @bus.on(TaskStartedEvent)
        def _(source, event):
            tname = _tname(event)
            with self._lock:
                parent = self._cur["crew"]
            span = self._start(_tk(event), f"task {tname}", SpanKind.INTERNAL, {
                "gen_ai.system": GEN_AI_SYSTEM,
                "gen_ai.operation.name": "invoke_agent",
                "crewai.task.id": str(_get(event, "task_id", default="")),
                "crewai.task.name": tname,
            }, parent=parent)
            with self._lock:
                self._cur["task"] = span

        @bus.on(TaskCompletedEvent)
        def _(source, event):
            self._end(_tk(event), status=Status(StatusCode.OK))
            with self._lock:
                self._cur["task"] = None
            if self._task_ctr:
                self._task_ctr.add(1, {"status": "ok"})

        @bus.on(TaskFailedEvent)
        def _(source, event):
            err = str(_get(event, "error", default="task failed"))
            self._end(_tk(event), {"error.type": "TaskFailed"},
                      Status(StatusCode.ERROR, err))
            with self._lock:
                self._cur["task"] = None
            if self._task_ctr:
                self._task_ctr.add(1, {"status": "error"})
            if self._err_ctr:
                self._err_ctr.add(1, {"signal": "task"})
            self._emit_log(f"task failed: {err}", "ERROR")

        # ---- Agent execution (LIFO stack; ids arrive as None) ---------------
        @bus.on(AgentExecutionStartedEvent)
        def _(source, event):
            role = _role(event)
            with self._lock:
                parent = self._cur["task"] or self._cur["crew"]
            span = self._tracer.start_span(
                f"agent {role}", kind=SpanKind.INTERNAL, context=self._ctx(parent),
                attributes=_clean({
                    "gen_ai.system": GEN_AI_SYSTEM,
                    "gen_ai.operation.name": "invoke_agent",
                    "gen_ai.agent.name": role,
                }))
            with self._lock:
                self._agent_stack.append((span, role))
                self._cur["agent"] = span
                self._cur["role"] = role

        @bus.on(AgentExecutionCompletedEvent)
        def _(source, event):
            self._pop_agent(Status(StatusCode.OK))

        @bus.on(AgentExecutionErrorEvent)
        def _(source, event):
            err = str(_get(event, "error", default="agent error"))
            self._pop_agent(Status(StatusCode.ERROR, err), {"error.type": "AgentExecutionError"})
            if self._err_ctr:
                self._err_ctr.add(1, {"signal": "agent"})
            self._emit_log(f"agent error: {err}", "ERROR")

        # ---- LLM calls (gen_ai semconv + token metrics) ---------------------
        @bus.on(LLMCallStartedEvent)
        def _(source, event):
            model = _get(event, "model", default="unknown")
            with self._lock:
                parent = self._cur["agent"] or self._cur["task"] or self._cur["crew"]
                role = self._cur["role"]
            span = self._tracer.start_span(
                f"chat {model}", kind=SpanKind.CLIENT, context=self._ctx(parent),
                attributes=_clean({
                    "gen_ai.system": GEN_AI_SYSTEM,
                    "gen_ai.operation.name": "chat",
                    "gen_ai.request.model": model,
                    "gen_ai.agent.name": role,  # attribute tokens to the running agent
                }))
            with self._lock:
                self._llm_stack.append((span, time.time(), model, role))

        @bus.on(LLMCallCompletedEvent)
        def _(source, event):
            with self._lock:
                entry = self._llm_stack.pop() if self._llm_stack else None
            if not entry:
                return
            span, started, model, role = entry
            dur = time.time() - started
            u = _usage(event)
            model = _get(event, "model", default=model)
            finish = _get(event, "finish_reason", default=None)
            span.set_attributes(_clean({
                "gen_ai.response.model": model,
                "gen_ai.usage.input_tokens": u["input"],
                "gen_ai.usage.output_tokens": u["output"],
                "gen_ai.usage.total_tokens": u["total"],
                "gen_ai.response.finish_reasons": [str(finish)] if finish else None,
                "gen_ai.response.id": _get(event, "response_id", default=None),
            }))
            span.set_status(Status(StatusCode.OK))
            span.end()
            # metrics
            base = {"gen_ai.system": GEN_AI_SYSTEM, "gen_ai.request.model": str(model),
                    "gen_ai.operation.name": "chat", "gen_ai.agent.name": str(role or "")}
            if self._token_hist:
                self._token_hist.record(u["input"], {**base, "gen_ai.token.type": "input"})
                self._token_hist.record(u["output"], {**base, "gen_ai.token.type": "output"})
            if self._dur_hist:
                self._dur_hist.record(dur, base)

        @bus.on(LLMCallFailedEvent)
        def _(source, event):
            with self._lock:
                entry = self._llm_stack.pop() if self._llm_stack else None
            if entry:
                span = entry[0]
                span.set_status(Status(StatusCode.ERROR, str(_get(event, "error", default="llm failed"))))
                span.end()
            if self._err_ctr:
                self._err_ctr.add(1, {"signal": "llm"})
            self._emit_log("llm call failed", "ERROR")

        # ---- Tool usage -----------------------------------------------------
        @bus.on(ToolUsageStartedEvent)
        def _(source, event):
            tool = _get(event, "tool_name", default="tool")
            with self._lock:
                parent = self._cur["agent"] or self._cur["task"] or self._cur["crew"]
            span = self._tracer.start_span(
                f"tool {tool}", kind=SpanKind.INTERNAL, context=self._ctx(parent),
                attributes=_clean({
                    "gen_ai.system": GEN_AI_SYSTEM,
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": tool,
                }))
            with self._lock:
                self._tool_stack.append((span, tool))

        @bus.on(ToolUsageFinishedEvent)
        def _(source, event):
            with self._lock:
                entry = self._tool_stack.pop() if self._tool_stack else None
            if not entry:
                return
            span, tool = entry
            span.set_status(Status(StatusCode.OK))
            span.end()
            if self._tool_ctr:
                self._tool_ctr.add(1, {"tool.name": str(tool), "status": "ok"})

        @bus.on(ToolUsageErrorEvent)
        def _(source, event):
            with self._lock:
                entry = self._tool_stack.pop() if self._tool_stack else None
            if entry:
                span, tool = entry
                span.set_status(Status(StatusCode.ERROR, str(_get(event, "error", default="tool error"))))
                span.end()
                if self._tool_ctr:
                    self._tool_ctr.add(1, {"tool.name": str(tool), "status": "error"})
            if self._err_ctr:
                self._err_ctr.add(1, {"signal": "tool"})
            self._emit_log("tool error", "ERROR")


# ---- correlation keys (stable per event object) ---------------------------
def _ck(e) -> str:
    return f"crew:{_get(e, 'crew_name', default='crew')}"


def _tk(e) -> str:
    return f"task:{_get(e, 'task_id', default=id(e))}"


def _role(e) -> str:
    """Agent role. CrewAI emits top-level agent_role=None; read nested event.agent.role."""
    agent = _get(e, "agent")
    if agent is not None:
        r = getattr(agent, "role", None) if not isinstance(agent, dict) else agent.get("role")
        if r:
            return str(r)
    return str(_get(e, "agent_role", default="agent"))


def _tname(e) -> str:
    """Task display name. Prefer explicit task_name, else nested task.description (truncated)."""
    tn = _get(e, "task_name")
    if tn:
        return str(tn)
    task = _get(e, "task")
    if task is not None:
        desc = getattr(task, "description", None) if not isinstance(task, dict) else task.get("description")
        if desc:
            return str(desc)[:60]
    return "task"


def _clean(attrs: Dict[str, Any]) -> Dict[str, Any]:
    """Drop None values; OTel rejects None attribute values."""
    return {k: v for k, v in attrs.items() if v is not None}


_LISTENER: Optional[OTelCrewAIListener] = None


def instrument_crewai(service_name: str = "crewai-bmad-crew") -> OTelCrewAIListener:
    """Idempotently install the CrewAI->OTel event listener. Returns the singleton."""
    global _LISTENER
    if _LISTENER is None:
        _LISTENER = OTelCrewAIListener(service_name=service_name)
    return _LISTENER
