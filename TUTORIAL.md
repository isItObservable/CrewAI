# TUTORIAL — Rebuild the BMAD crew in CrewAI, then observe it

A follow-along, host-runnable tutorial. Every step is a command you can paste. Baseline:
**CrewAI 1.15.1**, Python 3.10–3.12, local **qwen3.6** via Ollama at
`http://<your-ollama-host>:11434`. Substitute your own Ollama host/model where noted.

> CrewAI moves fast. This tutorial is pinned to **1.15.1** (the tested, deployed
> baseline — the published image and the k8s walkthroughs all run it). Doc links
> point at **v1.15.20** (closest stable docs); if you bump the version, re-verify
> the decorator import path (`crewai.project`) and the LLM/Ollama env names.
>
> **Provenance:** aligned with the v3 storyboard (ISI-4039 restructure + ISI-4088
> native-telemetry fold + ISI-4095 CopilotKit-as-UI, per board asks ISI-4078 /
> ISI-4095, 2026-09-09).

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

> **Scaffold it the right way — Skills first.** CrewAI ships a set of **Skills** for
> your *coding* assistant: one command — `npx skills add crewaiinc/skills` — pulls
> CrewAI's official public registry into whatever coding agent you use (Claude Code,
> Cursor, Codex…), so the project it scaffolds is idiomatic CrewAI from line one.
> This is **build-time** tooling: it primes the assistant that helps you *write* the
> crew — it doesn't run inside it. (OSS guardrail: the Skills registry add is all we
> use — no usage-analytics dashboards, no account linking.)
>
> Prefer the CLI scaffold to see how CrewAI generates a project? `crewai create crew demo`
> produces the same `config/agents.yaml` + `config/tasks.yaml` + `crew.py` shape this repo
> uses. And when your crew grows tools worth sharing, ship them as a package — see
> [§5](#5-give-your-agents-tools-built-ins--mcp--your-own--pypi). We ship a
> ready-made BMAD crew so you can go straight to running it.

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

## 5. Give your agents tools (built-ins → MCP → your own → PyPI)

So far the crew reasons and writes, but agents get a lot more useful when they can
**do things**. CrewAI's tooling story has a clear order of attack — and it starts
with *not building anything at all*:

1. **Reach for the built-in tool library first** — don't build what already ships.
2. Wire a whole **MCP server** when you have one (no glue code).
3. **Write your own** tool only when nothing fits.
4. **Publish it to PyPI** so future-you (and everyone else) can `pip install` it.

### 5.1 Built-in tools first (`crewai-tools`)

One install gets you a library of **40+ ready-made tools** — web search, website
scraping, file/PDF readers, RAG over your own docs, database and cloud connectors:

```bash
uv pip install crewai-tools          # already a dependency of this repo
```

Drop them straight onto an agent — no glue code:

```python
from crewai import Agent
from crewai_tools import SerperDevTool, FileReadTool

analyst = Agent(
    role="Business and Domain Analyst",
    goal="Turn the brief into a crisp problem statement",
    backstory="You are a meticulous analyst who never invents requirements.",
    tools=[SerperDevTool(), FileReadTool()],   # web search + local file reads
    llm=llm,
)
```

`SerperDevTool` wants a `SERPER_API_KEY`; the file/PDF/RAG tools work with no key
at all. Browse the full catalogue in the docs:
<https://docs.crewai.com/v1.15.20/en/tools/overview> — the message is simply:
**check the library before you write a tool.**

### 5.2 MCP servers (a whole toolbox in one line)

Already have an MCP server? CrewAI's `MCPServerAdapter` plugs it in, and every
tool the server exposes becomes available to the agent:

```python
from crewai_tools import MCPServerAdapter

with MCPServerAdapter({"url": "https://api.githubcopilot.com/mcp/",
                       "headers": {"Authorization": f"Bearer {GH_PAT}"}}) as tools:
    developer = Agent(role="Developer", ..., tools=tools, llm=llm)
```

This repo ships a worked example: the optional **GitHub toolset** for the dev agent
(`bmad-crew/GITHUB_TOOLS.md`) — issues, branches, commits, PRs — with every tool
call captured as a `tool <name>` span by the observability layer.

### 5.3 Write your own (two ways)

For the bespoke stuff, subclass `BaseTool` (with `name`, `description`, `_run`)
or decorate a plain function with `@tool`; add an `args_schema` (pydantic) and a
`result_schema` and it's production-grade:

```python
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

class LocateInput(BaseModel):
    target: str = Field(..., description="IP, domain or AS number to locate")

class GeoLocateTool(BaseTool):
    name: str = "geo_locate"
    description: str = "Locate an IP/domain/AS and return country + ISP."
    args_schema: type[BaseModel] = LocateInput

    def _run(self, target: str) -> str:
        ...  # call your geolocation API, return a string
```

Every tool call shows up as its own span in the trace (`tool <name>` — see
`observability/OBSERVABILITY.md` §6), so agents that *act* are agents you can
*observe*.

### 5.4 Don't keep it — ship it to PyPI

A private helper becomes a shared, versioned package in two commands:

```bash
uv build                # builds wheel + sdist from pyproject.toml
uv publish              # → PyPI (use --publish-url testpypi... for a dry run)
pip install crewai-geolocate   # future-you, or anyone, drops it into a crew
```

Name it `crewai-<what-it-does>` and it's discoverable next to the built-ins.
(OSS guardrail: the publish path is PyPI via `uv build` / `uv publish` — that's
the whole story; there is no hosted registry step.)

---

## 6. Add observability (OpenTelemetry → Dynatrace)

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
The Collector → Dynatrace pipeline and the dashboards live in
[`observability/README.md`](./observability/README.md).

> **Myth-buster: CrewAI's *native* telemetry — what it is, and what it is not.**
> CrewAI phones home with **anonymous product analytics**, and it's built on
> OpenTelemetry — so you'd be forgiven for thinking you're "already instrumented".
> You're not:
>
> - It runs on a **private, isolated `TracerProvider`** that is **never registered
>   as the global one** and **never exports to your backend** — no OTLP leaves the
>   process, your collector never sees it, and it never carries your prompts or
>   token counts.
> - It therefore **does not collide** with the OpenLIT instrumentation above, and
>   it **does not replace** the `gen_ai.*` layer we add ourselves — that layer
>   (OpenLIT / OpenLLMetry / the event-bus listener) stays the observability story:
>   it's what makes CrewAI's default **token-blindness** visible.
> - Want it off? The opt-out is **`CREWAI_DISABLE_TELEMETRY=true`** (our
>   `observability.py` sets this by default). Do **not** reach for
>   `OTEL_SDK_DISABLED=true` — that variable is a footgun: it disables *your*
>   OpenLIT/OpenTelemetry pipeline too, i.e. the very telemetry this chapter is
>   here to produce. It is a last-resort kill-switch for the whole OTel SDK, not
>   CrewAI's analytics opt-out.

---

## 7. Containerize

You don't need docker on your laptop to publish the image — the repo builds and
pushes it **for you** on GitHub's runners.

### 7.1 CI build (recommended — no local docker, no PAT)

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

### 7.2 Local build (offline fallback)

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

## 8. Provision a Kubernetes cluster

Steps 9–11 need a cluster you can `kubectl apply` to. If you already have one,
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

## 9. Deploy to Kubernetes

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

## 10. Run and verify

```bash
kubectl -n bmad-crew port-forward svc/bmad-crew 8080:80 &
curl -s localhost:8080/kickoff \
  -H 'content-type: application/json' \
  -d '{"project":"Status page","brief":"A public SLO status page..."}' | jq -r .result
```

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

If tokens don't appear: OpenLIT isn't initialised (check the startup line in step 6),
the OTLP endpoint is wrong, or the Collector isn't forwarding — walk the pipeline in
`observability/README.md`.

---

## 11. Drive the crew from the browser — self-hosted CopilotKit UI

curl is a fine demo, but the storyboard beat is a real **UI**: a chat panel you
type a brief into and watch the crew answer. We use **CopilotKit** — the
open-source UI layer for agent apps — **fully self-hosted**: the React app in
[`frontend/`](./frontend/) talks straight to a small FastAPI
**backend-for-frontend** (`bmad_crew/copilotkit_bff.py`) over the open
**AG-UI protocol** (SSE). No CopilotKit Cloud, no AMP, no hosted runtime — and
no extra LLM key: the crew keeps using your Ollama model.

```
┌───────────────────────┐  AG-UI (HTTP + SSE)  ┌──────────────────────┐   POST /kickoff   ┌─────────────────┐
│  CopilotKit chat UI   │ ◀──────────────────▶ │  FastAPI BFF         │ ────────────────▶ │  BMAD crew      │
│  frontend/ (Vite)     │   HttpAgent          │  copilotkit_bff.py   │   (server.py)     │  8 agents       │
└───────────────────────┘                      └──────────────────────┘                   └─────────────────┘
```

### 11.1 Start the crew service

The BFF is a *front door* — it calls the same `POST /kickoff` API you already
have. Start the crew service (locally or via port-forward to the cluster):

```bash
# local crew service:
cd bmad-crew && uv run uvicorn bmad_crew.server:app --port 8000
# …or the in-cluster one:
kubectl -n bmad-crew port-forward svc/bmad-crew 8000:80 &
```

### 11.2 Start the BFF

```bash
cd bmad-crew
export KICKOFF_URL=http://localhost:8000/kickoff   # where the crew service lives
uv run bmad-crew-bff                                # serves http://0.0.0.0:8100
# smoke-test it without a browser and without calling the crew:
#   BFF_ECHO_MODE=true uv run bmad-crew-bff
```

The BFF streams a standards-compliant AG-UI event stream — `RUN_STARTED` →
status message → (crew runs, SSE keep-alives hold the connection open) → the
QA report as a streamed assistant message → `RUN_FINISHED`.

### 11.3 Start the UI

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173
```

Type a brief (optionally start with a `project:` line to name the project):

```
project: Status page
We need a public status page that reflects our SLOs in real time.
```

The chat answers with a status note, then — after the crew finishes — the QA
report lands inline. That's the whole beat: **the crew is still the one clean
backend; CopilotKit is the thin self-hosted front door.**

> **Guardrail (carried from the storyboard, ISI-4038 §6).** Self-hosted OSS
> CopilotKit + your own model — never CopilotKit Cloud / AMP. The React app
> connects with `HttpAgent` from `@ag-ui/client` directly to *your* FastAPI
> endpoint; there is no CopilotKit-hosted service in the path.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `crewai version` ≠ 1.15.1 | `uv pip install 'crewai==1.15.1'` — the tutorial is pinned |
| Hangs on first agent | Ollama unreachable — check `OLLAMA_BASE_URL` and `curl .../api/tags` |
| `OPENAI_API_KEY` demanded | You enabled `memory=True` without a local embedder — set the Ollama embedder (research §3.4) |
| Tool-calling / delegation flaky | qwen tool-calling can wobble; fall back to sequential (drop `--hierarchical`) |
| No spans in Dynatrace | `OTEL_EXPORTER_OTLP_ENDPOINT` unset/wrong, or Collector not forwarding — and *not* `CREWAI_DISABLE_TELEMETRY` (that one only silences CrewAI's anon analytics) |
| Everything instrumented died at once | You set `OTEL_SDK_DISABLED=true` — that kills *your* OpenLIT pipeline too; unset it and use `CREWAI_DISABLE_TELEMETRY=true` if you only want CrewAI's analytics off |
| `import crewai.project` fails | Version drift — verify the decorator import path for your CrewAI version |
| BFF: `crew kickoff failed` in chat | `KICKOFF_URL` wrong or crew service down — check `curl localhost:8100/healthz` and the crew's `/healthz` |
| BFF: chat hangs then errors | Full 8-agent run exceeds `KICKOFF_TIMEOUT` (default 900 s) — raise it, or smoke-test with `BFF_ECHO_MODE=true` |

---

## Where to go next

- Enable **memory** with a local Ollama embedder for cross-run recall (research §3.4).
- Browse the **built-in tool library** before writing your own — see [§5](#5-give-your-agents-tools-built-ins--mcp--your-own--pypi) and <https://docs.crewai.com/v1.15.20/en/tools/overview>.
- Wrap the crew in a **Flow** (`@start`/`@listen`/`@router`) for retries and branching.
- Contrast **sequential vs hierarchical** delegation on camera.
- Point the CopilotKit UI at the in-cluster crew (§11) for the record-time demo.
