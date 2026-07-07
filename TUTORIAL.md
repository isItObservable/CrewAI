# TUTORIAL — Rebuild the BMAD crew in CrewAI, then observe it

A follow-along, host-runnable tutorial. Every step is a command you can paste. Baseline:
**CrewAI 1.15.1**, Python 3.10–3.12, local **qwen3.6** via Ollama at
`http://10.0.0.185:11434`. Substitute your own Ollama host/model where noted.

> CrewAI moves fast. This tutorial is pinned to **1.15.1**. If you bump the version,
> re-verify the decorator import path (`crewai.project`) and the LLM/Ollama env names.

---

## 0. Prerequisites

```bash
python3 --version           # 3.10 – 3.12
pip install uv              # or: curl -LsSf https://astral.sh/uv/install.sh | sh
# Confirm the model is reachable and pulled on your Ollama host:
curl http://10.0.0.185:11434/api/tags | grep qwen3.6
# (If missing:  ollama pull qwen3.6  on the Ollama host.)
```

---

## 1. Install CrewAI

```bash
git clone https://github.com/isItObservable/CrewAI.git
cd CrewAI/bmad-crew
uv venv && source .venv/bin/activate
uv pip install -e .          # installs crewai==1.15.1, crewai-tools, fastapi, openlit
crewai version               # expect 1.15.1
```

> Prefer the scaffold flow to see how CrewAI generates a project? `crewai create crew demo`
> produces the same `config/agents.yaml` + `config/tasks.yaml` + `crew.py` shape this repo
> uses. We ship a ready-made BMAD crew so you can go straight to running it.

---

## 2. Configure the model (local qwen, no API key)

```bash
cp .env.example .env
# .env already points MODEL=ollama/qwen3.6 and OLLAMA_BASE_URL=http://10.0.0.185:11434
```

The crew builds one shared `LLM` from these env vars (`crew.py: build_llm()`), so every
agent talks to local qwen. **No OpenAI/Anthropic key is needed** — that's the differentiator.

---

## 3. Understand the crew (what you're running)

Eight BMAD personas, each a CrewAI **Agent** (`config/agents.yaml`), and eight
hand-offs, each a **Task** (`config/tasks.yaml`), run as a **sequential** process:

```
analyst → pm → ux → po → architect → sm → dev → qa
```

Each task's `context` names the upstream task(s) whose output feeds it, so the hand-offs
are explicit in both the code and (later) the trace. The final QA task writes
`output/qa_report.md`.

Open `config/agents.yaml` to see the personas, and `crew.py` to see how `@agent` /
`@task` / `@crew` wire them with `Process.sequential`.

---

## 4. Run the crew locally

Zero-argument run uses a built-in sample brief (a Slack stand-up bot):

```bash
uv run bmad-crew
```

Or drive it with your own brief:

```bash
uv run bmad-crew \
  --project "Observability status page" \
  --brief "We need a public status page that reflects our SLOs in real time..."
```

Watch the console (`verbose=True`): each agent reasons, then hands its output to the
next. When it finishes, read the full delivery:

```bash
cat output/qa_report.md
```

> **Optional — dynamic delegation (the CrewAI "wow" beat).** Add `--hierarchical` to run
> a BMad-Orchestrator manager that delegates dynamically (`Process.hierarchical`). It's
> heavier on the model's tool-calling and non-deterministic — great for a contrast
> segment, but sequential is the backbone.

---

## 5. Add observability (OpenTelemetry → Dynatrace)

CrewAI is **trace-rich but token-blind by default** (research: ISI-1584). We use
**OpenLIT** to emit `gen_ai.*` spans and GenAI metrics. It's already wired in
`observability.py` and initialised at startup — you just point it at a collector:

```bash
# Run a local OTel Collector (or use your cluster's). Then:
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
uv run bmad-crew
# console prints: [bmad-crew] OpenTelemetry instrumentation: ON
```

Leave `OTEL_EXPORTER_OTLP_ENDPOINT` unset to run without telemetry (no crash).
`OTEL_SDK_DISABLED=true` is the hard off-switch. The Collector → Dynatrace pipeline and
the dashboards are built in **ISI-1586**; see [`observability/README.md`](./observability/README.md).

---

## 6. Containerize

From the **repo root** (the Dockerfile expects the root as build context):

```bash
cd ..                                        # back to CrewAI/
docker build -t ghcr.io/isitobservable/bmad-crew:1.0.0 .
# Smoke-test the service locally:
docker run --rm -p 8000:8000 \
  -e OLLAMA_BASE_URL=http://10.0.0.185:11434 \
  ghcr.io/isitobservable/bmad-crew:1.0.0
curl localhost:8000/healthz
```

The image serves the **kickoff API** (`server.py`): `POST /kickoff` runs the crew
synchronously; `GET /healthz` is the probe target.

```bash
docker push ghcr.io/isitobservable/bmad-crew:1.0.0
```

---

## 7. Deploy to Kubernetes

```bash
# Point OLLAMA_BASE_URL / image / OTLP endpoint to your environment first
# (k8s/configmap.yaml and k8s/deployment.yaml).
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/hpa.yaml
kubectl -n bmad-crew rollout status deploy/bmad-crew
```

**Two things that bite in k8s (from the research):**
1. **Egress to Ollama.** Pods must reach `http://10.0.0.185:11434`. Confirm routing from
   the cluster (owned by ProxOps in ISI-1588). If the model is unreachable, `/kickoff`
   will hang on the first LLM call.
2. **Memory persistence.** CrewAI memory (LanceDB) is on local disk and ephemeral in a
   pod — the `PVC` mounts it at `/app/.crewai`. Only relevant if you enable `memory=True`.

---

## 8. Run and verify

```bash
kubectl -n bmad-crew port-forward svc/bmad-crew 8080:80 &
curl -s localhost:8080/kickoff \
  -H 'content-type: application/json' \
  -d '{"project":"Status page","brief":"A public SLO status page..."}' | jq -r .result
```

Then confirm telemetry landed:

- **Traces** — a `crew.kickoff → <agent>.execute → chat qwen3.6` waterfall per run.
- **Metrics/tokens** — `gen_ai.usage.input_tokens` / `output_tokens` per LLM call,
  aggregated into tokens/run and tokens-per-agent (dashboards in ISI-1586, Dynatrace
  tenant `oat05854`).
- **Logs** — agent/task lifecycle.

If tokens don't appear: OpenLIT isn't initialised (check the startup line in step 5),
the OTLP endpoint is wrong, or the Collector isn't forwarding — walk the pipeline in
`observability/README.md`.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `crewai version` ≠ 1.15.1 | `uv pip install 'crewai==1.15.1'` — the tutorial is pinned |
| Hangs on first agent | Ollama unreachable — check `OLLAMA_BASE_URL` and `curl .../api/tags` |
| `OPENAI_API_KEY` demanded | You enabled `memory=True` without a local embedder — set the Ollama embedder (research §3.4) |
| Tool-calling / delegation flaky | qwen tool-calling can wobble; fall back to sequential (drop `--hierarchical`) |
| No spans in Dynatrace | `OTEL_EXPORTER_OTLP_ENDPOINT` unset/wrong, or Collector not forwarding |
| `import crewai.project` fails | Version drift — verify the decorator import path for your CrewAI version |

---

## Where to go next

- Enable **memory** with a local Ollama embedder for cross-run recall (research §3.4).
- Add **custom tools** (`@tool` / `BaseTool`) so the dev agent can read the repo or run tests.
- Wrap the crew in a **Flow** (`@start`/`@listen`/`@router`) for retries and branching.
- Contrast **sequential vs hierarchical** delegation on camera.
