"""Optional GitHub tooling for the BMAD crew.

By default the crew is key-free and self-contained: the agents reason and write their
delivery artifacts to ``./output``. When you want them to *actually work on GitHub* —
open issues, create branches, commit files, open pull requests, comment on reviews —
give them the GitHub MCP toolset.

We use the official **GitHub MCP server** (https://github.com/github/github-mcp-server)
through CrewAI's :class:`~crewai_tools.MCPServerAdapter`. That exposes first-class GitHub
tools to the agents (``create_issue``, ``create_or_update_file``, ``create_branch``,
``create_pull_request``, ``get_file_contents``, ``add_issue_comment`` …). Each tool call
is captured as a ``tool <name>`` span by the observability layer — see
``observability/OBSERVABILITY.md`` §6 (``gen_ai.operation.name=execute_tool``,
``gen_ai.tool.name``), so the crew's GitHub actions are observable end-to-end.

Enable it by exporting a **GitHub PAT** in ``GITHUB_PERSONAL_ACCESS_TOKEN`` — a
fine-grained token scoped to *only* the repositories the crew may touch, with the minimum
permissions it needs (typically Contents, Issues and Pull requests: read/write). With no
token set, :func:`github_tools` returns ``[]`` and the crew runs exactly as before.

Two transports are supported via ``GITHUB_MCP_MODE``:

* ``remote`` (default) — GitHub's hosted MCP endpoint (``https://api.githubcopilot.com/mcp/``).
  No Docker required; the PAT is sent as a bearer token.
* ``docker`` — run the server locally:
  ``docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN ghcr.io/github/github-mcp-server``.
  Use this when you want the MCP server on your own host.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, List

# Started adapters are kept referenced for the lifetime of the process so their MCP
# connection is not garbage-collected (and closed) while a crew run is still in flight.
_ADAPTERS: list = []

# Cap tool input/output recorded on spans so a huge file body can't blow up the trace.
_TOOL_IO_MAX = int(os.getenv("BMAD_TOOL_IO_MAX", "4000"))


def _truncate(value: Any) -> str:
    s = value if isinstance(value, str) else json.dumps(value, default=str)
    return s if len(s) <= _TOOL_IO_MAX else s[:_TOOL_IO_MAX] + "…[truncated]"


def _emit_tool_span(tracer, name: str, args: tuple, kwargs: dict, call):
    """Run ``call`` inside an ``execute_tool`` span carrying the gen_ai.tool.* attrs.

    ISI-6357 D2 — GitHub-MCP tool calls (``create_repository``, ``create_or_update_file``,
    …) come through CrewAI's :class:`MCPServerAdapter`, which OpenLIT's CrewAI instrumentor
    does *not* wrap — so without this they produce **no spans at all** and tool-trajectory
    scoring has nothing to match. We emit one span per call with the attributes the eval
    pipeline and the collector's ``transform/genai-normalize`` both key off:

    * ``gen_ai.operation.name = execute_tool`` / ``gen_ai.tool.name`` / ``gen_ai.tool.call.id``
    * ``gen_ai.tool.call.arguments`` **and** ``gen_ai.tool.args`` (spec name + OpenLIT name;
      the agentevals gate accepts either)
    * ``traceloop.span.kind = tool`` + ``traceloop.entity.name`` — the gateway already maps
      these to ``gen_ai.tool.name``, so the span is scoreable even if the gen_ai.* keys drift.
    """
    from opentelemetry.trace import SpanKind, Status, StatusCode

    # CrewAI tools are called positionally or by keyword; record whatever was passed.
    arg_payload: Any = kwargs if kwargs else (args[0] if len(args) == 1 else list(args))
    args_json = _truncate(arg_payload)
    call_id = uuid.uuid4().hex

    with tracer.start_as_current_span(f"execute_tool {name}", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", name)
        span.set_attribute("gen_ai.tool.call.id", call_id)
        span.set_attribute("gen_ai.tool.call.arguments", args_json)
        span.set_attribute("gen_ai.tool.args", args_json)
        # traceloop fallback — the collector maps kind==tool + entity.name -> gen_ai.tool.name.
        span.set_attribute("traceloop.span.kind", "tool")
        span.set_attribute("traceloop.entity.name", name)
        span.set_attribute("traceloop.entity.input", args_json)
        try:
            result = call(*args, **kwargs)
        except Exception as exc:  # record then re-raise so CrewAI's own handling is unchanged
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        span.set_attribute("traceloop.entity.output", _truncate(result))
        span.set_status(Status(StatusCode.OK))
        return result


def _instrument_tool(tool: Any) -> Any:
    """Wrap a CrewAI/MCP tool's run callable so every invocation emits a tool span.

    Degrades to a no-op for any tool we cannot wrap (unknown shape, pydantic lockdown):
    the tool still works, it just stays uninstrumented rather than breaking the run.
    """
    try:
        from opentelemetry import trace
    except Exception:
        return tool  # OTel not present — nothing to attach spans to.

    tracer = trace.get_tracer("bmad_crew.tools")
    name = getattr(tool, "name", None) or getattr(tool, "__name__", None) or tool.__class__.__name__

    # Prefer the private _run (what CrewAI's BaseTool.run dispatches to); fall back to
    # the public run, then a bare func. Whichever we find, close over the *bound* original.
    for attr in ("_run", "run", "func"):
        original = getattr(tool, attr, None)
        if not callable(original):
            continue

        def wrapped(*args, _orig=original, _name=name, **kwargs):
            return _emit_tool_span(tracer, _name, args, kwargs, _orig)

        try:
            # object.__setattr__ bypasses pydantic v2's field validation; the wrapper lands
            # in the instance __dict__ and shadows the class method for this instance only.
            object.__setattr__(tool, attr, wrapped)
            print(f"[bmad-crew] tool instrumented for spans: {name} (.{attr})")
            return tool
        except Exception as exc:
            print(f"[bmad-crew] could not instrument tool {name}.{attr} ({exc})")
            # try the next candidate attribute
            continue
    return tool


def github_tools() -> List:
    """Return the GitHub MCP tools for the crew, or ``[]`` when GitHub is not configured.

    Never raises: any missing dependency or connection problem degrades to an empty
    toolset with a printed warning, so the default key-free run is always safe.
    """
    token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "").strip()
    if not token:
        return []

    try:
        from crewai_tools import MCPServerAdapter
    except Exception as exc:  # the 'mcp' extra of crewai-tools is not installed
        print(f"[bmad-crew] GitHub tools disabled — install 'crewai-tools[mcp]' ({exc})")
        return []

    mode = os.getenv("GITHUB_MCP_MODE", "remote").strip().lower()
    try:
        if mode == "docker":
            from mcp import StdioServerParameters

            server = StdioServerParameters(
                command="docker",
                args=[
                    "run", "-i", "--rm",
                    "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
                    os.getenv("GITHUB_MCP_IMAGE", "ghcr.io/github/github-mcp-server"),
                ],
                # Pass the PAT through to the container without printing it.
                env={**os.environ, "GITHUB_PERSONAL_ACCESS_TOKEN": token},
            )
        else:
            server = {
                "url": os.getenv("GITHUB_MCP_URL", "https://api.githubcopilot.com/mcp/"),
                "transport": "streamable-http",
                "headers": {"Authorization": f"Bearer {token}"},
            }

        adapter = MCPServerAdapter(server)
        # Some crewai-tools versions connect lazily; start explicitly when supported.
        if hasattr(adapter, "start"):
            try:
                adapter.start()
            except Exception:
                pass
        tools = list(getattr(adapter, "tools", []) or [])
        _ADAPTERS.append(adapter)  # keep the connection alive for the whole run
        # ISI-6357 D2: MCPServerAdapter tools are invisible to OpenLIT's CrewAI
        # instrumentor, so wrap each one to emit a gen_ai.tool.* span per call.
        tools = [_instrument_tool(t) for t in tools]
        print(f"[bmad-crew] GitHub tools: ON ({mode}) — {len(tools)} tool(s) available")
        return tools
    except Exception as exc:  # network, auth, transport, version drift — never fatal
        print(f"[bmad-crew] GitHub tools disabled — could not start MCP server ({exc})")
        return []
