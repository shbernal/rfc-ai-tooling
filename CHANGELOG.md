# Changelog

Both surfaces — the `rfc-lookup` skill and the `mcp-server-rfc` package — are
versioned together from `core/rfc.py`, so one entry covers both unless it says
otherwise.

Breaking changes are removals, not deprecations: the old behaviour goes, the
version bumps, and this file is where the change is recorded. Nothing in the
code announces that something used to work differently.

## 0.2.0 — unreleased

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
  installed by either surface: the skill runs `python3 scripts/rfc.py` and the
  package is reachable as `python3 -m mcp_server_rfc.rfc`. The instruction
  failed as typed at exactly the moment it mattered most — the `--fulltext`
  refusal on an unsynced machine, which is the first wall an agent hits.
  Commands are now derived from how the program was actually invoked, which
  also fixes `--help`'s usage line.

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
