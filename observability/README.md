# Observability — BMAD crew (CrewAI)

> **Ownership.** The application-side instrumentation seam lives in this repo
> (`bmad-crew/src/bmad_crew/observability.py`, OpenLIT). The **production Collector,
> Dynatrace dashboards, and end-to-end token validation are owned by the Observability
> Observability Agent**. This page is the alignment contract between the two.

## The one thing to know

Per the telemetry research: **CrewAI is trace-rich but token-blind by
default and emits no OTLP metrics.** Its default instrumentors (OpenInference) produce
only CHAIN + AGENT spans — no LLM span, no token counts, no tool spans.

**We fix this by adopting [OpenLIT](https://openlit.io)** (OpenTelemetry-native), which
emits `gen_ai.*` spans **and** GenAI metrics (`gen_ai.client.token.usage`,
`gen_ai.client.operation.duration`) directly. That drops straight into a
Collector → Dynatrace pipeline with **no attribute remapping**.

## Signal flow

```
BMAD crew pod (OpenLIT, gen_ai.* OTLP)
      │  OTLP/HTTP :4318
      ▼
OTel Collector gateway  (k8s/otel-collector.yaml — starter config)
      │  memory_limiter → k8sattributes → batch
      ▼
Dynatrace (tenant <your-tenant>, native gen_ai.* model)
```

## What the app emits (for the dashboard builder)

- Spans: `chat <model>` (LLM), agent execution, workflow kickoff — a clean linear waterfall
  `invoke_workflow <name> → invoke_agent <role> → chat <model>` for the sequential BMAD
  pipeline (names verified live, OpenLIT 1.42.1; `create_agent <role>` spans appear at
  crew build-time).
- `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
  `gen_ai.response.finish_reasons`, `gen_ai.operation.name`.
- GenAI metrics: token-usage histogram + operation-duration histogram.

## Suggested dashboards

- **CrewAI Agentic Efficiency** — tokens/run, tokens per agent/model, LLM latency
  p50/p90, estimated cost, LLM error rate.
- **CrewAI Crew Health** — kickoff success/error rate + duration, task duration by
  agent, agent execution errors, tool call rate/errors.
- **Trace waterfall** — per-task drilldown of the pipeline.

## Enabling it

Set `OTEL_EXPORTER_OTLP_ENDPOINT` (ConfigMap in k8s, `.env` locally). Unset → the app
runs un-instrumented (no crash). `OTEL_SDK_DISABLED=true` hard-off. CrewAI's own
anonymous product telemetry is disabled by default (`CREWAI_DISABLE_TELEMETRY=true`).

