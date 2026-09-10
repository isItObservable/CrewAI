# BMAD Crew UI — CopilotKit + Next.js

Real-time web interface for the BMAD CrewAI pipeline, built with
[CopilotKit](https://docs.copilotkit.ai) and Next.js 14.

```
┌──────────────────────────────────────────────────┐
│  BMAD Crew — CrewAI               ● localhost:8000│
├───────────────────┬──────────────────────────────┤
│                   │  Agent Timeline (SSE)         │
│  CopilotKit Chat  │  🔍 Mary  · Business Analyst  │
│                   │  📋 John  · Product Manager   │
│  "Run the BMAD    │  🎨 Sally · UX Designer  ←🟢 │
│   crew for a      │  ✅ Sarah · Product Owner     │
│   todo app..."    │  🏗️ Winston · Architect       │
│                   │  📌 Bob   · Scrum Master      │
│                   │  💻 Amelia · Senior Engineer  │
│                   │  🧪 Quinn · QA Architect      │
│                   ├──────────────────────────────┤
│                   │  QA Report (Markdown)        │
└───────────────────┴──────────────────────────────┘
```

---

## Quick start (local)

```bash
cd tutorial/crewai/ui

# 1. Install deps
npm install

# 2. Configure
cp .env.local.example .env.local
# Edit .env.local: set BMAD_CREW_URL to your FastAPI server
# Default: http://localhost:8000 (run the FastAPI server first)

# 3. Start
npm run dev
# → open http://localhost:3000
```

### Start the FastAPI backend first

```bash
cd ../bmad-crew
uv run uvicorn bmad_crew.server:app --host 0.0.0.0 --port 8000
```

---

## LLM adapter options

Set `COPILOTKIT_ADAPTER` in `.env.local`:

| Value | Requires |
|-------|---------|
| `ollama` (default) | Ollama running locally with `qwen3.6` pulled |
| `openai` | `OPENAI_API_KEY` in `.env.local` |
| `anthropic` | `ANTHROPIC_API_KEY` in `.env.local` |

---

## Using the chat

1. Type a project brief in the chat sidebar, e.g.:
   > "Run the BMAD crew for a todo app with FastAPI backend and React frontend"
2. The AI extracts the project name + brief and calls `kickoff_crew`.
3. Watch the Agent Timeline — agents light up as they run.
4. The QA report appears in the bottom panel when the crew finishes.

**With GitHub integration:**
> "Run the crew for a todo app and commit the code to myorg/my-todo-repo"

This passes `github_repo=myorg/my-todo-repo` to the crew.
The dev agent (Amelia) will create a branch, commit files, and open a PR.

---

## Kubernetes deployment

```bash
# 1. Edit k8s/configmap.yaml — set OLLAMA_BASE_URL and the service URLs
# 2. Build and push the image
docker build -t ghcr.io/isitobservable/bmad-crew-ui:latest .
docker push ghcr.io/isitobservable/bmad-crew-ui:latest

# 3. Apply manifests (namespace already created by bmad-crew)
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

# 4. Get the external IP
kubectl get svc -n bmad-crew bmad-crew-ui
```

---

## Architecture

```
Browser
  ├── CopilotKit Chat  →  POST /api/copilotkit  (Next.js route)
  │                              │
  │                              └── CopilotRuntime (Ollama/OpenAI/Anthropic)
  │                                    └── kickoff_crew action
  │                                          └── POST /kickoff/async  (FastAPI)
  │
  └── AgentTimeline    →  GET /stream/{run_id}  (FastAPI SSE)
        (EventSource)         real-time agent lifecycle events
```
