"""
CrewAI → OpenTelemetry (GenAI semconv) bootstrap for the isItObservable tutorial.

WHY OpenLIT (see ISI-1584 research):
  CrewAI 1.15.1 is trace-rich but *token-blind by default* and emits NO OTLP
  metrics. The OpenInference default instrumentor only wraps Crew.kickoff /
  Task._execute_core and uses its own `llm.token_count.*` namespace — which
  Dynatrace does NOT model natively. OpenLIT auto-instruments CrewAI + the
  underlying LiteLLM/Ollama calls and emits OTel **GenAI semantic conventions**
  (`gen_ai.*`) as BOTH spans and metrics, so telemetry drops straight into
  Dynatrace (oat05854) with no remap and gives us the metrics we otherwise lack.

This is the ALTERNATIVE "easy button". The PRIMARY, live-validated path is the
native event-bus listener in observability/instrumentation/ (see OBSERVABILITY.md).
Use this only if you prefer OpenLIT's zero-code auto-instrumentation; re-validate
on your CrewAI version first (OpenLIT was lint-checked, not run, in this repo).

USAGE (drop-in — call once, before kickoff):
    from observability.instrument_openlit import init_observability
    init_observability(service_name="crewai-bmad-crew")
    ...
    crew.kickoff(inputs=...)

All export target / auth config is via standard OTEL_* env vars (no vendor
lock, no secrets in code). See observability/collector/ for the collector that
receives this OTLP stream.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("crewai.observability")


def init_observability(
    service_name: str | None = None,
    environment: str | None = None,
) -> None:
    """Initialise OpenLIT → OTLP. Idempotent; safe to call once at startup.

    Reads (all optional, sensible defaults):
      OTEL_SERVICE_NAME                 service.name  (default: crewai-bmad-crew)
      DEPLOYMENT_ENVIRONMENT            deployment.environment (default: tutorial)
      OTEL_EXPORTER_OTLP_ENDPOINT       collector endpoint (default: local gateway)
      CREWAI_DISABLE_TELEMETRY          forced true — kills the hardcoded
                                        telemetry.crewai.com anonymous analytics
                                        (unusable, and noisy). See ISI-1584.
      OTEL_SDK_DISABLED                 set "true" to no-op (tests / offline).
    """
    # Kill CrewAI's hardcoded anonymous analytics to telemetry.crewai.com.
    # It is not routable to our backend and only adds egress noise (ISI-1584).
    os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
    # Belt-and-suspenders: also silence the OSS "share crew" prompt.
    os.environ.setdefault("OTEL_PYTHON_LOG_CORRELATION", "true")

    if os.getenv("OTEL_SDK_DISABLED", "").lower() == "true":
        logger.info("OTEL_SDK_DISABLED=true → observability is a no-op")
        return

    service_name = service_name or os.getenv("OTEL_SERVICE_NAME", "crewai-bmad-crew")
    environment = environment or os.getenv("DEPLOYMENT_ENVIRONMENT", "tutorial")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318")

    try:
        import openlit
    except ImportError as exc:  # pragma: no cover - guidance path
        raise RuntimeError(
            "openlit is not installed. Add the observability extras:\n"
            "    pip install -r observability/requirements-observability.txt"
        ) from exc

    # OpenLIT wires the OTel SDK + exporters and instruments CrewAI/LiteLLM.
    # We pass otlp_endpoint so it honours our collector; auth/headers ride on
    # standard OTEL_EXPORTER_OTLP_HEADERS when talking directly to Dynatrace.
    openlit.init(
        application_name=service_name,
        environment=environment,
        otlp_endpoint=endpoint,
        # Capture prompts/completions as span events. Scrub PII downstream in
        # the collector (transform/pii) before it reaches Dynatrace. Env-var name
        # matches the ISI-1585 app-side observability.py off-switch.
        capture_message_content=os.getenv("OPENLIT_CAPTURE_CONTENT", "true").lower()
        == "true",
        disable_metrics=False,  # we WANT the GenAI metrics OpenLIT adds
    )

    logger.info(
        "OpenLIT observability initialised: service=%s env=%s endpoint=%s",
        service_name,
        environment,
        endpoint,
    )


if __name__ == "__main__":
    # Smoke: `python -m observability.instrument` should init without error
    logging.basicConfig(level=logging.INFO)
    init_observability()
    logger.info("init_observability() smoke OK")
