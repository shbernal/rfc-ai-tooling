# Changelog

Both surfaces — the `rfc-lookup` skill and the `mcp-server-rfc` package — are
versioned together from `core/rfc.py`, so one entry covers both unless it says
otherwise.

Breaking changes are removals, not deprecations: the old behaviour goes, the
version bumps, and this file is where the change is recorded. Nothing in the
code announces that something used to work differently.

## 0.2.0 — unreleased

### Added

- **An HTTP transport, for clients that cannot spawn a local process.**
  `mcp-server-rfc --transport http` serves Streamable HTTP instead of stdio;
  `RFC_TRANSPORT`, `HOST` and `PORT` configure the same thing from the
  environment. Sessions are stateless, so an instance can scale to zero and
  back. stdio remains the default and is unchanged — no existing client
  configuration needs to move.

  This exists because a session running in Anthropic's cloud — claude.ai on the
  web, Cowork — has no route to a process on your machine, so the stdio server
  could never reach it. **No public instance is hosted and none is planned**; a
  `Dockerfile` and a `fly.toml` ship in `mcp/` so that anyone who wants one can
  deploy it themselves. The server has no authentication, which is a deliberate
  omission for a local stdio process and a hazard for a public URL.

  Full-text search is unavailable over HTTP unless the host has synced a mirror,
  and says so rather than falling back to a title search. Everything else
  behaves identically: the index it needs is 2 MB and is fetched on demand.

- **`mcp-server-rfc` is now the CLI as well as the server.** A subcommand runs
  the CLI, so `uvx mcp-server-rfc sync` downloads the corpus and `uvx
  mcp-server-rfc status` reports what is present; with no subcommand, or with
  only transport flags, it serves MCP exactly as before. Every command `rfc.py`
  offers is reachable this way, and `uvx mcp-server-rfc <command> --help`
  documents them.

### Breaking

- **Reading a whole RFC over 1500 lines is now an error rather than a dump.**
  `get <n>` with no `--section` and no `--lines`, and `get_rfc` with no
  `section`, `start_line` or `max_lines`, answer with the document's length and
  where to find its section list. Explicitly scoped reads are untouched. Pass
  `--full` (CLI) or `full=true` (MCP) for the previous behaviour. The advice to
  read one section predates this, in both the skill and the tool descriptions;
  advice is the half of a guardrail that fails when it is skipped, and a single
  unscoped `get 9110` costs 10,786 lines of context.

### Fixed

- **Error messages now name a command that exists where they are read.** Six of
  them said to run `rfc sync` or `rfc status`, but no `rfc` executable is
  installed by either surface. The instruction failed as typed at exactly the
  moment it mattered most — the `--fulltext` refusal on an unsynced machine,
  which is the first wall an agent hits. The skill now says `python3
  scripts/rfc.py`, derived from how it was invoked, which also fixes `--help`'s
  usage line; the MCP server says `uvx mcp-server-rfc`, because `uvx` is how it
  is installed and it resolves the package into a throwaway environment that
  leaves neither a console script nor an importable module on the user's PATH.
  A module form (`python3 -m mcp_server_rfc.rfc`) would have been just as
  unrunnable there, and nothing observable from inside the process tells the two
  installs apart.

### Skill

- Opens with the four-step loop (`search` → `meta` → `sections` → `get
  --section`) rather than leaving it implied across four sections, and covers
  citation form, since the skill advertises help with normative MUST/SHOULD
  language and previously said nothing about how to quote it.
- Adds a recovery path for an empty title search, which is the default mode's
  most common dead end: title search requires every query term in the title, so
  "no matches" means the query was too specific, not that the RFC is absent.
- `--json` is documented as applying to every read command instead of appearing
  only under the ripgrep escape hatch.

## 0.1.0 — 2026-08-01

Initial release. `mcp-server-rfc` on PyPI, `@shbernal/rfc-lookup` on ClawHub.
</content>
</invoke>
