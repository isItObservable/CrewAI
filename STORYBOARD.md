# STORYBOARD — CrewAI episode (25:00)

**Rebuild the BMAD crew in CrewAI → run key-free on local qwen → ship to Kubernetes → *see* it in Dynatrace.**

Part of the [isitobservable](https://isitobservable.io) series. Same shape and discipline as the
[kagent](https://github.com/isItObservable/Kagent) episode. Every command and asset referenced below is in
**this repo** ([`TUTORIAL.md`](./TUTORIAL.md), [`bmad-crew/`](./bmad-crew), [`k8s/`](./k8s),
[`observability/`](./observability)) and validated against **CrewAI 1.15.1**.

- **Host:** Henrik
- **Runtime:** local **qwen3.6** via Ollama @ `http://10.0.0.185:11434` — **no external API key**
- **Observability tenant:** Dynatrace `oat05854`
- **Source of truth:** the committed `TUTORIAL.md` + research [ISI-1583] (build/k8s) and [ISI-1584] (telemetry gap)
- **Total runtime:** 25:00 across 11 scenes

> **Accuracy notes for the recording (kagent discipline — cite real numbers, not ticket text):**
> - The trace shape is fixed and **live-validated** (ISI-1586, 10/10 assertions vs a real CrewAI 1.15.1 crew):
>   `crew <name> → task <name> → agent <role> → chat <model>` — 4 nested span levels, plus `tool <name>` spans
>   under an agent when it calls a tool. For the BMAD crew that reads as `crew BmadCrew → task … → agent … →
>   chat qwen3.6`, 8 agents sequential. (Earlier drafts showed `crew.kickoff → <agent>.execute`; the emitted span
>   names are `crew`/`task`/`agent`/`chat` — use these on screen.)
> - Signal names are exact from the live-validated OTel-GenAI contract: `gen_ai.system=crewai`,
>   `gen_ai.operation.name` (`invoke_agent` / `chat` / `execute_tool`), `gen_ai.request.model`,
>   `gen_ai.usage.input_tokens` / `output_tokens` / `total_tokens`, `gen_ai.agent.name`; metrics
>   `gen_ai.client.token.usage` and `gen_ai.client.operation.duration` (histograms).
> - **Per-run token totals and LLM p50/p90 latency are `⟨CAPTURE-AT-RECORD⟩`** — the ISI-1586 live validation ran a
>   2-task smoke crew (asserts token *presence*, not magnitude), so no full 8-agent figure exists yet. Pull the live
>   number off the Dynatrace dashboards during the take, exactly as the kagent Short cited `~9,968 tok/run`. Do
>   **not** invent a number; the VO lines below hedge ("several thousand tokens a crew run" — robust from ~5k to the
>   ~10k the comparable kagent crew burned) so they stay true regardless, then the on-screen dashboard shows exact.

---

## Timing map

| # | Scene | Start | Dur | Board beat | TUTORIAL step |
|---|-------|-------|-----|------------|---------------|
| 0 | Cold open — the hook | 0:00 | 0:45 | — | — |
| 1 | What is CrewAI | 0:45 | 2:30 | ① What is CrewAI | §3 (concept) |
| 2 | Meet the BMAD crew we're rebuilding | 3:15 | 2:00 | ② Build the crew | §3 |
| 3 | Install + point it at local qwen (key-free) | 5:15 | 2:00 | ② Build the crew | §0–2 |
| 4 | Build the crew: agents, tasks, process | 7:15 | 3:30 | ② Build the crew | §3 |
| 5 | Run it locally — watch the hand-offs | 10:45 | 2:30 | ② Build the crew | §4 |
| 6 | The token-blindness gap + the OpenLIT fix | 13:15 | 3:30 | ④ Observe it | §5 |
| 7 | See it in Dynatrace — traces, tokens, dashboards | 16:45 | 2:30 | ④ Observe it | §8 |
| 8 | Containerize + deploy to Kubernetes | 19:15 | 3:00 | ③ Deploy to k8s | §6–7 |
| 9 | Track progress, integrate, and give back | 22:15 | 2:00 | ⑤ Track / integrate | §4 (hier.), "next" |
| 10 | Outro + CTA | 24:15 | 0:45 | — | — |

**Total: 25:00.**

---

## Scene 0 — Cold open: the hook (0:00–0:45)

**On-screen:** Fast montage — the finished Dynatrace **trace waterfall** for one crew run (the `crew` span at the
top over its nested `task → agent → chat` spans), then the **Agentic Efficiency** dashboard tile showing tokens/run ticking up.
Cut to a terminal mid-run with agent names streaming. Title card: **"CrewAI, observed."**

**VO:**
> "Eight AI agents — an analyst, a PM, an architect, engineers, QA — take a one-line brief and hand it
> down the line until working software falls out the bottom. That's a *crew*. Today we build one in **CrewAI**,
> run it on our own model with **no API key**, ship it to **Kubernetes**, and — the part everyone skips — we
> make it *observable*, so you can see every agent, every hand-off, and every token in **Dynatrace**. Let's go."

---

## Scene 1 — What is CrewAI (0:45–3:15)

**On-screen:** [crewai.com](https://crewai.com) landing, then a simple animated diagram: **Agents** (role +
goal + backstory) → grouped into a **Crew** → executing **Tasks** under a **Process** (sequential / hierarchical).
Lower-third callout: *"lean · framework-independent · role-playing agents."*

**VO:**
> "CrewAI is a lean Python framework for orchestrating role-playing AI agents. It's *not* built on LangChain —
> that's deliberate; it keeps the moving parts few. Three ideas do all the work.
> An **Agent** is a persona: a role, a goal, and a backstory that shapes how it thinks.
> A **Task** is a unit of work with an expected output, assigned to an agent.
> And a **Process** decides how tasks run — **sequential**, one after another, or **hierarchical**, where a
> manager agent delegates dynamically. Today we lean on **sequential**, because it gives us something beautiful
> to observe: a clean, linear chain of hand-offs."

**On-screen (2:10):** side-by-side — `Process.sequential` (straight arrow chain) vs `Process.hierarchical`
(manager fanning out). Tag the hierarchical one *"we'll come back to this."*

---

## Scene 2 — Meet the BMAD crew we're rebuilding (3:15–5:15)

**On-screen:** The BMAD pipeline as a horizontal chain of 8 named personas with their BMAD names:
**analyst (Mary) → pm (John) → ux (Sally) → po (Sarah) → architect (Winston) → sm (Bob) → dev (Amelia) → qa (Quinn)**.
Callout: *"the same crew from our kagent & Sympozium episodes — now in CrewAI."*

**VO:**
> "We're not inventing a toy crew. We're rebuilding **BMAD** — the software-delivery method we've run in previous
> episodes — as a native CrewAI crew. Eight roles, in the order a real project moves: an **analyst** turns a vague
> brief into a crisp problem statement; a **PM** writes the PRD; **UX** maps the journeys; a **product owner**
> tightens the backlog; an **architect** designs the solution; a **scrum master** slices it into stories; a
> **senior engineer** implements the top story; and **QA** delivers a ship / no-ship call. Each one hands its
> output to the next. If you've followed our kagent episode, this is the *same crew* — the point is to see how the
> *framework* changes, not the team."

**On-screen (4:40):** Quick peek at `output/qa_report.md` from a finished run — "this is what the crew produces."

---

## Scene 3 — Install + point it at local qwen, key-free (5:15–7:15)

**On-screen:** Terminal, following `TUTORIAL.md` §0–2 verbatim. Type each command; let output land.

```bash
git clone https://github.com/isItObservable/CrewAI.git
cd CrewAI/bmad-crew
uv venv && source .venv/bin/activate
uv pip install -e .
crewai version            # → 1.15.1
```
Then the model config:
```bash
cp .env.example .env
# MODEL=ollama/qwen3.6   OLLAMA_BASE_URL=http://10.0.0.185:11434
curl http://10.0.0.185:11434/api/tags | grep qwen3.6
```

**VO:**
> "Setup is three commands with `uv`: clone, virtual-env, install. `crewai version` should say **1.15.1** — the
> whole tutorial is pinned there, because CrewAI moves fast and import paths drift.
> Now the differentiator: we point the crew at **our own model**. Copy the example env, and it already targets
> **qwen3.6 on our Ollama host** — that Mac Studio at `10.0.0.185`. No OpenAI key, no Anthropic key, no data
> leaving the building. One `curl` confirms the model's actually there before we spend a single token."

**On-screen (7:00):** Highlight the `.env` line — no `*_API_KEY` anywhere. Freeze-frame stamp: **"$0 in API cost."**

---

## Scene 4 — Build the crew: agents, tasks, process (7:15–10:45)

**On-screen:** Editor tour of three files. Scroll slowly; highlight the marked lines.

1. **`config/agents.yaml`** — highlight the `analyst` block (role / goal / backstory). *"This is the persona."*
2. **`config/tasks.yaml`** — highlight `write_prd` and its **`context: [analyze_brief]`**. *"This line is the hand-off."*
3. **`crew.py`** — highlight `@CrewBase`, the `@agent`/`@task` decorators, `build_llm()`, and
   `process=Process.sequential`.

**VO:**
> "Three files define the whole crew. **`agents.yaml`** holds the eight personas — here's Mary, the analyst: a
> role, a goal, and a backstory that steers her behavior. **`tasks.yaml`** holds the eight units of work, and this
> is the line that matters most —" *(highlight `context: [analyze_brief]`)* "— `context`. It names the upstream
> task whose output feeds this one. We wire every hand-off explicitly, not just by list order, so the chain is
> legible in the **code** *and*, in a minute, in the **trace**.
> Then **`crew.py`** stitches it together. `@CrewBase` collects the agents and tasks; `build_llm()` builds **one
> shared qwen LLM** and injects it into every agent — that's why the whole crew is key-free; and
> `Process.sequential` runs the eight tasks in order. Notice there's also a `hierarchical_crew()` down here — hold
> that thought, it's our wow beat later."

**On-screen (10:20):** Zoom the `build_llm()` function → one LLM object flowing into all 8 agents (animated arrows).

---

## Scene 5 — Run it locally: watch the hand-offs (10:45–13:15)

**On-screen:** Full terminal. Run the zero-arg sample (TUTORIAL §4):
```bash
uv run bmad-crew
```
`verbose=True` output streams: analyst reasons → PM picks up → … Speed-ramp the middle; land full-speed on the
architect and QA. Then:
```bash
cat output/qa_report.md
```

**VO:**
> "Now run it. Zero arguments uses a built-in sample brief — a Slack stand-up bot. Because verbose is on, you
> watch the crew *think*: the analyst frames the problem, hands to the PM, who writes the PRD, which flows to UX,
> then the PO, the architect… each agent picking up exactly the context the previous one produced. This is the
> sequential process doing its job — a relay race, not a free-for-all. A couple of minutes later, QA writes the
> final delivery to `output/qa_report.md`: a full PRD-to-ship pipeline, start to finish, on a model running in
> our own rack."

**On-screen (12:55):** Optional custom-brief flash — `uv run bmad-crew --project "…" --brief "…"` — *"drive it
with your own idea."*

---

## Scene 6 — The token-blindness gap + the OpenLIT fix (13:15–16:45)

**On-screen:** Split panel. LEFT: CrewAI's *default* trace — only **CHAIN + AGENT** spans, a red **"tokens: ?"**
overlay. RIGHT: after OpenLIT — an added **`chat qwen3.6`** LLM span carrying `gen_ai.usage.*`, green
**"tokens: ✓"**. Then a short editor look at `bmad-crew/src/bmad_crew/observability.py`.

**VO:**
> "Here's the part every agent tutorial skips. Out of the box, CrewAI is **trace-rich but token-blind**. Its
> default instrumentation gives you chain and agent spans — you can see *that* an agent ran, but not the **LLM
> call** underneath, and crucially **not the tokens**. It also emits **no OTLP metrics** at all. For an
> agent system where tokens *are* the cost and the latency, that's flying blind." *(research: ISI-1584)*
> "So we adopt **OpenLIT** — an OpenTelemetry-native instrumentation. One import at startup and it emits proper
> `gen_ai.*` spans **and** GenAI metrics: token-usage and operation-duration histograms, straight to OTLP. No
> custom code in the agents, no attribute remapping downstream — it speaks Dynatrace's native GenAI model
> directly."

**On-screen (15:30):** Terminal — enable and re-run (TUTORIAL §5):
```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
uv run bmad-crew
# [bmad-crew] OpenTelemetry instrumentation: ON
```

**VO (cont.):**
> "Turning it on is one environment variable — point it at a collector and re-run. The startup line confirms it's
> **ON**. Leave that variable unset and the app runs perfectly fine with no telemetry — instrumentation that's
> safe by omission. Now let's go see what landed."

---

## Scene 7 — See it in Dynatrace: traces, tokens, dashboards (16:45–19:15)

**On-screen:** Dynatrace (`oat05854`). (1) The **distributed trace**: the `crew` root → 8 nested
`task → agent` pairs → each `agent` wrapping a `chat qwen3.6` span. Hover an LLM span to reveal
`gen_ai.usage.input_tokens` / `output_tokens`. (2) The **CrewAI Agentic Efficiency** dashboard — tokens/run,
**tokens per agent**, LLM latency p50/p90. (3) The **CrewAI Crew Health** dashboard — kickoff success rate,
task duration by agent.

**VO:**
> "This is the payoff. One crew run, as a single distributed trace: the `crew` span at the root, the eight agents
> nested beneath in the exact order they ran, and inside each one the `chat qwen3.6` call. Hover any LLM span and
> there are the tokens — input and output — the numbers we were blind to a minute ago.
> Roll that up and you get the dashboards the observability build ships. **Agentic Efficiency**: tokens per run —
> ⟨read the live figure — several thousand tokens a crew run⟩ — tokens *per agent* so you can see which persona is
> expensive, and LLM latency p50 and p90. And **Crew Health**: is the kickoff succeeding, and how long does each
> agent's task take. You've gone from 'the agents did *something*' to a per-agent, per-token account of the whole
> crew."

> **[record-time]** substitute the bracketed hedge with the on-screen number, e.g. *"about ten thousand tokens a
> crew"* — value is `⟨CAPTURE-AT-RECORD⟩` off the Agentic Efficiency tile (the comparable kagent crew ran ~10k).

---

## Scene 8 — Containerize + deploy to Kubernetes (19:15–22:15)

**On-screen:** TUTORIAL §6–7. Build + smoke-test, then apply manifests.
```bash
cd ..                                   # repo root = build context
docker build -t ghcr.io/isitobservable/bmad-crew:1.0.0 .
docker run --rm -p 8000:8000 -e OLLAMA_BASE_URL=http://10.0.0.185:11434 \
  ghcr.io/isitobservable/bmad-crew:1.0.0
curl localhost:8000/healthz            # → ok
```
Then k8s — quick tour of `k8s/` (namespace, configmap, secret, pvc, deployment, service, hpa), then:
```bash
kubectl apply -f k8s/
kubectl -n bmad-crew rollout status deploy/bmad-crew
kubectl -n bmad-crew port-forward svc/bmad-crew 8080:80 &
curl -s localhost:8080/kickoff -H 'content-type: application/json' \
  -d '{"project":"Status page","brief":"A public SLO status page..."}' | jq -r .result
```

**VO:**
> "A crew you can only run from your laptop isn't a product. So we wrap it in a small **FastAPI** service —
> `POST /kickoff` runs the crew, `GET /healthz` is the probe — build one image, and smoke-test it locally.
> Then Kubernetes: a namespace, a ConfigMap for the Ollama URL and OTLP endpoint, a Deployment, a Service, an
> HPA, and a PVC for CrewAI's memory. Apply, wait for the rollout, port-forward, and fire a real brief at the
> `/kickoff` endpoint — the crew runs *in-cluster* and the same trace lights up in Dynatrace.
> Two things bite here, straight from the research: the pods **must** reach the Ollama host — no egress, and the
> first LLM call hangs forever — and CrewAI's memory is on local disk, so it needs that **PVC** to survive a
> restart. Both are called out in the tutorial and owned by the cluster build."

**On-screen (22:00):** Lower-third: *"cluster provisioning: ISI-1588 (ProxOps) · dashboards: ISI-1586."*

---

## Scene 9 — Track progress, integrate, and give back (22:15–24:15)

**On-screen:** (1) Quick `--hierarchical` run (TUTORIAL §4 optional): the manager delegating — messier trace,
non-deterministic. (2) The "next" list from TUTORIAL: memory with a local embedder, custom `@tool`s, wrapping in
a **Flow**. (3) A slide framing the **upstream tracing contribution** (the token-blindness gap → OpenLIT-native
`gen_ai.*`).

**VO:**
> "Two directions to take this further. First, **dynamic delegation**: add `--hierarchical` and a manager agent
> assigns work on the fly instead of a fixed chain. It's heavier on the model's tool-calling and the trace is
> messier — great to *contrast*, but sequential stays the backbone. Second, **integration**: give the dev agent
> real `@tool`s so it can read the repo or run tests, turn on **memory** with a local embedder for cross-run
> recall, or wrap the crew in a **Flow** for retries and branching.
> And here's our takeaway for the ecosystem — the token-blindness we hit isn't unique to us. That's exactly the
> kind of gap worth pushing **upstream**, so CrewAI's default traces carry `gen_ai.*` tokens for everyone. That's
> the isitobservable way: don't just consume the tool — leave it more observable than you found it."

---

## Scene 10 — Outro + CTA (24:15–25:00)

**On-screen:** Recap chips animate in — **Build → Run key-free → Observe → Deploy → Give back**. Repo URL
`github.com/isItObservable/CrewAI`, then subscribe / like card.

**VO:**
> "That's a full agent crew — built in CrewAI, running on your own model for nothing, deployed to Kubernetes, and
> fully observable in Dynatrace, tokens and all. Every command is in the repo, linked below — clone it and follow
> along. If this helped, subscribe, and tell us in the comments what crew *you'd* build. See you in the next one."

---

## Appendix — asset ↔ scene cross-reference (for the editor)

| Asset (this repo) | Used in |
|---|---|
| `TUTORIAL.md` §0–2 | Scene 3 |
| `bmad-crew/config/agents.yaml`, `tasks.yaml`, `crew.py` | Scene 4 |
| `bmad-crew` local run, `output/qa_report.md` | Scenes 2, 5 |
| `bmad-crew/src/bmad_crew/observability.py` (OpenLIT) | Scene 6 |
| Dynatrace `oat05854` — trace + **Agentic Efficiency** + **Crew Health** dashboards (ISI-1586) | Scenes 0, 7 |
| `Dockerfile`, `bmad-crew/server.py`, `k8s/*` | Scene 8 |
| `crew.py: hierarchical_crew()` (`--hierarchical`) | Scenes 1, 9 |

**Open dependencies for the shoot (not for the storyboard):**
- Exact **tokens/run** and **LLM p50/p90** — capture live off the ISI-1586 dashboards at record time (`⟨CAPTURE-AT-RECORD⟩`).
- In-cluster `/kickoff` demo (Scene 8) needs the ISI-1588 cluster live with Ollama egress + default StorageClass.
- Repo must be public/landed before the "clone it and follow along" CTA — currently staged pending write access (ISI-1585).

[ISI-1583]: https://../ISI/issues/ISI-1583
[ISI-1584]: https://../ISI/issues/ISI-1584
[ISI-1586]: https://../ISI/issues/ISI-1586
[ISI-1588]: https://../ISI/issues/ISI-1588
