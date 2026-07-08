"""
OpenTelemetry SDK bootstrap for the CrewAI BMAD crew.

Wires TracerProvider + MeterProvider + LoggerProvider with OTLP exporters that
point at the OpenTelemetry Collector (which forwards to Dynatrace, <your-tenant>).
All endpoints/headers come from the standard OTEL_* environment variables so the
same code runs locally, in Docker, and in Kubernetes with no edits:

    OTEL_EXPORTER_OTLP_ENDPOINT   e.g. http://otel-collector:4317  (gRPC)
    OTEL_EXPORTER_OTLP_PROTOCOL   grpc | http/protobuf   (default grpc here)
    OTEL_SERVICE_NAME             defaults to crewai-bmad-crew
    OTEL_RESOURCE_ATTRIBUTES      e.g. deployment.environment=demo

Call `init_otel()` ONCE at process start, BEFORE `instrument_crewai()`.
"""
from __future__ import annotations

import os
from typing import Optional

from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

_PROTO = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").lower()

if _PROTO.startswith("http"):
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
else:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry._logs import set_logger_provider

_INITIALIZED = False


def _resource() -> Resource:
    attrs = {
        "service.name": os.getenv("OTEL_SERVICE_NAME", "crewai-bmad-crew"),
        "service.namespace": "crewai",
        "telemetry.sdk.language": "python",
    }
    return Resource.create(attrs)  # OTEL_RESOURCE_ATTRIBUTES is merged automatically


def init_otel(service_name: Optional[str] = None) -> None:
    """Idempotently configure global OTel providers (traces + metrics + logs)."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    if service_name:
        os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
    res = _resource()

    # Traces
    tp = TracerProvider(resource=res)
    tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tp)

    # Metrics (periodic push to the collector, default 60s)
    reader = PeriodicExportingMetricReader(OTLPMetricExporter())
    metrics.set_meter_provider(MeterProvider(resource=res, metric_readers=[reader]))

    # Logs (OTel log signal + bridge from stdlib logging)
    lp = LoggerProvider(resource=res)
    lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(lp)
    import logging
    logging.getLogger().addHandler(LoggingHandler(level=logging.INFO, logger_provider=lp))

    _INITIALIZED = True
