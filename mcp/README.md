# mcp-server-rfc

An MCP server for looking up IETF RFCs.

<!-- mcp-name: io.github.shbernal/rfc-ai-tooling -->

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

A client showing the server as connected has not necessarily used it, and a
model will happily answer an RFC question from memory instead. On Claude Desktop
the per-server log records only the handshake, so it cannot tell you either way
— [docs/desktop-verification.md][verify] says where the evidence actually is.

[verify]: https://github.com/shbernal/rfc-ai-tooling/blob/main/docs/desktop-verification.md

## Tools

| Tool | What it does |
|---|---|
| `search_rfcs` | Search titles, or the full text of every RFC, ranked by section, if the section index is present |
| `list_sections` | An RFC's headings with line numbers — the cheap first call |
| `get_rfc` | Read one section, or a line range |

With the section index, a full-text query is words, and each result is one
section ranked by BM25, carrying the section number to pass to `get_rfc` and the
line that best matches. Without it, full-text search falls back to `rg` or
`grep` over a synced mirror, where the query is a literal string and results are
whole RFCs; `regex=true` opts into pattern matching there and in titles. The
payload names the backend in `tool`. Title results put current RFCs before
superseded ones, so a page cut short at `limit` keeps the document you want
rather than the one it replaced.

`get_rfc` refuses any read of more than 1500 lines that is not a named section,
answering with its size and a pointer to `list_sections` rather than filling the
context with a specification the model had one question about; a `start_line` of
1 does not get around it. `full=true` overrides it. A section you asked for by
name is never refused: `list_sections` reports how long
each one is, and `max_lines` caps any read, so the choice is informed rather
than blocked.

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
needs the section index, which the user downloads from a shell:

```bash
uvx mcp-server-rfc sync --index
```

About 270 MB from this project's GitHub releases, checked against its published
SHA-256. It ranks sections by BM25 and serves every read from disk, so the
server stops fetching from the RFC Editor. `uvx mcp-server-rfc sync` instead
copies the corpus as 512 MB of text files from the RFC Editor's volunteer-run
rsync mirror, which is what `rg` and `regex=true` search.

The same command that runs the server runs its CLI: `sync` downloads, `status`
reports what is present, and `uvx mcp-server-rfc <command> --help` covers the
rest. It is also the command the server names in the error you get when
full-text search is asked for without either.

Both are optional. The server deliberately does not expose a sync tool: hundreds
of megabytes on someone's disk should be a person's decision, not a model's.

If an index or a mirror already exists — synced for the companion skill, say — this server
picks it up automatically. It looks under the platform's data directory:
`$XDG_DATA_HOME/rfc-ai-tooling`, or `%LOCALAPPDATA%\rfc-ai-tooling` on Windows,
falling back to `~/.local/share/rfc-ai-tooling`. Set `$RFC_MIRROR` to point at a
non-default location — in a container with no home directory, that or `--mirror`
is what to pass.

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

Full-text search works hosted only where the section index is on the
server's disk (`sync --index` there). Without it, a hosted instance returns an
error saying so instead of silently answering a title search. The obsolescence
banner, section reads and the unscoped-read guard work either way, because they
need only the 2 MB RFC index.

## If your client has a shell

Use the skill instead — Claude Code, Codex CLI, OpenClaw, Cursor and Zed all
qualify. It does the same things with fewer moving parts and gives the agent
ripgrep over the corpus:

```bash
npx skills add shbernal/rfc-ai-tooling      # from the repo, into .claude/skills/
clawhub install @shbernal/rfc-lookup        # or the last released version
```

This server is for clients that give the model no shell of its own. Claude
Desktop is the clearest case: its chat cannot run a command on your machine, but
it will spawn this server there.

Source, issues and the skill: https://github.com/shbernal/rfc-ai-tooling

MIT.
