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

No clone, no virtualenv, no path. That is the whole installation. Your client
spawns the server on your machine and talks to it over stdin and stdout.

## Tools

| Tool | What it does |
|---|---|
| `search_rfcs` | Search titles, or the full text of every RFC if a mirror has been synced |
| `list_sections` | An RFC's headings with line numbers — the cheap first call |
| `get_rfc` | Read one section, or a line range |

`get_rfc` refuses an unscoped read of an RFC over 1500 lines, answering with its
size and a pointer to `list_sections` rather than filling the context with a
specification the model had one question about. `full=true` overrides it.

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
uvx mcp-server-rfc sync
```

The same command that runs the server runs its CLI: `sync` downloads the
corpus, `status` reports what is present, and `uvx mcp-server-rfc <command>
--help` covers the rest. It is also the command the server names in the error
you get when full-text search is asked for without a mirror.

512 MB, a few minutes, entirely optional. The server deliberately does not
expose a sync tool: half a gigabyte pulled from a volunteer-run mirror should be
a person's decision, not a model's.

If a mirror already exists — synced for the companion skill, say — this server
picks it up automatically. Set `$RFC_MIRROR` to point at a non-default location.

## HTTP mode

The config above is the stdio transport, which needs a client that can spawn a
process on your machine. A session running in the cloud — claude.ai on the web,
Cowork — cannot, and no configuration fixes that. For those, the server has to
be deployed somewhere they can reach:

```bash
mcp-server-rfc --transport http --host 0.0.0.0 --port 8080
```

`RFC_TRANSPORT`, `HOST` and `PORT` are read from the environment too. The
repository carries a `Dockerfile` and a `fly.toml` that do this. **No public
instance of this server exists and none is planned** — if you want one, you host
it, and you should put authentication in front of it, since the server has none
and would otherwise be an open proxy to a volunteer-run mirror.

Full-text search is the one thing that does not survive: it reads a local 512 MB
corpus, so a hosted instance returns an error saying so instead of silently
answering a title search. The obsolescence banner, section reads and the
unscoped-read guard all work, because they need only the 2 MB index.

## If your client has a shell

Use the skill instead — Claude Code, Codex CLI, OpenClaw, Cursor and Zed all
qualify. It does the same things with fewer moving parts and gives the agent
ripgrep over the corpus:

```bash
clawhub install @shbernal/rfc-lookup
```

This server is for clients that give the model no shell of its own. Claude
Desktop is the clearest case: its chat cannot run a command on your machine, but
it will spawn this server there.

Source, issues and the skill: https://github.com/shbernal/rfc-ai-tooling

MIT.
