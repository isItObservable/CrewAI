# Observability for the CrewAI BMAD Crew

This section shows how to make the CrewAI BMAD crew **fully observable** with
OpenTelemetry — traces, metrics, and logs — and read the result in Dynatrace.
It is the observability track of the CrewAI episode; the telemetry
gap analysis behind these choices is in the research doc.

> **TL;DR** — CrewAI 1.15 emits rich internal *events* but, out of the box, **no
> OTLP metrics** and only two coarse spans, tagged with the wrong semantic
> convention for Dynatrace. We close that gap with **any of three vendor-neutral,
> no-crew-code-change instrumentation paths** — **OpenLIT** (the shipped easy
> button), **OpenLLMetry / Traceloop**, or a **native event-bus listener** — each
> emitting standards-compliant `gen_ai.*` spans + metrics + logs, then routed
> through one OTel Collector to Dynatrace (<your-tenant>). This mirrors the
> episode's Chapter 6.

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

## 3. Instrument the crew — pick one path

```bash
pip install -r observability/requirements-observability.txt
```

The episode shows **three** ways to instrument CrewAI, all open-source, all with
**no changes to the crew's own code**, and all landing on the **same OTLP →
Collector → Dynatrace** pipeline. Pick one — they are mutually exclusive.

### Option A — OpenLIT  *(shipped default — the "easy button")*

What the tutorial ships (the app wires this in `bmad_crew/observability.py`).
[OpenLIT](https://github.com/openlit/openlit) is a one-liner that auto-instruments
CrewAI + the LiteLLM/Ollama call path and emits `gen_ai.*` **spans *and* GenAI
metrics** with `gen_ai.system == "crewai"` — so it drops straight onto the shipped
dashboards with no remap.

```python
from observability.instrument_openlit import init_observability
init_observability(service_name="crewai-bmad-crew")   # before crew.kickoff(...)
```

Enable by uncommenting `openlit` in `requirements-observability.txt`.

### Option B — OpenLLMetry / Traceloop  *(one line, OTLP-native)*

[OpenLLMetry](https://github.com/traceloop/openllmetry) is Traceloop's one-line
auto-instrumentation — a great pick if you already live in that ecosystem.

```python
from observability.instrument_openllmetry import init_observability
init_observability(service_name="crewai-bmad-crew")   # before crew.kickoff(...)
```

Enable by uncommenting `traceloop-sdk` in `requirements-observability.txt`.

> **Attribute-parity note (the episode's "sanity-check the names" beat).**
> OpenLLMetry is OTel-GenAI-aligned but does **not** emit the exact same shape as
> Option A / C: token usage is `gen_ai.usage.prompt_tokens` / `completion_tokens`
> (the dashboards already coalesce these); framework spans carry
> `traceloop.span.kind` (`workflow|task|agent|tool`) + `traceloop.entity.name`
> instead of `gen_ai.operation.name` / `gen_ai.agent.name` / `gen_ai.tool.name`;
> and `gen_ai.system` on model-call spans is the **LLM vendor** (e.g. `ollama`),
> not `crewai`. The Collector `transform` (§4) bridges the token, agent, and tool
> attributes automatically; a single **opt-in** (commented) transform statement
> also re-stamps `gen_ai.system == "crewai"` so you can reuse the dashboards
> verbatim. **Re-validate the exact names against your pinned Traceloop version.**

### Option C — Native event-bus listener  *(full control, reference build)*

The `observability/instrumentation/` listener subscribes to CrewAI's native event
bus and emits `gen_ai.*` itself — the most control, and the reference for the
upstream contribution (§7). Live-validated on CrewAI 1.15.1.

```python
from observability.instrumentation import init_otel, instrument_crewai

init_otel(service_name="crewai-bmad-crew")   # OTel SDK -> OTLP collector (reads OTEL_* env)
instrument_crewai()                          # CrewAI event bus -> OTel signals
```

See `observability/example_instrumented_crew.py` for a complete runnable example.

### Attribute shape across the three paths

| Signal | OpenLIT (A) | OpenLLMetry (B) | Native listener (C) |
|---|---|---|---|
| `gen_ai.system` | `crewai` | LLM vendor (e.g. `ollama`) → opt-in remap to `crewai` | `crewai` |
| Input / output tokens | `gen_ai.usage.input_tokens` / `output_tokens` | `gen_ai.usage.prompt_tokens` / `completion_tokens` → bridged | `gen_ai.usage.input_tokens` / `output_tokens` |
| Agent grouping | `gen_ai.agent.name` | `traceloop.entity.name` (kind=`agent`) → bridged | `gen_ai.agent.name` |
| Tool span | `gen_ai.operation.name=execute_tool`, `gen_ai.tool.name` | `traceloop.span.kind=tool`, `traceloop.entity.name` → bridged | `gen_ai.operation.name=execute_tool`, `gen_ai.tool.name` |
| GenAI metrics | ✅ native | ✅ native | ✅ emitted by the listener |
| Dashboards work as-shipped | ✅ | ⚠️ enable the opt-in `gen_ai.system` remap | ✅ |

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
`observable-crewai` cluster / `crewai` namespace. Token tiles coalesce both the
`input/output` and `prompt/completion` token attributes, so **OpenLIT (A)**,
**OpenLLMetry (B)** and the **native listener (C)** all light them up — for the
OpenLLMetry path, also enable the opt-in `gen_ai.system` remap in the Collector
transform (§3 parity note) so its LLM spans pass the `crewai` filter.

> The DQL in these dashboards is modeled on the kagent episode's dashboards, which
> were validated live against this same Dynatrace tenant, with attribute names
> adapted to CrewAI (`chat` op, `gen_ai.agent.name` grouping, `span.status_code`
> for tool errors). **Span names and attributes were re-validated against live
> data on 2026-09-09** (k8squad-test deploy, OpenLIT 1.42.1).

---

## 6. GenAI semantic-convention reference

Span rows verified live 2026-09-09 (OpenLIT 1.42.1, `otel.scope.name=openlit.instrumentation.crewai`); metric rows are OpenLIT-documented.

| Signal | Name | Key attributes |
|---|---|---|
| Span (workflow) | `invoke_workflow <name>` | `gen_ai.operation.name=invoke_workflow`, `gen_ai.provider.name=crewai`, `gen_ai.workflow.name`, `gen_ai.execution.mode`, `gen_ai.crewai.crew.task_count`, run-total `gen_ai.usage.{input,output}_tokens` |
| Span (agent build) | `create_agent <role>` | `gen_ai.operation.name=create_agent`, `gen_ai.agent.{name,id,description}` |
| Span (agent run) | `invoke_agent <role>` | `gen_ai.operation.name=invoke_agent`, `gen_ai.agent.name`, `gen_ai.agent.id`, `gen_ai.input.messages` / `gen_ai.output.messages` |
| Span (LLM) | `chat <model>` | `gen_ai.operation.name=chat`, `gen_ai.request.model`, `gen_ai.usage.{input,output}_tokens`, `gen_ai.client.token.usage` (total), `gen_ai.response.finish_reasons`, `gen_ai.server.time_to_first_token`, `gen_ai.content.reasoning` |
| Span (tool) | `tool <name>` | appears only when tools are enabled — `gen_ai.operation.name=execute_tool`, `gen_ai.tool.name` (the tool-free baseline emits none) |
| Metric | `gen_ai.client.token.usage` (histogram) | `gen_ai.token.type=input\|output`, `gen_ai.request.model`, `gen_ai.agent.name` |
| Metric | `gen_ai.client.operation.duration` (histogram, s) | `gen_ai.request.model`, `gen_ai.agent.name` |
| Metric | `crewai.{crew,task,tool}.executions`, `crewai.errors` (counters) | `status`, `signal`, `tool.name` |

### Tool spans — MCP servers and custom skills

Chapter 3 gives the BMAD agents **tools**: custom skills (a `crewai.tools.BaseTool`
subclass) and whole **MCP servers** plugged in via `crewai_tools.MCPServerAdapter`.
Both kinds surface identically in the trace — one **`tool <name>`** span per call,
child of the agent that invoked it, carrying `gen_ai.operation.name=execute_tool`
and `gen_ai.tool.name=<tool>`. `<name>` is the tool's registered name
(`read_repo_file`, `list_repo_dir`, or the MCP-exposed tool name) — the same string
the app's `bmad_crew/tools.py` sets, so **span naming is aligned end-to-end** with
the tools built on the build/deploy side. On the OpenLLMetry path these arrive as
`traceloop.span.kind=tool` / `traceloop.entity.name` and are bridged to the
canonical shape by the Collector (§3 parity note, §4 transform). The **Agentic
Efficiency** dashboard reads these for *tool calls by tool*, *by agent*, and *tool
error rate*.

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
