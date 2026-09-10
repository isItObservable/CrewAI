/**
 * Catch-all proxy for /api/crew/* → FastAPI backend.
 *
 * Reads BMAD_CREW_URL at **request time** (server-side env var) so the same
 * image works in any cluster without rebuilding.
 *
 * Handles both regular JSON requests and SSE streaming (for /stream/{run_id}).
 */

import { NextRequest } from "next/server";

const BACKEND = process.env.BMAD_CREW_URL || "http://localhost:8000";

// Hop-by-hop headers that must not be forwarded.
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
]);

async function proxy(req: NextRequest, path: string[]) {
  const upstream = `${BACKEND}/${path.join("/")}${req.nextUrl.search}`;

  // Forward all safe headers from the incoming request.
  const forwardHeaders = new Headers();
  req.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) {
      forwardHeaders.set(key, value);
    }
  });

  const body =
    req.method !== "GET" && req.method !== "HEAD"
      ? await req.arrayBuffer()
      : undefined;

  const upstreamResp = await fetch(upstream, {
    method: req.method,
    headers: forwardHeaders,
    body: body ? body : undefined,
    // @ts-expect-error — Node.js fetch supports duplex for streaming
    duplex: "half",
  });

  // Build response headers — pass everything useful back.
  const respHeaders = new Headers();
  upstreamResp.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) {
      respHeaders.set(key, value);
    }
  });

  return new Response(upstreamResp.body, {
    status: upstreamResp.status,
    headers: respHeaders,
  });
}

export async function GET(
  req: NextRequest,
  { params }: { params: { path: string[] } }
) {
  return proxy(req, params.path);
}

export async function POST(
  req: NextRequest,
  { params }: { params: { path: string[] } }
) {
  return proxy(req, params.path);
}

export async function PUT(
  req: NextRequest,
  { params }: { params: { path: string[] } }
) {
  return proxy(req, params.path);
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: { path: string[] } }
) {
  return proxy(req, params.path);
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: { path: string[] } }
) {
  return proxy(req, params.path);
}
