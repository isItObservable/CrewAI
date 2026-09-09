# BMAD Crew — CopilotKit UI (self-hosted, OSS)

The browser front-end for the tutorial's **"drive the crew from the browser"**
beat (TUTORIAL.md §11, storyboard Scene 5 — ISI-4095, board-approved 2026-09-09).

```
CopilotKit chat (this app)  --AG-UI over SSE-->  FastAPI BFF  --POST /kickoff-->  BMAD crew
        HttpAgent                copilotkit_bff.py                  server.py
```

**OSS-only wiring.** The React app connects with `HttpAgent` from
[`@ag-ui/client`](https://docs.ag-ui.com) **directly** to *your* FastAPI
backend-for-frontend — no CopilotKit Cloud, no AMP, no hosted runtime, and no
extra model key (the crew keeps using its own Ollama model). This is the
`selfManagedAgents` production path from the CopilotKit docs.

## Run it

1. Start the crew service (locally or port-forwarded):

   ```bash
   cd ../bmad-crew && uv run uvicorn bmad_crew.server:app --port 8000
   # or: kubectl -n bmad-crew port-forward svc/bmad-crew 8000:80 &
   ```

2. Start the BFF:

   ```bash
   cd ../bmad-crew
   export KICKOFF_URL=http://localhost:8000/kickoff
   uv run bmad-crew-bff          # http://0.0.0.0:8100 — check /healthz
   ```

3. Start this app:

   ```bash
   npm install
   npm run dev                   # http://localhost:5173 (proxies /copilotkit → :8100)
   ```

4. Type a brief (optional first line `project: <name>`). A status note streams
   back immediately; the QA report lands when the crew finishes (minutes —
   that's eight agents reasoning sequentially).

## Smoke-test without the crew

```bash
BFF_ECHO_MODE=true uv run bmad-crew-bff    # BFF answers without calling the crew
npm run dev                                # UI works end-to-end, no LLM needed
```

## Build for serving

```bash
npm run build    # static bundle in dist/ — serve behind any static host
```

Set `VITE_AGENT_URL` at build time if the BFF lives at another origin
(see `.env.example`).

## Verify the backend by hand (no browser)

```bash
curl -N localhost:8100/copilotkit \
  -H 'content-type: application/json' \
  -d '{"threadId":"t1","runId":"r1","messages":[{"id":"m1","role":"user","content":"project: Demo — a status page for our SLOs"}]}'
# expect: RUN_STARTED → STEP_STARTED → TEXT_MESSAGE_* → … → RUN_FINISHED
```
