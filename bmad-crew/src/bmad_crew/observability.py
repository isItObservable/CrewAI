"""OpenTelemetry instrumentation for the BMAD crew.

Per the observability research (ISI-1584): CrewAI is trace-rich but **token-blind by
default**, and emits **no OTLP metrics** out of the box. We adopt **OpenLIT**, which is
OpenTelemetry-native and emits `gen_ai.*` spans *and* GenAI metrics (token usage,
operation duration) directly — so it drops straight into a Collector -> Dynatrace
pipeline with no attribute remapping.

This module is import-safe: if OpenLIT (or the OTLP endpoint) is not present it degrades
to a no-op so the crew still runs. The Collector pipeline and Dynatrace dashboards are
owned by the Observability Agent in ISI-1586; this file is the app-side seam they wire to.

Env:
  OTEL_EXPORTER_OTLP_ENDPOINT   OTLP gateway (e.g. http://otel-collector:4318)
  OTEL_SERVICE_NAME             logical service name (default: bmad-crew)
  OTEL_SDK_DISABLED=true        hard off-switch
  CREWAI_DISABLE_TELEMETRY=true disable CrewAI's own anonymous product telemetry
"""

from __future__ import annotations

import os


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
        otlp_endpoint=endpoint,
        # Capture prompts/completions as span content for the trace waterfall demo.
        # Set OPENLIT_CAPTURE_CONTENT=false to redact in sensitive environments.
        capture_message_content=os.getenv("OPENLIT_CAPTURE_CONTENT", "true").lower()
        == "true",
    )
    return True
