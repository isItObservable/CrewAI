"use client";

/**
 * AgentTimeline — real-time BMAD crew progress visualisation.
 *
 * Connects to GET /stream/{run_id} (SSE) on the bmad-crew FastAPI backend
 * and renders each agent's status as it transitions:
 *   idle → active → done (or error)
 *
 * The component is completely driven by the SSE stream — no polling, no
 * client-side timers.  When the parent passes a new run_id the previous
 * EventSource is closed and a fresh subscription is opened.
 */

import { useEffect, useRef, useState } from "react";

// The 8 BMAD personas in pipeline order.
const AGENTS: { key: string; name: string; role: string; emoji: string }[] = [
  { key: "analyst",   name: "Mary",    role: "Business Analyst",  emoji: "🔍" },
  { key: "pm",        name: "John",    role: "Product Manager",   emoji: "📋" },
  { key: "ux",        name: "Sally",   role: "UX Designer",       emoji: "🎨" },
  { key: "po",        name: "Sarah",   role: "Product Owner",     emoji: "✅" },
  { key: "architect", name: "Winston", role: "Solution Architect", emoji: "🏗️" },
  { key: "sm",        name: "Bob",     role: "Scrum Master",      emoji: "📌" },
  { key: "dev",       name: "Amelia",  role: "Senior Engineer",   emoji: "💻" },
  { key: "qa",        name: "Quinn",   role: "QA Architect",      emoji: "🧪" },
];

type AgentStatus = "idle" | "active" | "done" | "error";

interface AgentState {
  status: AgentStatus;
  startedAt?: number;
  durationMs?: number;
}

interface AgentTimelineProps {
  runId: string | null;
  crewUrl: string;
  onDone: (result: string) => void;
  onError: (message: string) => void;
}

function statusColor(status: AgentStatus): string {
  switch (status) {
    case "active": return "bg-indigo-500";
    case "done":   return "bg-emerald-500";
    case "error":  return "bg-red-500";
    default:       return "bg-slate-600";
  }
}

function statusLabel(status: AgentStatus): string {
  switch (status) {
    case "active": return "Running...";
    case "done":   return "Done";
    case "error":  return "Error";
    default:       return "Waiting";
  }
}

export default function AgentTimeline({
  runId,
  crewUrl,
  onDone,
  onError,
}: AgentTimelineProps) {
  const [agents, setAgents] = useState<Record<string, AgentState>>(() =>
    Object.fromEntries(AGENTS.map((a) => [a.key, { status: "idle" }]))
  );
  const [crewStarted, setCrewStarted] = useState(false);
  const [crewDone, setCrewDone] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  // Map a raw agent role string (may be verbose like "Senior Engineer (Amelia)")
  // to one of our known agent keys.
  function resolveAgentKey(role: string): string | null {
    const lower = role.toLowerCase();
    for (const a of AGENTS) {
      if (
        lower.includes(a.key) ||
        lower.includes(a.name.toLowerCase()) ||
        lower.includes(a.role.toLowerCase().split(" ")[0])
      ) {
        return a.key;
      }
    }
    return null;
  }

  useEffect(() => {
    // Close any existing stream.
    esRef.current?.close();
    esRef.current = null;

    if (!runId) return;

    // Reset state for the new run.
    setAgents(Object.fromEntries(AGENTS.map((a) => [a.key, { status: "idle" }])));
    setCrewStarted(false);
    setCrewDone(false);

    const url = `${crewUrl}/stream/${runId}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onmessage = (evt) => {
      let event: { type: string; agent?: string; result?: string; message?: string };
      try {
        event = JSON.parse(evt.data);
      } catch {
        return;
      }

      switch (event.type) {
        case "crew_start":
          setCrewStarted(true);
          break;

        case "agent_start": {
          const key = resolveAgentKey(event.agent || "");
          if (key) {
            setAgents((prev) => ({
              ...prev,
              [key]: { status: "active", startedAt: Date.now() },
            }));
          }
          break;
        }

        case "agent_done": {
          const key = resolveAgentKey(event.agent || "");
          if (key) {
            setAgents((prev) => {
              const started = prev[key]?.startedAt;
              return {
                ...prev,
                [key]: {
                  status: "done",
                  startedAt: started,
                  durationMs: started ? Date.now() - started : undefined,
                },
              };
            });
          }
          break;
        }

        case "done":
          setCrewDone(true);
          es.close();
          onDone(event.result || "");
          break;

        case "error":
          es.close();
          onError(event.message || "Unknown error");
          break;

        // "ping" and "task_start/done" — ignore for now
        default:
          break;
      }
    };

    es.onerror = () => {
      // EventSource will auto-reconnect on transient errors; only close on done/error.
    };

    return () => {
      es.close();
    };
  }, [runId, crewUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!runId) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-3">
        <span className="text-4xl">🤖</span>
        <p className="text-sm">
          Start a crew run via the chat to see agent progress here.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
          Agent Timeline
        </h2>
        <span className="text-xs text-slate-500 font-mono truncate max-w-[140px]">
          {runId.slice(0, 8)}…
        </span>
      </div>

      {/* Crew status banner */}
      {crewStarted && !crewDone && (
        <div className="text-xs text-indigo-400 flex items-center gap-2 mb-1">
          <span className="inline-block w-2 h-2 rounded-full bg-indigo-500 animate-ping" />
          Pipeline running
        </div>
      )}
      {crewDone && (
        <div className="text-xs text-emerald-400 flex items-center gap-2 mb-1">
          <span className="inline-block w-2 h-2 rounded-full bg-emerald-500" />
          Pipeline complete
        </div>
      )}

      {/* Agent cards */}
      {AGENTS.map((agent, idx) => {
        const state = agents[agent.key];
        const isActive = state.status === "active";
        return (
          <div
            key={agent.key}
            className={`
              flex items-center gap-3 rounded-lg px-3 py-2.5 border transition-all duration-300
              ${isActive
                ? "border-indigo-500/60 bg-indigo-950/40 agent-active"
                : state.status === "done"
                ? "border-emerald-800/50 bg-emerald-950/20"
                : state.status === "error"
                ? "border-red-800/50 bg-red-950/20"
                : "border-slate-700/50 bg-slate-800/30"
              }
            `}
          >
            {/* Step number */}
            <span className="text-xs text-slate-500 w-4 shrink-0">{idx + 1}</span>

            {/* Status dot */}
            <span
              className={`
                w-2.5 h-2.5 rounded-full shrink-0 transition-colors duration-300
                ${statusColor(state.status)}
                ${isActive ? "animate-pulse" : ""}
              `}
            />

            {/* Emoji */}
            <span className="text-base shrink-0">{agent.emoji}</span>

            {/* Name + role */}
            <div className="flex flex-col min-w-0">
              <span className="text-sm font-medium text-slate-200 leading-tight">
                {agent.name}
              </span>
              <span className="text-xs text-slate-500 leading-tight">{agent.role}</span>
            </div>

            {/* Status label + duration */}
            <div className="ml-auto flex flex-col items-end shrink-0">
              <span
                className={`text-xs font-medium ${
                  isActive ? "text-indigo-400"
                  : state.status === "done" ? "text-emerald-400"
                  : state.status === "error" ? "text-red-400"
                  : "text-slate-600"
                }`}
              >
                {statusLabel(state.status)}
              </span>
              {state.durationMs !== undefined && (
                <span className="text-xs text-slate-600">
                  {(state.durationMs / 1000).toFixed(1)}s
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
