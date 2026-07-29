"""
CrewAI → OpenTelemetry (GenAI semconv) bootstrap via **OpenLLMetry (Traceloop)**.

WHY a third option (see the telemetry-gap research):
  CrewAI 1.15.1 is trace-rich but *token-blind by default* and emits NO OTLP
  metrics. This tutorial ships THREE vendor-neutral, no-crew-code-change ways to
  close that gap — all emit OpenTelemetry and flow through the same Collector →
  Dynatrace pipeline (see OBSERVABILITY.md §3):

    1. OpenLIT              — the shipped "easy button" (instrument_openlit.py /
                             the app's observability.py). Emits gen_ai.* spans +
                             GenAI metrics; gen_ai.system == "crewai".
    2. OpenLLMetry (this)   — Traceloop's one-line auto-instrumentation. Great if
                             you already live in the Traceloop/OpenTelemetry
                             ecosystem. See the ATTRIBUTE-PARITY note below.
    3. Native event-bus     — full-control reference listener
                             (observability/instrumentation/). gen_ai.* by hand.

ATTRIBUTE PARITY — read before you rely on the shipped dashboards:
  OpenLLMetry is OTel-GenAI-aligned but does NOT emit the exact same attribute
  shape as OpenLIT / the native listener. Confirmed on the Traceloop semconv:
    - Token usage:  gen_ai.usage.prompt_tokens / completion_tokens / total_tokens
                    (the shipped "Agentic Efficiency" dashboard already coalesces
                    prompt/completion AND input/output, so token tiles light up).
    - Framework spans carry traceloop.span.kind (workflow|task|agent|tool) and
                    traceloop.entity.name — NOT gen_ai.operation.name /
                    gen_ai.agent.name / gen_ai.tool.name.
    - gen_ai.system on model-call spans is the LLM *vendor* (e.g. "ollama"),
                    NOT "crewai".
  The Collector `transform` in observability/collector/ bridges the token, agent
  and tool attributes back to the canonical shape. The one residual — the strict
  `gen_ai.system == "crewai"` dashboard filter — is handled by an OPT-IN
  (commented) transform statement; enable it to reuse the dashboards verbatim on
  this path. Always re-validate the exact attribute names against *your* pinned
  Traceloop version before trusting a tile.

USAGE (drop-in — call once, before kickoff):
    from observability.instrument_openllmetry import init_observability
    init_observability(service_name="crewai-bmad-crew")
    ...
    crew.kickoff(inputs=...)

All export target / auth config is via standard OTEL_* env vars (no vendor lock,
no secrets in code). The Collector holds the Dynatrace token, not the app.
The three instrumentation paths are MUTUALLY EXCLUSIVE — pick one.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("crewai.observability")


def init_observability(
    service_name: str | None = None,
    environment: str | None = None,
) -> None:
    """Initialise OpenLLMetry (Traceloop) → OTLP. Idempotent; call once at startup.

    Reads (all optional, sensible defaults):
      OTEL_SERVICE_NAME             service.name  (default: crewai-bmad-crew)
      DEPLOYMENT_ENVIRONMENT        deployment.environment (default: tutorial)
      OTEL_EXPORTER_OTLP_ENDPOINT   collector OTLP/HTTP base (default: local gateway).
                                    Traceloop exports OTLP to <base>/v1/{traces,metrics}.
      OPENLLMETRY_CAPTURE_CONTENT   "false" to stop capturing prompt/completion text
                                    (PII). Mapped to TRACELOOP_TRACE_CONTENT. Default
                                    "true" — scrub downstream in the Collector.
      CREWAI_DISABLE_TELEMETRY      forced true — kills the hardcoded
                                    telemetry.crewai.com anonymous analytics.
      OTEL_SDK_DISABLED             set "true" to no-op (tests / offline).
    """
    # Kill CrewAI's hardcoded anonymous analytics to telemetry.crewai.com — it is
    # not routable to our backend and only adds egress noise.
    os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
    # Silence Traceloop's own product-analytics ping; we stay vendor-neutral.
    os.environ.setdefault("TRACELOOP_TELEMETRY", "false")

    if os.getenv("OTEL_SDK_DISABLED", "").lower() == "true":
        logger.info("OTEL_SDK_DISABLED=true → observability is a no-op")
        return

    service_name = service_name or os.getenv("OTEL_SERVICE_NAME", "crewai-bmad-crew")
    environment = environment or os.getenv("DEPLOYMENT_ENVIRONMENT", "tutorial")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318")

    # Traceloop reads its OTLP base from TRACELOOP_BASE_URL and appends /v1/traces.
    # Honour the standard OTEL_EXPORTER_OTLP_ENDPOINT so all three paths configure
    # the collector the same way.
    os.environ.setdefault("TRACELOOP_BASE_URL", endpoint)
    # Prompt/completion capture off-switch (PII). Name matches the OpenLIT path's
    # OPENLIT_CAPTURE_CONTENT so the two toggles read alike.
    capture = os.getenv("OPENLLMETRY_CAPTURE_CONTENT", "true").lower() == "true"
    os.environ.setdefault("TRACELOOP_TRACE_CONTENT", "true" if capture else "false")
    os.environ.setdefault("DEPLOYMENT_ENVIRONMENT", environment)

    try:
        from traceloop.sdk import Traceloop
    except ImportError as exc:  # pragma: no cover - guidance path
        raise RuntimeError(
            "traceloop-sdk (OpenLLMetry) is not installed. Enable the extra:\n"
            "    # uncomment `traceloop-sdk` in "
            "observability/requirements-observability.txt\n"
            "    pip install -r observability/requirements-observability.txt"
        ) from exc

    # disable_batch=False → use the batching span processor (production default).
    # OTLP endpoint/headers ride on TRACELOOP_BASE_URL / OTEL_EXPORTER_OTLP_HEADERS.
    Traceloop.init(
        app_name=service_name,
        disable_batch=False,
    )

    logger.info(
        "OpenLLMetry (Traceloop) observability initialised: service=%s env=%s "
        "endpoint=%s capture_content=%s",
        service_name,
        environment,
        endpoint,
        capture,
    )


if __name__ == "__main__":
    # Smoke: `python -m observability.instrument_openllmetry` inits without error.
    logging.basicConfig(level=logging.INFO)
    init_observability()
    logger.info("init_observability() smoke OK")
