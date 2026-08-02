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
make smoke         # drive the *published* PyPI server over real stdio JSON-RPC
```

Run `make sync-core lint test` before committing any change to `core/rfc.py`.

`pytest` and `ruff` are dev dependencies, so the targets that need them run
through `uv run`, which syncs the environment on demand — no activated venv
required. `make test RUN=` calls the bare commands instead, for an environment
you manage yourself.

`make smoke` is the only target that tests something other than this working
tree, so it is a release step, not a development one. Run it cold — inside a
container, on a filesystem that has never held this repo — because a warm
`~/.cache/uv` or a leftover mirror invalidates the result:

```bash
docker run --rm -i -v "$PWD/mcp/smoke.py:/smoke.py:ro" python:3.13-slim \
  bash -c 'pip install -q uv && python3 /smoke.py'
```

## Conventions

- Python 3.10+, stdlib only in `core/rfc.py` — do not add a dependency there.
  The MCP server's only dependency is the `mcp` SDK.
- Tests live in `core/test_rfc.py` and run against fixtures in
  `core/fixtures/`, not live network calls. Tests marked `network` hit the
  real RFC Editor and are excluded from CI (`-m 'not network'`).
- No RFC text is bundled in either surface; the corpus is fetched from the RFC
  Editor on demand and optionally mirrored locally via `rfc sync`.

## Released

`v0.1.0` was tagged and released on 2026-08-01, and both surfaces are live:
`mcp-server-rfc` on PyPI and `@shbernal/rfc-lookup` on ClawHub.

Both registries treat a version as permanent. Never delete or re-publish a
released version; fix forward with a version bump on whichever surfaces are
affected. The publish workflow is idempotent on both halves, so re-running it at
an already-published version skips rather than fails.

### Breaking changes are welcome

Released constrains what a *published version* means, not what the next one may
do. When the better behaviour is incompatible with the old one, ship the better
behaviour: remove the old one and bump the version.

- **No deprecation period, no compatibility shims, and no runtime warning that
  a behaviour has changed.** A migration is read once; code carrying a record
  of its own history is paid for on every read after that.
- **Put the notice in `CHANGELOG.md`**, under the version that made the change,
  naming what moved and how to get the old outcome where one exists.
- An error message may name the flag that restores prior behaviour when that
  flag is a genuine feature (`get --full`), never as a notice that something
  used to work differently.

What a fix has to ship on:

- **`core/rfc.py` or `server.py`** — a bump on whichever surfaces are affected.
- **`skill/SKILL.md`** — needs a ClawHub bump. The skill artifact embeds it, so
  a description or trigger fix does not reach users without a release.
- **`mcp/README.md`** — it is the PyPI project page, so a fix only shows up on a
  new release.
- **Root `README.md`** — ships in neither artifact. Commit it; publish nothing.
- **`CHANGELOG.md`** — ships in neither artifact either, but every version bump
  gets an entry there before the tag is cut, and the date goes in at that point.
