# GitHub MCP Demo — BMAD Crew Coding Test

This document covers the **"real coding test"** segment of episode 94:
giving the BMAD crew a real product brief and watching it commit working code
to GitHub, the same way Sympozium and kagent were tested in earlier episodes.

---

## What we're testing

The crew receives the [sympozium-todo-demo](https://github.com/isItObservable/sympozium-todo-demo)
brief: build a todo app with a **FastAPI backend + React frontend**, wired
together with Docker Compose.

The crew's dev agent (Amelia) uses the **GitHub MCP server** to:
1. Create a feature branch in your fork
2. Commit each file (backend, frontend, docker-compose) to that branch
3. Open a pull request for QA review

---

## Prerequisites

### 1. Fork the reference repo

```bash
gh repo fork https://github.com/isItObservable/sympozium-todo-demo \
  --clone=false \
  --org your-org            # or omit --org to fork into your personal account
```

### 2. Create a fine-grained GitHub PAT

Go to **GitHub → Settings → Developer settings → Fine-grained tokens → Generate new token**.

Required permissions on the forked repo:
| Permission | Access |
|-----------|--------|
| Contents | Read & write |
| Issues | Read & write |
| Pull requests | Read & write |
| Metadata | Read (auto-selected) |

```bash
export GITHUB_PERSONAL_ACCESS_TOKEN=github_pat_...
export GITHUB_TARGET_REPO=your-org/sympozium-todo-demo
```

### 3. Choose MCP transport

**Option A — Remote (no Docker required):**
```bash
export GITHUB_MCP_MODE=remote   # default
```
The crew connects to `https://api.githubcopilot.com/mcp/` using your PAT.

**Option B — Docker (local MCP server):**
```bash
export GITHUB_MCP_MODE=docker
docker pull ghcr.io/github/github-mcp-server
```

---

## Running the test

```bash
cd tutorial/crewai
export GITHUB_PERSONAL_ACCESS_TOKEN=github_pat_...
export GITHUB_TARGET_REPO=your-org/sympozium-todo-demo

bash scripts/test_todo_app.sh
```

Or drive it directly:

```bash
cd tutorial/crewai/bmad-crew
uv run bmad-crew \
  --project "Sympozium Todo App" \
  --brief "Build a todo app with FastAPI backend and React frontend..." \
  --github-repo your-org/sympozium-todo-demo
```

### Hierarchical mode variant

```bash
bash scripts/test_todo_app.sh   # MODE=sequential (default)
MODE=hierarchical bash scripts/test_todo_app.sh
```

In hierarchical mode the BMad Orchestrator (manager LLM) delegates tasks
dynamically — compare the trace span trees in Dynatrace to see the difference.

---

## What to watch in the terminal

```
[bmad-crew] GitHub tools: ON (remote) — 26 tool(s) available
[agent: Mary] Analyzing brief...          # analyst
[agent: John] Writing PRD...              # pm → may open GitHub issues
[agent: Winston] Designing architecture...# architect → may commit design doc
[agent: Bob] Slicing stories...           # sm → may open story issues
[agent: Amelia] Implementing story...     # dev → creates branch, commits files, opens PR
[agent: Quinn] QA review...              # qa → reviews implementation
```

---

## What to check in GitHub

After the run completes, open your fork:

1. **Branches** — `feature/bmad-crew-impl` should appear
2. **Files committed** — look for `backend/`, `frontend/`, `docker-compose.yml`, `README.md`
3. **Pull request** — titled "BMAD crew: implement highest-priority story"
4. **QA report** — `output/qa_report.md` locally

---

## What to check in Dynatrace (if observability is on)

The GitHub MCP tool calls appear as `gen_ai.operation.name=execute_tool` spans
under the dev agent's trace node:

```
crew.kickoff
  └── task: implement_story (agent: Amelia)
      ├── llm: chat (qwen3.6) — plan the implementation
      ├── tool: create_branch
      ├── tool: create_or_update_file  (backend/main.py)
      ├── tool: create_or_update_file  (backend/models.py)
      ├── tool: create_or_update_file  (frontend/src/App.tsx)
      ├── tool: create_or_update_file  (docker-compose.yml)
      └── tool: create_pull_request
```

The agentic efficiency dashboard shows tool call rate and errors per agent —
useful for spotting which GitHub operations are slow or failing.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `GitHub tools disabled — could not start MCP server` | Check PAT is exported and has correct scopes |
| `422 Unprocessable Entity` from GitHub API | PAT missing `pull_requests` permission |
| Dev agent writes code as markdown instead of committing | GitHub tools not loaded (see above) |
| `crewai-tools[mcp]` import error | Run `uv pip install "crewai-tools[mcp]>=0.30.0"` |
| MCP Docker mode: `cannot pull image` | `docker pull ghcr.io/github/github-mcp-server` first |

---

## Comparing to Sympozium / kagent

| Aspect | Sympozium | kagent | BMAD Crew (CrewAI) |
|--------|-----------|--------|---------------------|
| Framework | OpenAI Swarm | Kubernetes-native | CrewAI |
| Agent roles | Configurable | Configurable | BMAD 8-persona pipeline |
| GitHub integration | Via tools | Via tools | GitHub MCP server |
| Process mode | Sequential | Sequential | Sequential + Hierarchical |
| Observability | OTel spans | OTel spans | OpenLIT / OpenLLMetry / native events |
| Local LLM | Yes (Ollama) | Yes (Ollama) | Yes (Ollama/qwen3.6) |
