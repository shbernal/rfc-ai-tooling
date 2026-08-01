# AGENTS.md

Guidance for AI agents working in this repo.

## What this is

Two surfaces (a Claude skill and an MCP server) over one shared, stdlib-only
Python core (`core/rfc.py`) that gives an agent access to the IETF RFC corpus.
See `README.md` for the full pitch and usage.

```
core/     the stdlib-only implementation and its tests — the only real source
skill/    SKILL.md and a vendored copy of core/rfc.py
mcp/      the mcp-server-rfc PyPI package, a thin adapter over the core
```

## The vendoring rule

`core/rfc.py` is the single implementation. `skill/scripts/rfc.py` and
`mcp/src/mcp_server_rfc/rfc.py` are byte-identical vendored copies, not
independent code.

- **Never edit a vendored copy directly.** Edit `core/rfc.py`, then run
  `make sync-core`.
- CI enforces this via `make check-vendor`; a drifted copy fails the build.

## Commands

```bash
make sync-core     # copy core/rfc.py into both surfaces — run after any core edit
make test          # pytest, no network (network-marked tests are excluded)
make lint          # ruff check + format --check
make format        # ruff format .
make check-vendor  # verify vendored copies match core/rfc.py
```

Run `make sync-core lint test` before committing any change to `core/rfc.py`.

## Conventions

- Python 3.10+, stdlib only in `core/rfc.py` — do not add a dependency there.
  The MCP server's only dependency is the `mcp` SDK.
- Tests live in `core/test_rfc.py` and run against fixtures in
  `core/fixtures/`, not live network calls. Tests marked `network` hit the
  real RFC Editor and are excluded from CI (`-m 'not network'`).
- No RFC text is bundled in either surface; the corpus is fetched from the RFC
  Editor on demand and optionally mirrored locally via `rfc sync`.

## Pre-release

No GitHub release has been cut yet. Treat the project as pre-release and free
to change:

- Do not preserve backwards compatibility unless explicitly asked.
- Do not defer to the prior architecture when it conflicts with the current
  goal.
- Existing code, docs, and plans are context, not constraints.

Once there is a GitHub release, compatibility and migration concerns become
real constraints and must be evaluated before breaking changes.
