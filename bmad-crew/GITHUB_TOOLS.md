# Letting the BMAD crew work on GitHub (optional)

By default the crew is **key-free and self-contained** — the agents reason and write their
delivery artifacts (PRD, architecture, stories, code, QA report) to `./output`. They do
**not** touch the outside world.

When you want the agents to *actually work on GitHub* — open issues, create branches,
commit files, open pull requests, comment on reviews — give them the **GitHub MCP
toolset**. This is the "give the crew real tools" beat from the episode.

## How it works

We use the official [GitHub MCP server](https://github.com/github/github-mcp-server)
through CrewAI's `MCPServerAdapter` (`bmad-crew/src/bmad_crew/tools.py`). The adapter turns
the MCP server's operations into first-class CrewAI tools —
`create_issue`, `create_or_update_file`, `create_branch`, `create_pull_request`,
`get_file_contents`, `add_issue_comment`, … — and hands them to the agents that produce
durable artifacts: **pm** (files the PRD/epics as issues), **architect** (commits design
docs), **sm** (opens the sliced stories as issues), and **dev** (creates branches, commits
code, opens PRs).

Every GitHub tool call is captured as a `tool <name>` span
(`gen_ai.operation.name=execute_tool`, `gen_ai.tool.name`) — see
[`observability/OBSERVABILITY.md`](../observability/OBSERVABILITY.md) §6 — so the crew's
GitHub actions show up in your traces and the *tool calls by tool / by agent* dashboard
tiles alongside the LLM spans.

## Enable it

1. Create a **fine-grained** GitHub PAT scoped to **only** the repositories the crew may
   touch, with the minimum permissions it needs — typically **Contents**, **Issues**, and
   **Pull requests: read/write**. Do not reuse an admin or broadly-scoped token.

2. Set it in your `.env` (see `.env.example`):

   ```bash
   GITHUB_PERSONAL_ACCESS_TOKEN=<your-fine-grained-pat>
   # GITHUB_MCP_MODE=remote   # default — GitHub-hosted MCP endpoint, no Docker
   ```

3. Run the crew as usual (`uv run bmad-crew`). On startup you'll see:

   ```
   [bmad-crew] GitHub tools: ON (remote) — N tool(s) available
   ```

   With **no** token set, `github_tools()` returns `[]` and the crew runs exactly as
   before — nothing to disable.

## Transports

| `GITHUB_MCP_MODE` | What runs | When to use |
|---|---|---|
| `remote` (default) | GitHub's hosted MCP endpoint `https://api.githubcopilot.com/mcp/`; PAT sent as a bearer token | Simplest — no Docker |
| `docker` | `docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN ghcr.io/github/github-mcp-server` | You want the MCP server on your own host |

Override the endpoint/image with `GITHUB_MCP_URL` / `GITHUB_MCP_IMAGE` if needed.

## Safety notes

- The tool wiring **fails safe**: any missing dependency (`crewai-tools[mcp]`), auth error,
  or transport problem degrades to an empty toolset with a warning — it never crashes a run.
- Scope the PAT tightly and rotate it if it is ever exposed. A crew agent acting on GitHub
  has exactly the permissions of the token you give it.
- Give tool-armed agents a capable local model. Small models can struggle with the
  multi-step tool-calling GitHub work requires; if the crew loops on tool calls, narrow the
  set of tool-armed agents or use a stronger `MODEL`.
