/**
 * CopilotKit runtime backend route — LLM adapter only.
 *
 * Architecture:
 *   Browser (page.tsx)
 *     └─ useCopilotAction("kickoff_crew")   ← registers action CLIENT-SIDE
 *          │  CopilotKit protocol sends the action catalog to this route
 *          │  so the AI knows about kickoff_crew and can call it.
 *          │  When the AI decides to call it, CopilotKit routes execution
 *          │  BACK to the browser handler — NOT here.
 *          ↓
 *   This route (route.ts)
 *     └─ CopilotRuntime (no actions — avoids double-firing)
 *          └─ LLM adapter (Ollama / OpenAI / Anthropic)
 *               └─ powers the chat sidebar + interprets user messages
 *
 * The kickoff_crew action lives exclusively in page.tsx via useCopilotAction.
 * That handler calls the FastAPI /kickoff/async endpoint from the browser and
 * updates React state (runId) for the AgentTimeline SSE subscription.
 * Defining it here too would cause the action to fire twice (two crew runs).
 *
 * Env vars (server-side only — not exposed to the browser):
 *   COPILOTKIT_ADAPTER   ollama | openai | anthropic  (default: ollama)
 *   OLLAMA_BASE_URL      http://localhost:11434
 *   OLLAMA_MODEL         qwen3.6
 *   OPENAI_API_KEY       sk-...
 *   ANTHROPIC_API_KEY    sk-ant-...
 */

import {
  CopilotRuntime,
  OpenAIAdapter,
  AnthropicAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import OpenAI from "openai";

// ---------------------------------------------------------------------------
// LLM adapter — powers the chat sidebar
// ---------------------------------------------------------------------------
function buildAdapter() {
  const adapter = (process.env.COPILOTKIT_ADAPTER || "ollama").toLowerCase();

  if (adapter === "anthropic") {
    return new AnthropicAdapter(); // reads ANTHROPIC_API_KEY automatically
  }

  if (adapter === "openai") {
    return new OpenAIAdapter(); // reads OPENAI_API_KEY automatically
  }

  // Default: Ollama via its OpenAI-compatible API (no key required)
  const ollamaClient = new OpenAI({
    baseURL: `${process.env.OLLAMA_BASE_URL || "http://localhost:11434"}/v1`,
    apiKey: "ollama", // Ollama ignores the key; required by the OpenAI SDK
  });
  return new OpenAIAdapter({
    openai: ollamaClient,
    model: process.env.OLLAMA_MODEL || "qwen3.6",
  });
}

// ---------------------------------------------------------------------------
// Runtime — no server-side actions; kickoff_crew is client-side (page.tsx)
// ---------------------------------------------------------------------------
const runtime = new CopilotRuntime({
  actions: [],
});

// ---------------------------------------------------------------------------
// Next.js App Router POST handler
// In @copilotkit/runtime >=1.9 the endpoint helper returns { handleRequest }
// rather than { POST } — re-export under the Next.js convention.
// ---------------------------------------------------------------------------
const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
  runtime,
  serviceAdapter: buildAdapter(),
  endpoint: "/api/copilotkit",
});
export const POST = handleRequest;
