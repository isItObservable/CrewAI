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

import os
from typing import Any, List


def _normalize_json_schema(schema: Any) -> Any:
    """Recursively convert union type arrays to 'string'.

    GitHub's MCP server uses JSON Schema union types like ``{"type": ["string", "number",
    "boolean"]}`` which is valid JSON Schema but crewai's ``create_model_from_schema``
    only handles scalar type strings.  Coercing to ``"string"`` is lossy but safe: the
    LLM passes string values and the GitHub API coerces them on its side.
    """
    if isinstance(schema, list):
        return [_normalize_json_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, list):
            result[key] = "string"
        else:
            result[key] = _normalize_json_schema(value)
    return result


def _patch_create_model_from_schema() -> None:
    """Monkey-patch crewai's schema→Pydantic converter to tolerate union type arrays.

    Called once at module load time; idempotent (guarded by _PATCHED flag).
    """
    try:
        import crewai.utilities.pydantic_schema_utils as _m

        if getattr(_m, "_union_type_patch_applied", False):
            return
        _orig = _m.create_model_from_schema

        def _patched(json_schema: Any, **kwargs: Any) -> Any:
            return _orig(_normalize_json_schema(json_schema), **kwargs)

        _m.create_model_from_schema = _patched
        _m._union_type_patch_applied = True  # type: ignore[attr-defined]
    except Exception:
        pass  # if crewai internals change, degrade gracefully


_patch_create_model_from_schema()

# Started adapters are kept referenced for the lifetime of the process so their MCP
# connection is not garbage-collected (and closed) while a crew run is still in flight.
_ADAPTERS: list = []


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
        print(f"[bmad-crew] GitHub tools: ON ({mode}) — {len(tools)} tool(s) available")
        return tools
    except Exception as exc:  # network, auth, transport, version drift — never fatal
        print(f"[bmad-crew] GitHub tools disabled — could not start MCP server ({exc})")
        return []
