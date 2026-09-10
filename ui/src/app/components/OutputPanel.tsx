"use client";

/**
 * OutputPanel — displays the final QA report from the crew run.
 *
 * Renders the markdown output from the QA agent (Quinn) using react-markdown.
 * Shows a placeholder when no result is available yet.
 */

import ReactMarkdown from "react-markdown";

interface OutputPanelProps {
  result: string | null;
  error: string | null;
}

export default function OutputPanel({ result, error }: OutputPanelProps) {
  if (error) {
    return (
      <div className="p-4 rounded-lg border border-red-800/50 bg-red-950/20">
        <h3 className="text-sm font-semibold text-red-400 mb-2">Crew error</h3>
        <pre className="text-xs text-red-300 whitespace-pre-wrap font-mono">{error}</pre>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-3 p-8">
        <span className="text-4xl">📄</span>
        <p className="text-sm text-center">
          The QA report will appear here once the crew finishes.
        </p>
      </div>
    );
  }

  return (
    <div className="p-4 overflow-y-auto">
      <div className="flex items-center gap-2 mb-4">
        <span className="text-emerald-400">✓</span>
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
          QA Report
        </h2>
      </div>
      <div className="prose prose-invert prose-sm max-w-none prose-headings:text-slate-200 prose-p:text-slate-300 prose-code:text-indigo-300 prose-pre:bg-slate-800 prose-pre:border prose-pre:border-slate-700">
        <ReactMarkdown>{result}</ReactMarkdown>
      </div>
    </div>
  );
}
