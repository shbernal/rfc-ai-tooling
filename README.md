# rfc-ai-tooling

Two ways to give an AI agent working access to the IETF RFC corpus: a **skill**
and an **MCP server**. They share one stdlib-only Python core and behave
identically.

**Use the skill.** It is a few files, needs no install step, and gives the agent
the full shell — including `ripgrep` over the corpus — instead of a fixed set of
tools. **Use the MCP server only if your client cannot run shell commands**:
claude.ai on the web, Claude Desktop, Cursor, Zed. If your client has a shell
(Claude Code, OpenClaw, Codex CLI, and most terminal agents), the skill is
strictly the better surface.

Both surfaces work with no setup, fetching RFCs on demand. Both gain full-text
search across the whole corpus if you choose to sync a local mirror.

## Install the skill

### Into one project

Use [skillbarn](https://www.npmjs.com/package/skillbarn), which vendors skills
from a committed lockfile the way `node_modules` vendors packages:

```bash
pnpm add -g skillbarn clawhub          # npm i -g works too; needs Node 22+
skb init --dir .claude/skills          # omit for OpenClaw; it defaults to .agents/skills
skb add @shbernal/rfc-lookup
```

Commit `skillbarn.json` and `skillbarn.lock`; the skill tree itself is
gitignored, and `skb install` restores exactly those bytes in a fresh clone.
The `--dir` matters: `skb` flattens to `<dir>/rfc-lookup/`, which is the layout
Claude Code can actually see — see below.

### User-wide

```bash
clawhub install @shbernal/rfc-lookup
```

That lands in `<workdir>/skills/@shbernal/rfc-lookup`, where the workdir is
`$CLAWHUB_WORKDIR` or the current directory. **OpenClaw** reads that as-is: it
finds `SKILL.md` anywhere under a skills root and takes the skill's identity
from its frontmatter, not from the path.

**Claude Code does not.** It scans `~/.claude/skills/<name>/SKILL.md` exactly
one level deep and never descends into the `@shbernal/` publisher directory
ClawHub creates, so a skill left there is silently never loaded. Point clawhub
at the right tree — `--dir` alone is not enough, since it resolves relative to
the workdir — and then flatten:

```bash
clawhub --workdir ~/.claude --dir skills install @shbernal/rfc-lookup
mv ~/.claude/skills/@shbernal/rfc-lookup ~/.claude/skills/rfc-lookup
rmdir ~/.claude/skills/@shbernal
```

Either route, that is the whole installation: the skill ships a single
stdlib-only Python script, and there is nothing to `pip install`.

## Install the MCP server

Add to your client's MCP configuration:

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

There is no repository to clone and no virtualenv to create. `uvx` fetches the
package from PyPI on first run.

## What it does

- **Search** RFCs by title, or by full document text once a mirror is synced.
- **List sections** of an RFC with line numbers, so the agent can read the one
  section it needs instead of pulling a 500 KB document into context.
- **Fetch** a section, or a line range, with page headers and footers stripped.
- **Flag obsolescence on every result.** An RFC that has been superseded says so
  in a header the model cannot miss:

  ```
  RFC 2616 — Hypertext Transfer Protocol -- HTTP/1.1  [DRAFT STANDARD]
  !! OBSOLETED BY: RFC 7230, 7231, 7232, 7233, 7234, 7235
  ```

  This is the main reason to use either surface rather than letting the model
  fetch `rfc-editor.org` itself. Agents cite dead specifications confidently;
  RFC 2616 has been obsolete since 2014 and is still the first thing most models
  reach for on HTTP semantics.

## Optional: full-text mode

By default, RFCs are fetched over HTTPS as needed and cached. Searching is
limited to titles, which is enough to find a document you can already name.

Syncing a local mirror adds full-text search across all 9,812 RFCs. Neither
surface puts an `rfc` command on your `PATH`, so run the script where it landed:

```bash
# skill — <skills-dir> is .claude/skills, ~/.claude/skills, .agents/skills, …
python3 <skills-dir>/rfc-lookup/scripts/rfc.py sync

# MCP server
uvx --from mcp-server-rfc python -m mcp_server_rfc.rfc sync
```

Both write to the same place, so one sync serves both surfaces.

| | |
|---|---|
| Disk | 512 MB (text only — no XML, HTML, PDF or JSON) |
| Time | roughly 5 minutes on a fast connection |
| Source | the RFC Editor's public rsync mirror |

This is optional, and it is never triggered automatically — not on install, not
on first use, not by an agent. It transfers half a gigabyte from a
volunteer-operated mirror, so it stays a deliberate human action at a shell. The
sync is bandwidth-limited by default; pass `--bwlimit` to change it.

No RFC text is bundled in either the skill or the PyPI package. The corpus is
always fetched from the RFC Editor.

## Why this exists

This replaces [`mcp-server-ietf`](https://github.com/tizee/mcp-server-ietf),
which is unmaintained. Its problems, and what is different here:

- **RFCs below 1000 were invisible.** Its index parser assumed zero-padded
  numbers, but the RFC index is not padded. 999 of the 10,004 index entries never
  matched — including RFC 791 (IP), 793 (TCP), 768 (UDP) and 959 (FTP). Because
  document fetches were gated on the index, those RFCs could not be retrieved at
  all.
- **Titles were truncated at the first period.** RFC 2616 came back as
  "Hypertext Transfer Protocol -- HTTP/1", and any title containing a version
  number, abbreviation or hostname was silently corrupted.
- **The index was downloaded once and never refreshed**, so a newly published RFC
  was reported as nonexistent even though its URL fetched fine.
- **Search covered titles only**, as a case-insensitive substring match.
- **Every returned document chunk was written to a log file** at default DEBUG
  level, forever. A local checkout had accumulated 3.8 MB of log against 1.1 MB
  of actual RFCs.
- **Installation required cloning the repository.** This one installs with a
  one-line client config.
- **There was no obsolescence signal**, which is the single most valuable field
  in the index for an agent.

## Development

```
core/     the stdlib-only implementation and its tests
skill/    SKILL.md and a vendored copy of the core
mcp/      the PyPI package (mcp-server-rfc), thin adapter over the core
```

`core/rfc.py` is the only real implementation. The skill and the MCP server each
carry a byte-identical vendored copy, kept honest by CI and regenerated with
`make sync-core`. Never edit a vendored copy.

The core depends on nothing outside the Python standard library, which is what
lets the skill be self-contained and keeps the MCP server's only dependency the
`mcp` SDK. Python 3.10 or newer.

```bash
make sync-core   # copy core/rfc.py into both surfaces
make test        # pytest, no network
make lint        # ruff check + format --check
make smoke       # stdio JSON-RPC session against the published PyPI server
```

## License

MIT. See [`LICENSE`](LICENSE), and [`NOTICE`](NOTICE) for attribution and for
the terms that apply to RFC documents themselves.
