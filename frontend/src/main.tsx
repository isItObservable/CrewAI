import React from "react";
import ReactDOM from "react-dom/client";
import { HttpAgent } from "@ag-ui/client";
import { CopilotKit, CopilotChat } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import App from "./App";
import "./app.css";

/**
 * Self-hosted CopilotKit UI for the BMAD crew (ISI-4095).
 *
 * OSS-only wiring: an HttpAgent from @ag-ui/client connects DIRECTLY to our
 * FastAPI backend-for-frontend (bmad_crew/copilotkit_bff.py) speaking the open
 * AG-UI protocol over SSE. No CopilotKit Cloud, no AMP, no hosted runtime, and
 * no extra model key — the crew keeps using its own Ollama model.
 *
 * In dev, Vite proxies /copilotkit -> http://localhost:8100 (vite.config.ts).
 * Point VITE_AGENT_URL elsewhere (e.g. an in-cluster BFF) when needed.
 */
const agentUrl =
  (import.meta.env.VITE_AGENT_URL as string | undefined) ?? "/copilotkit";

const AGENT_ID = "bmad-crew";
const bmadCrewAgent = new HttpAgent({ url: agentUrl });

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <CopilotKit selfManagedAgents={{ [AGENT_ID]: bmadCrewAgent }}>
      <App>
        <CopilotChat
          agentId={AGENT_ID}
          className="bmad-chat"
          labels={{
            chatInputPlaceholder: "Type the crew brief…",
            welcomeMessageText:
              "Type a brief for the crew — e.g. 'project: Status page — we need a public page that reflects our SLOs in real time'.",
          }}
        />
      </App>
    </CopilotKit>
  </React.StrictMode>,
);
