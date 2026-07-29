"""
CrewAI observability instrumentation (OpenTelemetry, gen_ai semconv).

One-line wiring for a crew:

    from observability.instrumentation import init_otel, instrument_crewai
    init_otel(service_name="crewai-bmad-crew")   # OTel SDK -> OTLP collector
    instrument_crewai()                          # CrewAI event bus -> OTel signals
    # ... then build and kickoff your crew as usual.

`init_otel` reads standard OTEL_* env vars (endpoint, protocol, headers). See
otel_bootstrap.py. Disable CrewAI's anonymous product analytics separately with
`CREWAI_DISABLE_TELEMETRY=true`.
"""
from .otel_bootstrap import init_otel
from .crewai_otel import instrument_crewai, OTelCrewAIListener

__all__ = ["init_otel", "instrument_crewai", "OTelCrewAIListener"]
