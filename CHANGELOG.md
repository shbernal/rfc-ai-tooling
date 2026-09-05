# Changelog

Both surfaces — the `rfc-lookup` skill and the `mcp-server-rfc` package — are
versioned together from `core/rfc.py`, so one entry covers both unless it says
otherwise.

Breaking changes are removals, not deprecations: the old behaviour goes, the
version bumps, and this file is where the change is recorded. Nothing in the
code announces that something used to work differently.

## 0.4.0 — 2026-09-05

### Breaking

- **Full-text queries are literal.** `--fulltext` / `scope='fulltext'` passed
  the query straight to `rg -e` or `grep -E`, so every search was a pattern in
  whichever dialect the machine happened to have. `\d` is a digit class to
  ripgrep and a literal `d` to POSIX ERE; `C++` matches on one and fails to
  compile on the other. The same query over the same corpus answered two
  different questions depending on what was installed, and a search for
  `application/json;charset` or `RFC 2616 (1)` hit that with nothing to explain
  it.

  Queries now match literally. `--regex` / `regex=true` opts back into pattern
  matching — which is what that flag has always meant for titles and, until
  now, was silently ignored under `--fulltext`. The dialect there is still the
  backend's own; `tool` in the payload names which one answered.

- **`hits` is now `matching_lines`, and it counts the same thing everywhere.**
  Ripgrep was asked for `--count-matches` and grep for `-c`, so the number was
  every match on one backend and every matching *line* on the other. That
  number is what ranks the results, so a search could come back in a different
  order on a different machine, and the field name settled nothing. Both are
  asked for matching lines now. Expect smaller numbers where ripgrep is
  installed, and read `matching_lines` where you read `hits`.

- **Title results put current RFCs before superseded ones.** Results were
  ordered by RFC number ascending and then cut at `--limit` (20 by default), so
  the oldest matches filled the page and the newest were dropped — on this
  corpus, keeping RFC 2616 and losing RFC 9110, which is the exact instinct the
  obsolescence banner exists to correct. Superseded documents now sort after
  current ones, ascending by number within each group. They still appear and
  `total` is unchanged; they no longer crowd out what replaced them.

- **A number at the start of a line is no longer a heading on its own.**
  `sections` accepted anything matching `N.` at column 0, so prose wrapping
  onto a line that opens with a number became a section: RFC 1035 reported a
  section 25 made of half a sentence about SMTP, and RFC 768, which has no
  numbered headings at all, reported one called "Aug 1980". A top-level heading
  now has to continue the sequence — `1`, then `2`, and so on — which leaves
  every real heading in RFC 2616 and RFC 9110 in place and takes RFC 1700, the
  worst case in the corpus, from 364 headings to 71. A `--section` that used to
  resolve to a line of table data no longer resolves; there is no way to ask
  for one back, because it was never a section.

- **`limit` below 1 is an error.** `limit=-1` dropped the last result while
  `total` still counted it, so the page reported itself as truncated and
  omitted a row for no stated reason; `limit=0` rendered as "no matches" under
  a non-zero total.

- **The MCP tools validate the RFC number.** `get_rfc(0)` and
  `list_sections(-5)` used to reach the network as `rfc0.txt` and `rfc-5.txt`
  and come back as a 404 that read as though the RFC did not exist. They now
  refuse before fetching, through the same parser the CLI uses — which also
  means `number` accepts `"RFC 9110"` and `"rfc9110"` as well as `9110`.

### Added

- **`regex` on the MCP `search_rfcs` tool**, matching the CLI's `--regex` in
  both scopes.
- **Payload keys the two surfaces disagreed about**, reconciled to the union of
  what each returned. Full-text results carry `tool`, and each row carries
  `record`, `title` and `header`; title results carry `fulltext_available`.
  Nothing that was there is gone.

### Fixed

- **The index and cached documents are written atomically.** Both were written
  straight over the target, so a process killed mid-write left a truncated
  file — and it failed silently either way. A half-written index carries a
  fresh mtime, so it was served as current for a day and reported real RFCs as
  missing; a half-written document is only ever checked for existence, so
  nothing ever repaired it.
- **`smoke.py` resolves the mirror the way the server does.** Its copy of the
  rule was not updated when 0.3.0 moved the default to `$XDG_DATA_HOME`, so on
  any machine with that set its "connecting and listing tools created no
  mirror" check watched a directory the server would never write to and passed
  without testing anything.
- **A revalidation the CDN answers 304 to no longer re-parses the index.** The
  touch that resets the freshness clock moved the mtime the parse cache is
  keyed on, so a server that stays up re-read 2 MB of unchanged text every day.
- **A section read builds the page-furniture mask once** instead of walking the
  whole document for it twice.

## 0.3.0 — 2026-08-15

### Fixed

- **The module imports under a UID with no home directory.** The default mirror
  was a module-level constant, so `Path.home()` ran at import — and it raises
  `RuntimeError` when there is neither a passwd entry nor `$HOME`, which is the
  ordinary state of a container running as an arbitrary UID (`runAsUser` with
  no matching passwd entry is the default on OpenShift and common in hardened
  Kubernetes). `import rfc` failed there, and `--mirror` and `$RFC_MIRROR`
  could not help: the constant was computed before either could be read. The
  default is now computed on call, so both overrides work with no home
  directory at all, and only a run that genuinely falls through to the default
  still fails. The `--mirror` help text names the resolution order instead of
  interpolating the resolved path, for the same reason.

  `make smoke` could not have caught this — it runs as root, where `HOME=/root`
  resolves.

### Breaking

- **The mirror now follows `$XDG_DATA_HOME`, and `%LOCALAPPDATA%` on Windows.**
  `~/.local/share` is the fallback the XDG spec names for when `$XDG_DATA_HOME`
  is unset; hardcoding it overrode everyone who had already said where their
  data goes. Windows had no correct location at all — it got a `.local/share`
  directory in the user profile that no backup or uninstall tool recognises —
  and now uses the local profile, never the roaming one, which would sync half
  a gigabyte of RFC text to a domain controller at every logon. A relative
  value in either variable is ignored rather than resolved, as the spec says.

  Anyone with `$XDG_DATA_HOME` set to a non-default location will find their
  existing corpus where they left it but no longer looked for: `status` will
  report no mirror and `--fulltext` will refuse. Either move the directory, or
  set `RFC_MIRROR` to the old path — `$HOME/.local/share/rfc-ai-tooling` — to
  keep it where it is. Unset, as it is on most machines, nothing moves.

  `RFC_MIRROR` and `--mirror` are unchanged and still win over both.

## 0.2.4 — 2026-08-04

### Fixed

- **The MCP server no longer pins itself to the first index it loaded.** It
  held the parsed index in a module global for the life of the process, which
  quietly cancelled two things the core does on purpose. `INDEX_TTL_SECONDS`
  never fired, so a long-running server — the HTTP deployment especially —
  answered from whatever it read at startup and reported RFCs published since
  then as nonexistent. And the offline fallback directly above was defeated:
  its whole design is to leave the mtime alone so the *next* call retries, and
  a first call made during an outage meant there was no next call.

  `load_index` now reuses its previous parse only while the index file on disk
  is unchanged, keyed on its path, mtime and size. The server holds no index
  state at all, and repeated calls cost a `stat`.

- **`list_sections` and `get_rfc` no longer fail when the index is
  unreachable.** Both looked the header up in a way that propagated the
  error, so an unfetchable index took the document with it — even though
  retrieval never consults the index and the text fetches perfectly well. They
  now use the same best-effort banner the CLI does, degrading to `RFC <n>`.
  This is what `core/rfc.py`'s `header_for` was already for; it is public
  under that name now rather than private under `_header_for`.

- **A network blip no longer turns a readable index into an error.** Once the
  index aged past its TTL, refreshing it was mandatory: a failed revalidation
  raised out of `ensure_index`, so `search` and `find` reported a network error
  while a perfectly good index sat on disk. `get` survived but dropped the
  obsolescence banner — the one thing the tool adds over reading the document
  directly — because its fallback treats a missing index and an unreachable one
  the same way.

  A refresh that cannot reach the network now serves the index on disk. The
  file's mtime is deliberately not touched, so `status` still reports its true
  age and the next call retries rather than recording the failure as a refresh.
  With no index on disk there is nothing to fall back to and the error still
  surfaces.

### Changed

- **The index refreshes daily instead of weekly.** `INDEX_TTL_SECONDS` drops
  from 7 days to 24 hours. It was a week because revalidation did not work:
  the RFC Editor's CDN answered every conditional GET with 200 and the full
  2 MB, so the TTL was the only thing keeping refresh traffic down. As of
  2026-08-03 it honours `If-None-Match` (ietf-tools/red#475), so a refresh that
  finds nothing new is a header exchange. A week was long enough for the
  obsolescence banner to be confidently wrong about a document; a day is as
  fine-grained as the corpus gets, since RFCs publish in weekday batches.

  Nothing to do to get the old cadence — pass a different `ttl` to
  `ensure_index` if you are calling it directly.

- **`status` no longer reuses the refresh interval to decide what is stale.**
  These are separate questions, and answering both with one number meant
  tightening the refresh cadence would relabel a two-day-old index as stale
  when it is fine. The warning threshold moves to `INDEX_STALE_SECONDS` and
  stays at 7 days, so `status` reports staleness exactly as it did in 0.2.3.
  Reaching it now means a week with no working refresh at all.

## 0.2.3 — 2026-08-03

### Fixed

- **A section you name is never refused for its length again.** 0.2.1 added a
  guard refusing an uncapped read of a section over 1000 lines. RFC 2616's
  section 13 is 1431 lines and is *the* canonical example of reading one section
  instead of a whole RFC — it is the case `smoke.py` has always used to prove the
  project works — so the guard refused the thing the project is for. `get_rfc`
  returned an error where 0.2.0 returned the caching model, and with it went the
  obsolescence banner.

  The whole-document guard deliberately leaves named sections alone, on the
  grounds that naming one *is* the scoping, and that was right. What 0.2.1 got
  right is kept: `list_sections` reports how long each section is, and
  `max_lines` caps any read. The choice is informed rather than blocked.

  **If you are on 0.2.1 or 0.2.2, upgrade.** Both refuse
  `get_rfc(2616, section="13")` and every other section past 1000 lines.

## 0.2.2 — 2026-08-03

### Documentation

- **Installing the skill straight from this repository is now the first option**,
  via [`skills`](https://github.com/vercel-labs/skills): `npx skills add
  shbernal/rfc-ai-tooling`. It takes the skill's name from `SKILL.md`'s
  frontmatter rather than its path, so it lands at `.claude/skills/rfc-lookup/`
  — the flat layout Claude Code scans — and does for free the flattening the
  ClawHub route needs three commands to arrange. ClawHub remains the way to
  install a *released* version; the repo route tracks `main`.

- **The skillbarn instructions are gone.** Nothing replaced it as a vendoring
  story: `skills` writes its own `skills-lock.json`, and ClawHub covers the
  released-version case, so the third tool was a step without a job.

## 0.2.1 — 2026-08-03

Both fixes come from driving the published 0.2.0 through Claude Desktop and
reading what the model actually sent. See `docs/desktop-verification.md`.

### Fixed

- **`max_lines` was silently discarded when `section` was also given.** The MCP
  schema accepted both and honoured only the section, so a model asking for
  section 3.1 of RFC 791 capped at 120 lines received all 729 of it, 26 KB,
  with nothing indicating an argument had been dropped. It now caps the section,
  and on the CLI `--max-lines` does the same for every read. `--section` with
  `--lines`, and `section` with `start_line`, are contradictory rather than
  merely redundant — both name where to start — and are now an error instead of
  a silent preference for one of them.

### Changed

- **A section over 1000 lines is now refused unless capped.** RFC 2616's section
  13 is 1431 lines: comfortably under the whole-document limit, and so a fully
  scoped, entirely reasonable-looking request that still costs what reading the
  RFC would have. The whole-document guard deliberately ignores sections, on the
  grounds that naming one *is* the scoping — this is the case where that stops
  being true. Pass `max_lines` for the first part of it, read a subsection, or
  `full=true` / `--full` to override.

- **`list_sections` and `sections` now report each section's length.** The guard
  above is the half that holds when advice is skipped; this is the half that
  makes the advice followable. Previously nothing short of reading a section
  revealed how long it was, so a model had no way to prefer a smaller one — it
  found out by receiving 59 KB.

## 0.2.0 — 2026-08-03

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

### Documentation

- **Where to check that a client actually called the tools**, in
  `docs/desktop-verification.md`. A connected server that is never invoked looks
  identical to a working one, and on Claude Desktop the per-server MCP log holds
  only the handshake — it reports zero `tools/call` even when calls succeeded, so
  reading it as proof of a bluffing model is a false negative. The evidence is in
  `main.log`'s permission lines and, with full inputs and outputs, in the session
  transcript.

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
