"""OpenTelemetry instrumentation for the BMAD crew.

Supports three vendor-neutral instrumentation paths, selected at runtime via
the CREWAI_INSTRUMENTATION env var:

  CREWAI_INSTRUMENTATION=openlit       (default) OpenLIT auto-instrumentation.
                                        gen_ai.* spans + GenAI metrics. Easiest
                                        to set up; single pip dependency.
  CREWAI_INSTRUMENTATION=openllmetry   Traceloop auto-instrumentation. Great if
                                        you already live in the OTel ecosystem.
  CREWAI_INSTRUMENTATION=native        Native CrewAI event-bus listener. Full
                                        control; only the OTel SDK required.

All three paths route to the same Collector → Dynatrace pipeline and degrade
gracefully when a dependency is missing — the crew still runs.

Common env vars:
  OTEL_EXPORTER_OTLP_ENDPOINT   OTLP gateway (e.g. http://otel-collector:4318)
  OTEL_SERVICE_NAME             logical service name (default: bmad-crew)
  OTEL_ENVIRONMENT              deployment.environment tag
  OTEL_SDK_DISABLED=true        hard off-switch for all paths
  CREWAI_DISABLE_TELEMETRY=true disable CrewAI's own anonymous telemetry
  CREWAI_INSTRUMENTATION        openlit | openllmetry | native (default: openlit)

Path-specific env vars:
  OPENLIT_CAPTURE_CONTENT       true|false — capture prompts/completions (openlit)
  OPENLLMETRY_CAPTURE_CONTENT   true|false — same toggle for openllmetry
  OTEL_EXPORTER_OTLP_PROTOCOL   grpc | http/protobuf (native path, default http/protobuf)
"""

from __future__ import annotations

import os


def init_observability() -> bool:
    """Initialise OTel instrumentation for the selected path.

    Returns True if telemetry is active, False if disabled or unavailable.
    """
    if os.getenv("OTEL_SDK_DISABLED", "").lower() == "true":
        return False

    # Silence CrewAI's hardcoded anonymous telemetry.crewai.com analytics.
    os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        # No collector configured — run un-instrumented rather than fail.
        return False

    path = os.getenv("CREWAI_INSTRUMENTATION", "openlit").lower().strip()

    if path == "openlit":
        return _init_openlit(endpoint)
    if path == "openllmetry":
        return _init_openllmetry(endpoint)
    if path == "native":
        return _init_native(endpoint)

    print(
        f"[bmad-crew] Unknown CREWAI_INSTRUMENTATION={path!r}. "
        "Valid values: openlit, openllmetry, native. Falling back to openlit."
    )
    return _init_openlit(endpoint)


# ---------------------------------------------------------------------------
# Path A — OpenLIT
# ---------------------------------------------------------------------------

def _init_openlit(endpoint: str) -> bool:
    """OpenLIT auto-instrumentation (gen_ai.* spans + GenAI metrics)."""
    try:
        import openlit
    except ImportError:
        print("[bmad-crew] openlit not installed — run: pip install openlit")
        return False

    openlit.init(
        application_name=os.getenv("OTEL_SERVICE_NAME", "bmad-crew"),
        # deployment.environment resource attr — dashboards filter on this.
        environment=os.getenv("OTEL_ENVIRONMENT", "observable-crewai"),
        otlp_endpoint=endpoint,
        # GenAI metrics are the whole point (CrewAI is token-blind by default).
        disable_metrics=False,
        # Capture prompts/completions for the trace waterfall demo.
        # Set OPENLIT_CAPTURE_CONTENT=false to redact in sensitive environments.
        capture_message_content=os.getenv("OPENLIT_CAPTURE_CONTENT", "true").lower() == "true",
    )
    print("[bmad-crew] Instrumentation path: OpenLIT")
    return True


# ---------------------------------------------------------------------------
# Path B — OpenLLMetry (Traceloop)
# ---------------------------------------------------------------------------

def _init_openllmetry(endpoint: str) -> bool:
    """Traceloop (OpenLLMetry) auto-instrumentation.

    Attribute shape differs slightly from OpenLIT — see OBSERVABILITY.md §3
    and the Collector transform processor for the bridging rules.
    """
    # Suppress Traceloop's own product-analytics ping; stay vendor-neutral.
    os.environ.setdefault("TRACELOOP_TELEMETRY", "false")
    # Traceloop reads its OTLP base from TRACELOOP_BASE_URL and appends /v1/traces.
    os.environ.setdefault("TRACELOOP_BASE_URL", endpoint)
    capture = os.getenv("OPENLLMETRY_CAPTURE_CONTENT", "true").lower() == "true"
    os.environ.setdefault("TRACELOOP_TRACE_CONTENT", "true" if capture else "false")

    try:
        from traceloop.sdk import Traceloop
    except ImportError:
        print(
            "[bmad-crew] traceloop-sdk not installed — run: pip install traceloop-sdk\n"
            "            or uncomment it in observability/requirements-observability.txt"
        )
        return False

    Traceloop.init(
        app_name=os.getenv("OTEL_SERVICE_NAME", "bmad-crew"),
        disable_batch=False,
    )
    print("[bmad-crew] Instrumentation path: OpenLLMetry (Traceloop)")
    return True


# ---------------------------------------------------------------------------
# Path C — Native CrewAI event-bus → OTel SDK
# ---------------------------------------------------------------------------

def _init_native(endpoint: str) -> bool:  # noqa: C901
    """Native event-bus listener: wires OTel SDK providers + the CrewAI listener.

    The listener (observability/instrumentation/crewai_otel.py) subscribes to
    CrewAI's internal event bus and emits gen_ai.* spans, token-usage histograms,
    and OTel LogRecords — all without any third-party auto-instrumentation library.
    """
    # ---- 1. Bootstrap OTel SDK providers ------------------------------------
    try:
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    except ImportError:
        print("[bmad-crew] opentelemetry-sdk not installed — run: pip install opentelemetry-sdk")
        return False

    proto = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf").lower()
    try:
        if proto.startswith("http"):
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        else:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    except ImportError:
        print("[bmad-crew] OTLP exporters not installed — run: pip install opentelemetry-exporter-otlp")
        return False

    service_name = os.getenv("OTEL_SERVICE_NAME", "bmad-crew")
    resource = Resource.create({
        "service.name": service_name,
        "service.namespace": "crewai",
        "deployment.environment": os.getenv("OTEL_ENVIRONMENT", "observable-crewai"),
        "telemetry.sdk.language": "python",
    })

    # Traces — OTEL_EXPORTER_OTLP_ENDPOINT picked up from env by the exporter.
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tp)

    # Metrics (periodic push, default 60 s interval).
    mp = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
    )
    metrics.set_meter_provider(mp)

    # ---- 2. Wire the native event-bus listener --------------------------------
    # The listener lives at observability/instrumentation/crewai_otel.py,
    # relative to the tutorial root (four levels up from this file).
    import sys
    import pathlib

    _tutorial_root = pathlib.Path(__file__).resolve().parent.parent.parent.parent
    if str(_tutorial_root) not in sys.path:
        sys.path.insert(0, str(_tutorial_root))

    try:
        from observability.instrumentation.crewai_otel import instrument_crewai  # type: ignore
        instrument_crewai(service_name=service_name)
        print("[bmad-crew] Instrumentation path: Native event-bus (crewai_otel)")
    except ImportError:
        print(
            "[bmad-crew] Native listener (crewai_otel) not found. "
            f"Expected observability/instrumentation/ under {_tutorial_root}. "
            "OTel providers are active but no CrewAI-specific spans will be emitted."
        )

    return True
