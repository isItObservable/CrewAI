# TUTORIAL — Rebuild the BMAD crew in CrewAI, then observe it

A follow-along, host-runnable tutorial. Every step is a command you can paste. Baseline:
**CrewAI 1.15.1**, Python 3.10–3.12, local **qwen3.6** via Ollama at
`http://<your-ollama-host>:11434`. Substitute your own Ollama host/model where noted.

> CrewAI moves fast. This tutorial is pinned to **1.15.1**. If you bump the version,
> re-verify the decorator import path (`crewai.project`) and the LLM/Ollama env names.

---

## 0. Prerequisites

### 0.1 Set your environment variables

Set these **once** in your terminal session. Every `kubectl apply`, `envsubst`, and
`curl` command in this tutorial uses them — no hardcoded IPs or tokens anywhere.

```bash
# ── Ollama ────────────────────────────────────────────────────────────────────
# IP or hostname of your Ollama host (no protocol, no port)
export OLLAMA_HOST=<your-ollama-host>       # e.g. 192.168.1.100 or ollama.local
export OLLAMA_MODEL=qwen3.6                 # model tag you have pulled on that host

# ── Dynatrace ─────────────────────────────────────────────────────────────────
export DT_TENANT_URL=https://<your-tenant>.live.dynatrace.com
export DT_API_TOKEN=<operator-token>        # scopes: see README § Dynatrace tokens
export DT_INGEST_TOKEN=<data-ingest-token>  # scopes: metrics.ingest + logs.ingest
                                            #         + openTelemetryTrace.ingest

# ── GitHub (optional — dev agent GitHub MCP) ──────────────────────────────────
# Leave blank to run without GitHub integration (dev agent writes to ./output/).
export GITHUB_PAT=<your-fine-grained-PAT>  # fine-grained PAT: Contents + PRs read/write
export GITHUB_REPO=owner/repo-name         # target repo slug (e.g. acme/my-app)

# ── OTel Collector (in-cluster) ───────────────────────────────────────────────
# If you deploy the in-cluster Collector (Step 5), use its cluster-internal DNS.
# Override if your Collector lives on a different host/port.
export OTEL_COLLECTOR_ENDPOINT=http://otel-gateway-collector.observability.svc.cluster.local:4318
```

> **Tip:** Save these exports to a file (e.g. `vars.env`) and `source vars.env` at the
> start of each session. Add `vars.env` to your `.gitignore` — never commit real tokens.

### 0.2 Verify tooling and Ollama

```bash
python3 --version           # 3.10 – 3.12
pip install uv              # or: curl -LsSf https://astral.sh/uv/install.sh | sh

# Confirm Ollama is reachable and the model is pulled:
curl http://${OLLAMA_HOST}:11434/api/tags | grep ${OLLAMA_MODEL}
# If the model is missing, pull it on the Ollama host:  ollama pull qwen3.6
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
# Edit .env and set your Ollama host (you set $OLLAMA_HOST in Step 0):
sed -i.bak "s|http://<your-ollama-host>:11434|http://${OLLAMA_HOST}:11434|" .env
cat .env | grep OLLAMA_BASE_URL   # verify the substitution
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

> **One crew, one process — read this before you scale it.** `kickoff()` runs all
> eight agents in a single Python process: task `context` hand-offs are in-memory,
> so the natural unit of deployment is ONE container/pod (that's what `k8s/` ships,
> behind one Service). Per-agent containers are **not** a native CrewAI pattern.
> If you outgrow it, the escape hatch is to split the crew into per-agent services —
> each a single-agent crew behind its own Deployment — and hand work off over HTTP.
> You gain independent scaling and failure domains; you pay with network hops, more
> moving parts, and losing the free in-process context. Measure first (the
> dashboards in the observability chapter) — for a crew this size, one pod is the
> honest architecture.

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

```bash
# HITL mode (default) — agents pause for human validation at 3 checkpoints:
#   1. After analyst: validate requirements (BLK-N blockers surfaced one at a time)
#   2. After architect: validate tech stack
#   3. After QA: final SHIP / NO-SHIP sign-off
# Decisions written to output/decisions.memlog.md
uv run bmad-crew

# Fully automated (no pauses — for CI / scripted runs):
uv run bmad-crew --no-hitl

# With GitHub MCP (dev agent creates branch, commits files, opens PR):
uv run bmad-crew --github-repo owner/myrepo --no-hitl
# Requires GITHUB_PERSONAL_ACCESS_TOKEN and GITHUB_MCP_MODE in env.
# See docs/github-mcp-demo.md for the full setup.
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

### 5.1 Choose your instrumentation path

Three drop-in options emit to the same Collector → Dynatrace pipeline. Switch by setting
`CREWAI_INSTRUMENTATION` (no rebuild — the image ships all three):

| Value | Library | Notes |
|-------|---------|-------|
| `openlit` (default) | openlit | gen_ai.* spans + GenAI metrics out of the box |
| `openllmetry` | traceloop-sdk | Traceloop ecosystem; token attr names differ slightly |
| `native` | opentelemetry-sdk only | Full control; no third-party auto-instrumentation |

```bash
export CREWAI_INSTRUMENTATION=native   # switch path; restart crew
uv run bmad-crew
# console: [bmad-crew] Instrumentation path: Native event-bus (crewai_otel)
```

---

## 6. Containerize

You don't need docker on your laptop to publish the image — the repo builds and
pushes it **for you** on GitHub's runners.

### 6.1 CI build (recommended — no local docker, no PAT)

`.github/workflows/build-image.yml` builds **two images** and pushes them to GHCR using
the built-in `GITHUB_TOKEN`, which carries `packages: write` **scoped to this repo
only** — no personal access token required. The workflow has two jobs:

- **`build-backend`** — builds `ghcr.io/isitobservable/bmad-crew` from the repo root
  `Dockerfile`. Only runs when backend files change.
- **`build-ui`** — builds `ghcr.io/isitobservable/bmad-crew-ui` from `ui/Dockerfile`.
  Only runs when UI files change.

Both jobs trigger on:

- every push to `main` / `master`,
- any `v*` tag (semver-tagged release images), and
- a manual **workflow_dispatch** from the Actions tab.

Path filtering means a pure UI change will not rebuild the backend image and vice versa.

> **First publish is private.** GHCR packages default to *private*. After each job's
> first green run, set the corresponding package **Public** (Package → Settings →
> Change visibility) so the cluster can pull it without an `imagePullSecret`.
> Do this once for each package (`bmad-crew` and `bmad-crew-ui`).

Watch the run under the repo's **Actions** tab; both published images show up under
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

The ConfigMap files contain `${OLLAMA_HOST}` placeholders. Use `envsubst` to substitute
your variables before applying — no file editing required.

> **Prerequisite:** `envsubst` ships with the `gettext` package.
> macOS: `brew install gettext`. Ubuntu/Debian: `apt-get install gettext-base`.

```bash
# 1. Namespace
kubectl apply -f k8s/namespace.yaml

# 2. ConfigMap — substitute $OLLAMA_HOST (and any other vars) at apply time
envsubst < k8s/configmap.yaml | kubectl apply -f -

# 3. Secret — inject your GitHub PAT directly (never commit the real value)
kubectl create secret generic bmad-crew-secrets \
  -n bmad-crew \
  --from-literal=GITHUB_PERSONAL_ACCESS_TOKEN="${GITHUB_PAT:-}" \
  --from-literal=OPENAI_API_KEY="" \
  --dry-run=client -o yaml | kubectl apply -f -

# 4. Storage, Deployment, Service, HPA
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/hpa.yaml

# 5. Wait for rollout
kubectl -n bmad-crew rollout status deploy/bmad-crew
```

**Two things that bite in k8s:**
1. **Egress to Ollama.** Pods must reach `http://${OLLAMA_HOST}:11434`. Confirm routing from
   the cluster before you apply — if the model is unreachable, `/kickoff` hangs on the
   first LLM call.
2. **Memory persistence.** CrewAI memory (LanceDB) is on local disk and ephemeral in a
   pod — the `PVC` mounts it at `/app/.crewai`. Only relevant if you enable `memory=True`.

---

## 8.5 Deploy the CopilotKit UI

The browser-based demo frontend. `ui/k8s/configmap.yaml` also contains `${OLLAMA_HOST}` —
use `envsubst` the same way:

```bash
# ConfigMap (substitutes $OLLAMA_HOST for the CopilotKit Ollama adapter)
envsubst < ui/k8s/configmap.yaml | kubectl apply -f -

# Deployment and Service
kubectl apply -f ui/k8s/deployment.yaml
kubectl apply -f ui/k8s/service.yaml
kubectl -n bmad-crew rollout status deploy/bmad-crew-ui
```

**Traffic flow:** Browser → `/api/crew/*` → Next.js rewrite → FastAPI pod (ClusterIP,
internal). The FastAPI backend is never directly exposed to the internet — all external
traffic enters through the UI's LoadBalancer service.

---

## 9. Run and verify

### 9.1 Open the CopilotKit UI

Get the LoadBalancer IP assigned to the UI service and open it in your browser:

```bash
# Cloud cluster (GKE / EKS / AKS / MetalLB) — wait for EXTERNAL-IP to appear:
kubectl get svc bmad-crew-ui -n bmad-crew
# NAME            TYPE           CLUSTER-IP     EXTERNAL-IP      PORT(S)        AGE
# bmad-crew-ui    LoadBalancer   10.96.x.x      <EXTERNAL-IP>    80:31234/TCP   2m

# Once EXTERNAL-IP is populated, grab it and open the browser:
BMAD_UI_IP=$(kubectl get svc bmad-crew-ui -n bmad-crew \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "CopilotKit UI → http://${BMAD_UI_IP}"
open "http://${BMAD_UI_IP}"        # macOS — opens your default browser
# xdg-open "http://${BMAD_UI_IP}" # Linux alternative
```

> **IP still `<pending>`?** The cluster's LoadBalancer controller hasn't assigned an address yet.
> On a bare-metal cluster (no cloud LB) you need MetalLB or similar. As a quick alternative,
> use port-forward (see below).

```bash
# Local cluster (kind / k3d / minikube) — use port-forward instead of a LoadBalancer:
kubectl port-forward svc/bmad-crew-ui -n bmad-crew 3000:80
# Then open http://localhost:3000 in your browser.
```

Type a project brief in the chat sidebar, watch the **Agent Timeline** panel light up
agent by agent (click any completed agent card to expand its output), and read the QA
report in the output panel once the pipeline finishes.

### 9.2 Headless / curl (Option B — no browser)

```bash
# Option B — curl (headless)
kubectl -n bmad-crew port-forward svc/bmad-crew 8080:80 &
curl -s localhost:8080/kickoff/async \
  -H 'content-type: application/json' \
  -d '{"project":"Status page","brief":"A public SLO status page..."}' | jq .
# returns {"run_id": "..."} — poll /run/{run_id}/result or stream /stream/{run_id}
```

`/kickoff` (sync) still works for quick tests; `/kickoff/async` + `/stream/{run_id}` is
what the UI uses for live streaming.

Then confirm telemetry landed:

- **Traces** — per run: `invoke_workflow BmadCrew` at the root, one
  `invoke_agent <role>` span per agent (plus `create_agent` spans from crew
  build-time and CrewAI-internal `invoke_agent <step>` spans beneath each), and
  one `chat qwen3.6` span per LLM call. These are the exact span names from the
  live deployment (OpenLIT 1.42.1).
- **Metrics/tokens** — `gen_ai.usage.input_tokens` / `output_tokens` on every
  `chat` span, and a run total on the `invoke_workflow` span (measured full run:
  130,344 in / 239,104 out across 8 LLM calls).
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
| UI pod CrashLoopBackoff | `BMAD_CREW_URL` wrong or Ollama unreachable from ui pod — check configmap and Ollama egress |
| Chat sidebar shows no response | `COPILOTKIT_ADAPTER=ollama` but `OLLAMA_BASE_URL` unreachable from ui pod |
| Double crew run on kickoff | `kickoff_crew` must be client-side only (`useCopilotAction` in `page.tsx`) — `route.ts` must have empty actions array |
| HITL never pauses | `BMAD_HUMAN_IN_LOOP=false` in ConfigMap — set to `true` for interactive mode |

---

## Where to go next

- Enable **memory** with a local Ollama embedder for cross-run recall (research §3.4).
- Add **custom tools** (`@tool` / `BaseTool`) so the dev agent can read the repo or run tests.
- Wrap the crew in a **Flow** (`@start`/`@listen`/`@router`) for retries and branching.
- Contrast **sequential vs hierarchical** delegation on camera.
