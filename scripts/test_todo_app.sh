#!/usr/bin/env bash
# ============================================================================
# test_todo_app.sh — Drive the BMAD crew with the sympozium-todo-demo brief.
#
# This is the "real coding test" segment of episode 94:
#   - The BMAD crew receives a real product brief (a todo app)
#   - The dev agent (Amelia) uses the GitHub MCP to create a branch,
#     commit backend + frontend code, and open a pull request
#   - The QA agent (Quinn) reviews and issues a ship / no-ship decision
#
# Prerequisites:
#   1. uv + Python 3.10-3.12 installed
#   2. Ollama running with qwen3.6 model pulled
#   3. GITHUB_PERSONAL_ACCESS_TOKEN exported (fine-grained PAT)
#      Scopes: Contents (read/write), Issues (read/write), Pull Requests (read/write)
#   4. A fork of https://github.com/isItObservable/sympozium-todo-demo
#      under your GitHub org
#
# Usage:
#   export GITHUB_PERSONAL_ACCESS_TOKEN=github_pat_...
#   export GITHUB_TARGET_REPO=your-org/sympozium-todo-demo   # your fork
#   bash scripts/test_todo_app.sh
#
# Optional overrides:
#   GITHUB_MCP_MODE=docker      # use local Docker MCP server instead of remote
#   MODEL=ollama/qwen3.6        # default model
#   OLLAMA_BASE_URL=http://...  # default: http://localhost:11434
#   MODE=hierarchical           # set to "hierarchical" for Option B demo
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CREW_DIR="$(cd "${SCRIPT_DIR}/../bmad-crew" && pwd)"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
: "${GITHUB_PERSONAL_ACCESS_TOKEN:?GITHUB_PERSONAL_ACCESS_TOKEN must be set}"
: "${GITHUB_TARGET_REPO:?GITHUB_TARGET_REPO must be set (e.g. your-org/sympozium-todo-demo)}"
: "${GITHUB_MCP_MODE:=remote}"
: "${MODEL:=ollama/qwen3.6}"
: "${OLLAMA_BASE_URL:=http://localhost:11434}"
: "${MODE:=sequential}"

TODO_PROJECT="Sympozium Todo App"
TODO_BRIEF='Build a todo app with a Python FastAPI backend and a React + TypeScript frontend.

Backend requirements:
- FastAPI with CRUD endpoints: POST /todos, GET /todos, GET /todos/{id}, PUT /todos/{id}, DELETE /todos/{id}
- SQLite database via SQLAlchemy (async)
- Pydantic v2 models for request/response validation
- CORS enabled for the frontend origin
- Dockerfile for the backend service

Frontend requirements:
- React 18 + TypeScript + Vite
- Display list of todos (title, done status)
- Add new todo via an input form
- Toggle done status with a checkbox
- Delete a todo
- Fetches from the backend API (configurable via VITE_API_URL env var)
- Dockerfile for the frontend service

Deployment:
- docker-compose.yml wiring backend (port 8000) + frontend (port 5173)
- README with build and run instructions

Non-goals for v1: user auth, real-time sync, pagination.'

# ---------------------------------------------------------------------------
# Check dependencies
# ---------------------------------------------------------------------------
echo "=========================================="
echo "  BMAD Crew — Todo App Coding Test"
echo "  Repo:  ${GITHUB_TARGET_REPO}"
echo "  Model: ${MODEL}"
echo "  Mode:  ${MODE}"
echo "=========================================="
echo ""

if ! command -v uv &>/dev/null; then
  echo "ERROR: 'uv' not found. Install with: curl -Ls https://astral.sh/uv/install.sh | sh"
  exit 1
fi

if ! curl -sf "${OLLAMA_BASE_URL}/api/tags" >/dev/null 2>&1; then
  echo "ERROR: Ollama not reachable at ${OLLAMA_BASE_URL}. Start it first."
  exit 1
fi

echo "✓ uv found"
echo "✓ Ollama reachable at ${OLLAMA_BASE_URL}"
echo ""

# ---------------------------------------------------------------------------
# Build environment for the crew run
# ---------------------------------------------------------------------------
cd "${CREW_DIR}"

# Activate or create the virtual environment
if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  uv venv
fi

HIERARCHICAL_FLAG=""
if [ "${MODE}" = "hierarchical" ]; then
  HIERARCHICAL_FLAG="--hierarchical"
  echo "Mode: HIERARCHICAL (manager LLM delegates dynamically)"
else
  echo "Mode: SEQUENTIAL (analyst → pm → ux → po → architect → sm → dev → qa)"
fi

echo ""
echo "Brief excerpt:"
echo "${TODO_BRIEF}" | head -5
echo "  [...]"
echo ""
echo "Kicking off the BMAD crew..."
echo "  Watch the agent progress in your terminal."
echo "  When the dev agent runs, it will use GitHub MCP to:"
echo "    1. Create branch: feature/bmad-crew-impl"
echo "    2. Commit backend + frontend files"
echo "    3. Open a pull request → check ${GITHUB_TARGET_REPO} on GitHub"
echo ""

# ---------------------------------------------------------------------------
# Run the crew
# ---------------------------------------------------------------------------
export MODEL
export OLLAMA_BASE_URL
export GITHUB_PERSONAL_ACCESS_TOKEN
export GITHUB_MCP_MODE

START_TS=$(date +%s)

uv run bmad-crew \
  --project "${TODO_PROJECT}" \
  --brief "${TODO_BRIEF}" \
  --github-repo "${GITHUB_TARGET_REPO}" \
  ${HIERARCHICAL_FLAG}

END_TS=$(date +%s)
ELAPSED=$(( END_TS - START_TS ))

# ---------------------------------------------------------------------------
# Post-run validation
# ---------------------------------------------------------------------------
echo ""
echo "=========================================="
echo "  Run complete (${ELAPSED}s)"
echo "=========================================="
echo ""

OUTPUT_FILE="${CREW_DIR}/output/qa_report.md"
if [ -f "${OUTPUT_FILE}" ]; then
  echo "✓ QA report written to: ${OUTPUT_FILE}"
  echo ""
  echo "--- QA report (last 30 lines) ---"
  tail -30 "${OUTPUT_FILE}"
  echo "--- end ---"
else
  echo "WARNING: QA report not found at ${OUTPUT_FILE}"
fi

echo ""
echo "Next steps:"
echo "  1. Open https://github.com/${GITHUB_TARGET_REPO}/pulls"
echo "     to review the pull request opened by the dev agent."
echo "  2. If observability is on, check Dynatrace for the trace:"
echo "     crew → task → agent → llm/tool span tree."
echo "  3. Check token usage on the dashboard:"
echo "     observability/dashboards/crewai-agentic-efficiency-dashboard.json"
echo ""
