"""OpenTelemetry instrumentation for the BMAD crew.

Per the observability research: CrewAI is trace-rich but **token-blind by
default**, and emits **no OTLP metrics** out of the box. We adopt **OpenLIT**, which is
OpenTelemetry-native and emits `gen_ai.*` spans *and* GenAI metrics (token usage,
operation duration) directly — so it drops straight into a Collector -> Dynatrace
pipeline with no attribute remapping.

This module is import-safe: if OpenLIT (or the OTLP endpoint) is not present it degrades
to a no-op so the crew still runs. The Collector pipeline and Dynatrace dashboards are
owned by the Observability Agent; this file is the app-side seam they wire to.

Env:
  OTEL_EXPORTER_OTLP_ENDPOINT   OTLP gateway (e.g. http://otel-collector:4318)
  OTEL_SERVICE_NAME             logical service name (default: bmad-crew)
  OTEL_SDK_DISABLED=true        hard off-switch
  CREWAI_DISABLE_TELEMETRY=true disable CrewAI's own anonymous product telemetry
"""

from __future__ import annotations

import os

# Output attributes that must never carry a serialized coroutine repr.
_OUTPUT_KEYS = ("gen_ai.output.messages", "output.value")
_COROUTINE_MARKER = "coroutine object"


def _install_coroutine_repr_guard() -> bool:
    """Strip OpenLIT's un-awaited-coroutine repr from CrewAI flow-method spans (ISI-6357 D1).

    CrewAI 1.15.1 runs each agent's reasoning loop as an **internal** ``Flow`` whose
    ``@start``/``@router``/``@listen`` methods (``generate_plan``, ``route_by_answer_type``,
    ``call_llm_and_parse``, ``finalize`` …) are ``async``. OpenLIT wraps these with a
    *synchronous* span and closes the span around the call — so it records the method's
    return value, which for an async method is the un-awaited coroutine
    ``<coroutine object Flow._execute_method at 0x…>`` serialized onto
    ``gen_ai.output.messages`` / ``output.value``. (There is no app-owned ``Flow`` to await;
    the async methods live inside CrewAI itself — see ISI-6356 FIX-DESIGN.)

    The real per-role deliverable text is **not lost** — it lives on the agent-level
    ``invoke_agent <role>`` spans and the sibling ``.task`` span's ``traceloop.entity.output``.
    These internal flow-method spans have no meaningful assistant "output", so we remove the
    garbage key here, at the source, before export. Effect on the raw Phoenix trace the eval
    gate reads: no ``coroutine object`` substring survives, and the agent/task spans keep the
    resolved text the judges score against. The durable upstream fix is OpenLIT making its
    CrewAI flow instrumentation async-aware (await before closing the span); tracked for a
    version bump — this guard is the app-side seam until then.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import SpanProcessor
    except Exception:
        return False

    class _CoroutineReprGuard(SpanProcessor):
        def on_start(self, span, parent_context=None):  # noqa: D401 - interface method
            return None

        def on_end(self, span) -> None:
            try:
                attrs = getattr(span, "_attributes", None)
                if not attrs:
                    return
                for key in _OUTPUT_KEYS:
                    val = attrs.get(key)
                    if isinstance(val, str) and _COROUTINE_MARKER in val:
                        # Remove the key entirely: an internal flow-method span has no real
                        # assistant deliverable, and the eval gate skips absent output keys
                        # (real text is asserted on the agent/task spans that still carry it).
                        try:
                            del attrs[key]
                        except Exception:
                            attrs[key] = ""
            except Exception:
                # Telemetry hygiene must never break a crew run.
                return None

        def shutdown(self) -> None:
            return None

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            return True

    try:
        provider = trace.get_tracer_provider()
        add = getattr(provider, "add_span_processor", None)
        if not callable(add):
            return False  # no-op/proxy provider — nothing to attach to
        add(_CoroutineReprGuard())
        return True
    except Exception:
        return False


def init_observability() -> bool:
    """Initialise OpenLIT OTel instrumentation. Returns True if telemetry is active."""
    if os.getenv("OTEL_SDK_DISABLED", "").lower() == "true":
        return False

    # Silence CrewAI's hard-coded anonymous product telemetry (telemetry.crewai.com) —
    # it is not routable to our backend and we don't want the extra egress.
    os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        # No collector configured — run un-instrumented rather than fail.
        return False

    try:
        import openlit
    except ImportError:
        # OpenLIT not installed; the crew still runs, just without OTel spans/metrics.
        return False

    openlit.init(
        application_name=os.getenv("OTEL_SERVICE_NAME", "bmad-crew"),
        # deployment.environment resource attr — dashboards/filters key off this.
        environment=os.getenv("OTEL_ENVIRONMENT", "observable-crewai"),
        otlp_endpoint=endpoint,
        # GenAI metrics are the whole point (CrewAI is token-blind by default) —
        # make it explicit so a future OpenLIT default change can't silently drop them.
        disable_metrics=False,
        # Capture prompts/completions as span content for the trace waterfall demo.
        # Set OPENLIT_CAPTURE_CONTENT=false to redact in sensitive environments.
        capture_message_content=os.getenv("OPENLIT_CAPTURE_CONTENT", "true").lower()
        == "true",
    )
    # ISI-6357 D1: once OpenLIT has set up the tracer provider, attach the guard that
    # strips its un-awaited-coroutine repr from CrewAI's internal async flow-method spans.
    guard_on = _install_coroutine_repr_guard()
    print(f"[bmad-crew] coroutine-repr guard: {'ON' if guard_on else 'off'}")
    return True
