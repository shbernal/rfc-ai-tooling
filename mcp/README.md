# mcp-server-rfc

An MCP server for looking up IETF RFCs.

```json
{
  "mcpServers": {
    "rfc": {
      "command": "uvx",
      "args": ["mcp-server-rfc"]
    }
  }
}
```

No clone, no virtualenv, no path. That is the whole installation.

## Tools

| Tool | What it does |
|---|---|
| `search_rfcs` | Search titles, or the full text of every RFC if a mirror has been synced |
| `list_sections` | An RFC's headings with line numbers — the cheap first call |
| `get_rfc` | Read one section, or a line range |

Every response carries a banner with the RFC's status and, when it applies, a
warning that it has been superseded:

```
RFC 2616 — Hypertext Transfer Protocol -- HTTP/1.1  [DRAFT STANDARD]
!! OBSOLETED BY: RFC 7230, 7231, 7232, 7233, 7234, 7235
```

That warning is the reason to use this rather than let a model fetch
`rfc-editor.org` itself. Models cite dead specifications with great confidence.

## Full-text search

Works with no setup, fetching documents on demand. Full-text search additionally
requires a local mirror, which the user creates from a shell:

```bash
uvx --from mcp-server-rfc python -m mcp_server_rfc.rfc sync
```

512 MB, a few minutes, entirely optional. The server deliberately does not
expose a sync tool: half a gigabyte pulled from a volunteer-run mirror should be
a person's decision, not a model's.

If a mirror already exists — synced for the companion skill, say — this server
picks it up automatically. Set `$RFC_MIRROR` to point at a non-default location.

## If your client has a shell

Use the skill instead. It does the same things with fewer moving parts and gives
the agent ripgrep over the corpus:

```bash
clawhub install @shbernal/rfc-lookup
```

This server exists for clients that cannot run shell commands — claude.ai on the
web, Claude Desktop, Cursor, Zed.

Source, issues and the skill: https://github.com/shbernal/rfc-ai-tooling

MIT.
