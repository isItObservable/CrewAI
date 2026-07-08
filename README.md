# CrewAI — BMAD crew, observed

Part of the **[isitobservable](https://isitobservable.io)** tutorial series. This repo
rebuilds our **BMAD software-delivery crew** (analyst → PM → UX → PO → architect → SM →
dev → QA) in **[CrewAI](https://crewai.com)**, runs it against a **local qwen model via
Ollama** (no external API key), packages it for **Kubernetes**, and wires it to
**OpenTelemetry → Dynatrace** so you can *see* the agents work.

It is a **follow-along tutorial**, in the same shape as our
[kagent](https://github.com/isItObservable/Kagent) episode. Start with
**[TUTORIAL.md](./TUTORIAL.md)**.

## What you'll build

| Stage | Outcome |
|-------|---------|
| 1. Install CrewAI | `crewai` 1.15.1 in a clean venv |
| 2. Build the crew | 8 BMAD agents + 8 tasks, sequential process, against local qwen |
| 3. Run locally | `uv run bmad-crew` → a full PRD→architecture→stories→code→QA run |
| 4. Instrument | OpenLIT emits `gen_ai.*` spans + GenAI metrics (CrewAI is token-blind by default) |
| 5. Containerize | Dockerfile → image |
| 6. Provision a cluster | Cluster API on Proxmox **or** GKE — your choice ([`docs/cluster-setup.md`](./docs/cluster-setup.md)) |
| 7. Deploy to k8s | Deployment/Service/ConfigMap/Secret/PVC + a kickoff API |
| 8. Verify | tokens + trace waterfall land in Dynatrace |

## Repository layout

```
CrewAI/
├── README.md                 # you are here
├── TUTORIAL.md               # numbered, host-followable steps
├── Dockerfile                # container image for the crew service
├── bmad-crew/                # the CrewAI application
│   ├── pyproject.toml
│   ├── .env.example
│   └── src/bmad_crew/
│       ├── config/agents.yaml   # the 8 BMAD personas as CrewAI agents
│       ├── config/tasks.yaml    # the 8 hand-offs, wired via `context`
│       ├── crew.py              # @CrewBase — sequential (+ optional hierarchical)
│       ├── main.py              # CLI entrypoint
│       ├── server.py            # FastAPI /kickoff for k8s
│       └── observability.py     # OpenLIT OTel init (import-safe)
├── k8s/                      # namespace, configmap, secret, pvc, deployment, service, hpa, otel-collector
├── docs/
│   └── cluster-setup.md      # provision a cluster: Cluster API on Proxmox OR GKE
└── observability/           # alignment contract with the dashboards build
```

## Why CrewAI here

CrewAI is a lean, LangChain-independent framework for role-playing agent crews. BMAD is
a linear, role-based pipeline — a near-textbook fit for CrewAI's `Process.sequential`,
where each task's output becomes the next task's context. That also gives us a **clean
linear trace** to observe.

## Observability note

CrewAI is **trace-rich but token-blind by default** and emits **no OTLP metrics**. We
adopt **OpenLIT** (OpenTelemetry-native) to get `gen_ai.*` spans and real GenAI metrics
straight into Dynatrace. See [`observability/README.md`](./observability/README.md).

## Requirements

- Python 3.10–3.12, [`uv`](https://docs.astral.sh/uv/)
- Network reach to an Ollama host with a `qwen3.6` tag (set `OLLAMA_BASE_URL` to yours)
- (Deploy) a Kubernetes cluster + registry — don't have one? See
  [`docs/cluster-setup.md`](./docs/cluster-setup.md) (Cluster API on Proxmox or GKE);
  (observe) an OTel Collector → Dynatrace
