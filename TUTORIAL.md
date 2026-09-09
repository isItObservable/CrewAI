# TUTORIAL — Rebuild the BMAD crew in CrewAI, then observe it

A follow-along, host-runnable tutorial. Every step is a command you can paste. Baseline:
**CrewAI 1.15.1**, Python 3.10–3.12, local **qwen3.6** via Ollama at
`http://<your-ollama-host>:11434`. Substitute your own Ollama host/model where noted.

> CrewAI moves fast. This tutorial is pinned to **1.15.1**. If you bump the version,
> re-verify the decorator import path (`crewai.project`) and the LLM/Ollama env names.

---

## 0. Prerequisites

```bash
python3 --version           # 3.10 – 3.12
pip install uv              # or: curl -LsSf https://astral.sh/uv/install.sh | sh
# Confirm the model is reachable and pulled on your Ollama host:
curl http://<your-ollama-host>:11434/api/tags | grep qwen3.6
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
# .env already points MODEL=ollama/qwen3.6 and OLLAMA_BASE_URL=http://<your-ollama-host>:11434
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

CrewAI is **trace-rich but token-blind by default**. We use
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
the dashboards live in [`observability/README.md`](./observability/README.md).

---

## 6. Containerize

You don't need docker on your laptop to publish the image — the repo builds and
pushes it **for you** on GitHub's runners.

### 6.1 CI build (recommended — no local docker, no PAT)

`.github/workflows/build-image.yml` builds the image and pushes it to GHCR using
the built-in `GITHUB_TOKEN`, which carries `packages: write` **scoped to this repo
only** — no personal access token required. It runs on:

- every push to `main` / `master`,
- any `v*` tag (semver-tagged release images), and
- a manual **workflow_dispatch** from the Actions tab.

So the workflow is: **push (or open the Actions tab → Run workflow) → GitHub builds
the image → it lands at `ghcr.io/isitobservable/bmad-crew:latest` and `:1.0.0`.**
The Dockerfile lives at the repo root and `COPY`s from `bmad-crew/`, so the workflow
sets the build context to the repo root (`context: .`) and `platforms: linux/amd64`
(the Kubernetes workers are amd64; the Mac Studio only hosts Ollama).

> **First publish is private.** GHCR packages default to *private*. After the first
> green run, a package admin sets the `bmad-crew` package **Public** (Package →
> Settings → Change visibility) so the cluster can pull it without an
> `imagePullSecret`. Do this once.

Watch the run under the repo's **Actions** tab; the published image shows up under
the org's **Packages**.

### 6.2 Local build (offline fallback)

If you're offline or want to iterate on the image locally, build it yourself from
the **repo root** (the Dockerfile expects the root as build context):

```bash
cd ..                                        # back to CrewAI/
docker build -t ghcr.io/isitobservable/bmad-crew:1.0.0 .
# Smoke-test the service locally:
docker run --rm -p 8000:8000 \
  -e OLLAMA_BASE_URL=http://<your-ollama-host>:11434 \
  ghcr.io/isitobservable/bmad-crew:1.0.0
curl localhost:8000/healthz
```

The image serves the **kickoff API** (`server.py`): `POST /kickoff` runs the crew
synchronously; `GET /healthz` is the probe target.

```bash
docker push ghcr.io/isitobservable/bmad-crew:1.0.0    # needs `packages:write` on the org
```

---

## 7. Provision a Kubernetes cluster

Steps 8–9 need a cluster you can `kubectl apply` to. If you already have one,
skip ahead. Otherwise pick one of these two paths — both are documented in full,
with every environment-specific value (node names, IPs, project id) as a
**variable you supply**, in **[`docs/cluster-setup.md`](./docs/cluster-setup.md)**.

### Option A — Cluster API on Proxmox (what we use)

We provision our tutorial clusters declaratively with [Cluster
API](https://cluster-api.sigs.k8s.io/) on a Proxmox homelab. Nothing about our
network is baked in: you describe **your** Proxmox node, template, and free IP
ranges in a `values.env` file, render the manifests, and apply them.

```bash
# See docs/cluster-setup.md for the full walkthrough. In short:
#   1. copy the example config and set YOUR values (no defaults leak through):
#        cp -r clusters/example-cluster clusters/my-cluster
#        $EDITOR clusters/my-cluster/values.env   # source_node, template_id, vip, IP pools
#   2. render + apply against your CAPI management cluster:
#        render.sh my-cluster && kubectl apply -k clusters/my-cluster/
```

> The reusable CAPI manifests + render tooling live in the companion
> [proxmox-clusters](https://github.com/henrikrexed/proxmox-clusters) repo.
> `docs/cluster-setup.md` explains exactly which variables to set and how to
> discover free IPs on your LAN.

### Option B — Google Kubernetes Engine (managed, no homelab needed)

Don't have Proxmox? Stand up a managed cluster in one command:

```bash
gcloud container clusters create-auto bmad-crew \
  --project <your-gcp-project> --region <your-region>
gcloud container clusters get-credentials bmad-crew --region <your-region>
kubectl get nodes
```

On GKE, a `Service` of `type: LoadBalancer` gets a cloud IP automatically — so
you can skip any MetalLB add-on. Full `gcloud`/Terraform steps and the (few)
manifest differences are in [`docs/cluster-setup.md`](./docs/cluster-setup.md).

> **Ollama reachability (both paths).** The crew calls your Ollama host over the
> network. Make sure pods in the cluster can reach `OLLAMA_BASE_URL`
> (`k8s/configmap.yaml`) — a homelab cluster reaches a LAN Ollama directly; from
> GKE you'll need the Ollama host reachable from the cluster (VPN, public
> endpoint, or run Ollama in-cluster).

---

## 8. Deploy to Kubernetes

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
1. **Egress to Ollama.** Pods must reach `http://<your-ollama-host>:11434`. Confirm routing from
   the cluster. If the model is unreachable, `/kickoff`
   will hang on the first LLM call.
2. **Memory persistence.** CrewAI memory (LanceDB) is on local disk and ephemeral in a
   pod — the `PVC` mounts it at `/app/.crewai`. Only relevant if you enable `memory=True`.

---

## 9. Run and verify

```bash
kubectl -n bmad-crew port-forward svc/bmad-crew 8080:80 &
curl -s localhost:8080/kickoff \
  -H 'content-type: application/json' \
  -d '{"project":"Status page","brief":"A public SLO status page..."}' | jq -r .result
```

Then confirm telemetry landed:

- **Traces** — a `crew.kickoff → <agent>.execute → chat qwen3.6` waterfall per run.
- **Metrics/tokens** — `gen_ai.usage.input_tokens` / `output_tokens` per LLM call,
  aggregated into tokens/run and tokens-per-agent.
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
