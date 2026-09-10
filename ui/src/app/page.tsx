"use client";

/**
 * BMAD Crew — CopilotKit UI
 *
 * Layout:
 *   ┌──────────────────────────────────────────────────┐
 *   │  Header                                          │
 *   ├───────────────────┬──────────────────────────────┤
 *   │                   │                              │
 *   │  CopilotKit Chat  │  Agent Timeline (SSE)        │
 *   │  (left sidebar)   │                              │
 *   │                   ├──────────────────────────────┤
 *   │                   │  QA Report (OutputPanel)     │
 *   │                   │                              │
 *   └───────────────────┴──────────────────────────────┘
 *
 * The user types a project brief into the chat.  CopilotKit's AI interprets
 * the message and calls the `kickoff_crew` action, which starts a crew run on
 * the FastAPI backend and returns a run_id.  The AgentTimeline subscribes to
 * /stream/{run_id} and lights up each agent as it executes.
 */

import { useState, useEffect } from "react";
import { CopilotKit } from "@copilotkit/react-core";
import { CopilotSidebar, useCopilotChatSuggestions } from "@copilotkit/react-ui";
import { useCopilotAction } from "@copilotkit/react-core";
import AgentTimeline from "./components/AgentTimeline";
import OutputPanel from "./components/OutputPanel";

const CREW_URL = process.env.NEXT_PUBLIC_BMAD_CREW_URL || "/api/crew";

// Suggestions shown in the empty chat state
const CHAT_SUGGESTIONS = [
  "Run the BMAD crew for a todo app with FastAPI backend and React frontend",
  "Plan and implement a public SLO status page in Python + Svelte",
  "Build a Slack stand-up bot — self-hosted, no paid SaaS",
];

// ---------------------------------------------------------------------------
// Inner component — needs to be inside <CopilotKit> to use hooks
// ---------------------------------------------------------------------------
function CrewApp() {
  const [runId, setRunId] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Register the kickoff_crew action so the AI can trigger crew runs.
  // The actual HTTP call lives in /api/copilotkit/route.ts; here we only
  // handle the client-side side-effect (storing the run_id).
  useCopilotAction({
    name: "kickoff_crew",
    description:
      "Call this whenever the user wants to build, create, or start a software project. " +
      "Pass the raw user input as-is — the crew will extract details automatically.",
    parameters: [
      {
        name: "input",
        type: "string",
        description: "The user's full project description exactly as they wrote it.",
        required: false,
      },
      {
        name: "github_repo",
        type: "string",
        description: "GitHub repo slug (owner/repo) if the user mentioned one.",
        required: false,
      },
      {
        name: "hierarchical",
        type: "boolean",
        description: "True if the user asked for a manager/hierarchical process.",
        required: false,
      },
    ],
    handler: async ({ input, github_repo, hierarchical }) => {
      setResult(null);
      setError(null);

      const brief = input || "Build the described project.";
      // Use first few words as the project name.
      const project = brief.split(" ").slice(0, 5).join(" ");

      try {
        const resp = await fetch(`${CREW_URL}/kickoff/async`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project,
            brief,
            github_repo: github_repo || "",
            hierarchical: hierarchical || false,
          }),
        });

        if (!resp.ok) {
          const msg = await resp.text();
          setError(`Failed to start crew: ${msg}`);
          return { error: msg };
        }

        const data = await resp.json() as { run_id: string };
        setRunId(data.run_id);
        return {
          run_id: data.run_id,
          message: `Crew pipeline started! Watch the Agent Timeline →`,
        };
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(`Failed to start crew: ${msg}`);
        return { error: msg };
      }
    },
    // Show a status card while the action runs (client-side actions use `render`).
    render: ({ status }) =>
      status === "executing" ? (
        <div className="flex items-center gap-2 text-sm text-indigo-400 py-1">
          <span className="inline-block w-2 h-2 rounded-full bg-indigo-500 animate-ping" />
          Starting crew pipeline…
        </div>
      ) : <></>,
  });

  // Offer contextual suggestions in the empty chat state.
  useCopilotChatSuggestions({
    instructions:
      "Suggest realistic software project briefs the user can run through the BMAD crew.",
    minSuggestions: 2,
    maxSuggestions: 3,
  });

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header className="flex items-center gap-3 px-6 py-3 border-b border-slate-700/60 bg-slate-900 shrink-0">
        <span className="text-xl">🤖</span>
        <div>
          <h1 className="text-base font-semibold text-slate-100 leading-tight">
            BMAD Crew — CrewAI
          </h1>
          <p className="text-xs text-slate-500 leading-tight">
            8-agent software delivery pipeline · powered by CopilotKit
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2 text-xs text-slate-600">
          <span className="w-2 h-2 rounded-full bg-emerald-500" />
          {CREW_URL}
        </div>
      </header>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">

        {/* Right panel: timeline + output */}
        <main className="flex-1 flex flex-col overflow-hidden">
          {/* Agent Timeline — top half */}
          <div className="flex-1 overflow-y-auto border-b border-slate-700/50">
            <AgentTimeline
              runId={runId}
              crewUrl={CREW_URL}
              onDone={(res) => setResult(res)}
              onError={(msg) => setError(msg)}
            />
          </div>

          {/* QA Report — bottom half */}
          <div className="flex-1 overflow-y-auto">
            <OutputPanel result={result} error={error} />
          </div>
        </main>
      </div>

      {/* CopilotKit sidebar — rendered as a floating panel */}
      <CopilotSidebar
        defaultOpen={true}
        labels={{
          title: "BMAD Assistant",
          placeholder: "Describe your project brief…",
          initial: CHAT_SUGGESTIONS,
        }}
        instructions={
          "You are the BMAD Crew assistant. " +
          "ALWAYS call kickoff_crew immediately when the user mentions any project, app, or software to build. " +
          "Pass their exact words as the input parameter. Do NOT ask clarifying questions first — just call the function. " +
          "If they mention a GitHub repo, pass it as github_repo. " +
          "After calling kickoff_crew, tell the user the pipeline has started."
        }
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Root page — wraps with CopilotKit provider
// CopilotKit 1.71+ calls new URL(runtimeUrl) which requires an absolute URL.
// Build it client-side from window.location.origin to stay cluster-portable.
// ---------------------------------------------------------------------------
export default function Page() {
  const [runtimeUrl, setRuntimeUrl] = useState<string>("");

  useEffect(() => {
    setRuntimeUrl(`${window.location.origin}/api/copilotkit`);
  }, []);

  if (!runtimeUrl) return null;

  return (
    <CopilotKit runtimeUrl={runtimeUrl}>
      <CrewApp />
    </CopilotKit>
  );
}
