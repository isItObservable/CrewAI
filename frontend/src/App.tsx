import type { ReactNode } from "react";

export default function App({ children }: { children: ReactNode }) {
  return (
    <div className="shell">
      <header className="masthead">
        <span className="badge">IsItObservable</span>
        <h1>BMAD Crew — drive it from the browser</h1>
        <p>
          Self-hosted <strong>CopilotKit</strong> (OSS) → AG-UI/SSE → FastAPI BFF →{" "}
          <code>POST /kickoff</code> → 8 CrewAI agents on your own Ollama model.
          No CopilotKit Cloud, no extra API key.
        </p>
      </header>
      <main>{children}</main>
      <footer>
        A full sequential crew run takes minutes — the chat streams a status note,
        holds the connection, then lands the QA report.
      </footer>
    </div>
  );
}
