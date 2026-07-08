# Observability for the CrewAI BMAD Crew

This section shows how to make the CrewAI BMAD crew **fully observable** with
OpenTelemetry — traces, metrics, and logs — and read the result in Dynatrace.
It is the observability track of the CrewAI episode; the telemetry
gap analysis behind these choices is in the research doc.

> **TL;DR** — CrewAI 1.15 emits rich internal *events* but, out of the box, **no
> OTLP metrics** and only two coarse spans, tagged with the wrong semantic
> convention for Dynatrace. We close that with a small event-bus → OpenTelemetry
> listener that emits standards-compliant `gen_ai.*` spans + metrics + logs, then
> route them through an OTel Collector to Dynatrace (<your-tenant>).

---

## 1. Why CrewAI needs help here

CrewAI has three telemetry surfaces:

| Surface | What it is | Verdict |
|---|---|---|
| Anonymous product analytics | hardcoded to `telemetry.crewai.com` | Not usable — disable with `CREWAI_DISABLE_TELEMETRY=true`. |
| AMP hosted tracing (`tracing=True`) | CrewAI Enterprise SaaS | Off-topic for a vendor-neutral OTel pipeline. |
| **Native event bus** (`crewai_event_bus`) | 160+ typed lifecycle events | **The gold mine.** `LLMCallCompletedEvent` carries real token usage, model, and finish reason. |

The popular `openinference-instrumentation-crewai` path, by default, produces only
`Crew.kickoff` + `Task._execute_core` spans — **no LLM span, no tokens, no tool
spans** — and when it does emit an LLM span it uses OpenInference attributes
(`llm.token_count.*`), **not** the OpenTelemetry GenAI convention (`gen_ai.*`) that
Dynatrace reads natively. CrewAI 1.15 also dropped its `litellm` dependency, so the
`openinference-instrumentation-litellm` hook is a **no-op**.

**Our approach:** subscribe to the native event bus and emit correct `gen_ai.*`
telemetry ourselves. This is vendor-neutral, needs no CrewAI code changes, and
doubles as the reference implementation for the upstream contribution.

---

## 2. Architecture

```
  ┌──────────────────────────┐   OTLP (gRPC/HTTP)   ┌───────────────────┐   /api/v2/otlp
  │  CrewAI BMAD crew        │ ───────────────────▶ │  OTel Collector   │ ─────────────▶  Dynatrace
  │  + crewai_otel listener  │   traces/metrics/logs│  (contrib)        │   Api-Token     (<your-tenant>)
  └──────────────────────────┘                      └───────────────────┘
        gen_ai.* spans                                memory_limiter → … → batch
        gen_ai.client.token.usage
        crewai.* counters + logs
```

Emitted signals:

- **Traces** — a clean `crew → task → agent → {chat, tool}` span tree. LLM spans
  (`chat <model>`) carry `gen_ai.usage.input_tokens` / `output_tokens` /
  `total_tokens`, `gen_ai.request.model`, `gen_ai.response.finish_reasons`, and the
  running `gen_ai.agent.name` (so tokens are attributable per agent).
- **Metrics** — `gen_ai.client.token.usage` and `gen_ai.client.operation.duration`
  histograms (OTel GenAI semconv), plus `crewai.crew.executions`,
  `crewai.task.executions`, `crewai.tool.executions`, and `crewai.errors` counters.
- **Logs** — OTel LogRecords on lifecycle + failures, trace-correlated.

---

## 3. Instrument the crew (two lines)

```bash
pip install -r observability/requirements-observability.txt
```

At the very top of your entrypoint (`main.py` / FastAPI `server.py`), **before**
building the crew:

```python
from observability.instrumentation import init_otel, instrument_crewai

init_otel(service_name="crewai-bmad-crew")   # OTel SDK -> OTLP collector (reads OTEL_* env)
instrument_crewai()                          # CrewAI event bus -> OTel signals
```

See `observability/example_instrumented_crew.py` for a complete runnable example.

### Alternative: OpenLIT (zero-code auto-instrumentation)

If you prefer not to run the native listener, `observability/instrument_openlit.py`
wires [OpenLIT](https://github.com/openlit/openlit) instead — a one-liner that
auto-instruments CrewAI + the LiteLLM/Ollama call path and also emits `gen_ai.*`:

```python
from observability.instrument_openlit import init_observability
init_observability(service_name="crewai-bmad-crew")   # before crew.kickoff(...)
```

Enable it by uncommenting `openlit` in `requirements-observability.txt`. Trade-off:
simpler, but pulls a heavier dependency and its exact span/metric shape depends on
the OpenLIT version — **re-validate on your CrewAI version** before relying on it
(the collector `transform` and the dashboards assume the attribute names in §6,
which the native listener guarantees). The two paths are mutually exclusive — pick
one.

Environment:

```bash
export CREWAI_DISABLE_TELEMETRY=true                        # silence anon analytics
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
export OTEL_EXPORTER_OTLP_PROTOCOL=grpc                     # or http/protobuf
export OTEL_SERVICE_NAME=crewai-bmad-crew
export OTEL_RESOURCE_ATTRIBUTES=deployment.environment=demo
```

> **Note on nesting.** CrewAI runs the sequential process across worker threads,
> so Python `contextvars` do not propagate a parent span from the crew thread to
> the agent/LLM threads. The listener therefore parents spans **explicitly** by
> tracking the active crew/task/agent. This yields a correct tree for the
> sequential process; for hierarchical/parallel crews the "current agent" pointer
> is best-effort.

---

## 4. Deploy the collector

The collector holds the Dynatrace Api-Token so the app never does.

### Local / Docker

```bash
docker run --rm -p 4317:4317 -p 4318:4318 \
  -e DT_ENDPOINT=https://<your-tenant>.live.dynatrace.com \
  -e DT_API_TOKEN=dt0c01.XXXX \
  -v $(pwd)/observability/collector/otel-collector-config.yaml:/conf/collector.yaml \
  otel/opentelemetry-collector-contrib:0.154.0 --config=/conf/collector.yaml
```

### Kubernetes

```bash
kubectl create ns crewai
kubectl -n crewai create secret generic dynatrace \
  --from-literal=dynatrace_oltp_url=https://<your-tenant>.live.dynatrace.com \
  --from-literal=dt_api_token=dt0c01.XXXX
kubectl apply -f observability/collector/k8s/otel-collector.yaml
```

Then point the crew Deployment at `http://otel-collector.crewai:4317`.

**Pipeline rules baked in:** `memory_limiter` is the **first** processor and
`batch` is the **last** in every pipeline; `k8sattributes` appears **only** in the
Kubernetes manifest (never in the local config). The collector `transform` also
maps OpenInference `llm.token_count.*` → `gen_ai.*` as a fallback, so the
dashboards work even if you instrument with OpenInference instead of this listener.

The DT Api-Token needs `openTelemetryTrace.ingest`, `metrics.ingest`, and
`logs.ingest` scopes.

---

## 5. Read the dashboards

Two dashboards ship as JSON in `observability/dashboards/` (24-column grid,
Dynatrace document format). Deploy them with the dashboard skill's script:

```bash
dtctl dashboard create -f observability/dashboards/crewai-agentic-efficiency-dashboard.json
dtctl dashboard create -f observability/dashboards/crewai-health-dashboard.json
```

### CrewAI BMAD Crew — Health
Is the crew *up and succeeding*? Kubernetes workload CPU/memory/network, service
request throughput / failures / response time, agent-run success and failure
counts, run-latency p50/p90, task-execution throughput, and live log feed.

### CrewAI BMAD Crew — Agentic Efficiency
Is the crew *working well and economically*? **Total tokens by agent** and by
model, token usage over time, input-vs-output split, **avg tokens per run**, LLM
and tool latency (avg + p90), tool calls by tool and by agent, tool error rate,
finish reasons, per-agent efficiency (LLM vs tool calls), and a trace-correlated
GenAI event feed.

All span tiles filter on `gen_ai.system == "crewai"`, so they work whether the
crew runs locally or in Kubernetes. Infra/log tiles filter on the
`observable-crewai` cluster / `crewai` namespace.

> The DQL in these dashboards is modeled on the kagent episode's dashboards, which
> were validated live against this same Dynatrace tenant, with attribute names
> adapted to CrewAI (`chat` op, `gen_ai.agent.name` grouping, `span.status_code`
> for tool errors). **Re-validate against live data once the crew is deployed**
>.

---

## 6. GenAI semantic-convention reference

| Signal | Name | Key attributes |
|---|---|---|
| Span (crew) | `crew <name>` | `gen_ai.system=crewai`, `gen_ai.operation.name=invoke_agent`, `crewai.crew.name` |
| Span (task) | `task <name>` | `gen_ai.operation.name=invoke_agent`, `crewai.task.name`, `crewai.task.id` |
| Span (agent) | `agent <role>` | `gen_ai.operation.name=invoke_agent`, `gen_ai.agent.name` |
| Span (LLM) | `chat <model>` | `gen_ai.operation.name=chat`, `gen_ai.request.model`, `gen_ai.usage.{input,output,total}_tokens`, `gen_ai.response.finish_reasons`, `gen_ai.agent.name` |
| Span (tool) | `tool <name>` | `gen_ai.operation.name=execute_tool`, `gen_ai.tool.name` |
| Metric | `gen_ai.client.token.usage` (histogram) | `gen_ai.token.type=input\|output`, `gen_ai.request.model`, `gen_ai.agent.name` |
| Metric | `gen_ai.client.operation.duration` (histogram, s) | `gen_ai.request.model`, `gen_ai.agent.name` |
| Metric | `crewai.{crew,task,tool}.executions`, `crewai.errors` (counters) | `status`, `signal`, `tool.name` |

---

## 7. Upstream contribution (tracing gap)

Because CrewAI ships no first-party OTel/GenAI exporter, this listener is the seed
for an upstream contribution:

- **Gap A (fast):** `Arize-ai/openinference` — make the CrewAI instrumentor emit
  LLM + tool spans by default and drop the dead `litellm` hook.
- **Gap B (strategic):** `crewAIInc/crewAI` — a first-party, opt-in OTel-GenAI
  exporter over the event bus (the event payloads are already `gen_ai`-shaped).

`observability/instrumentation/crewai_otel.py` is a working, live-validated
reference for Gap B.
