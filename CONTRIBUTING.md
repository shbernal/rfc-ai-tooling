# Contributing

## Layout

```
core/     the stdlib-only implementation and its tests
skill/    SKILL.md and a vendored copy of the core
mcp/      the PyPI package (mcp-server-rfc), thin adapter over the core
assets/   README images
```

`core/rfc.py` is the only real implementation.
The skill and the MCP server each carry a byte-identical vendored copy, kept honest by CI and regenerated with `make sync-core`.
Never edit a vendored copy.

The core depends on nothing outside the Python standard library.
That keeps the skill self-contained and the MCP server's only dependency the `mcp` SDK.
Python 3.10 or newer.

## Commands

Run these before committing a change to `core/rfc.py`:

```bash
make sync-core lint typecheck test
```

| Target | What it does |
| --- | --- |
| `make sync-core` | Copy `core/rfc.py` into both surfaces |
| `make test` | pytest, no network |
| `make lint` | ruff check and format check |
| `make typecheck` | mypy over the core, the server and the smoke script |
| `make smoke-local` | stdio JSON-RPC session against the working tree |
| `make smoke` | The same session against the published PyPI server |

`make test`, `make lint` and `make format` run through [uv](https://docs.astral.sh/uv/), which syncs the dev dependencies on demand.
They work in a fresh shell with no venv activated.

[`AGENTS.md`](AGENTS.md) has the full release procedure and the reasons behind each rule.

## Breaking changes

Breaking changes are removals, not deprecations.
The old behaviour goes and the version bumps, with no compatibility shim and no runtime notice.
Record each one in [`CHANGELOG.md`](CHANGELOG.md) under the version that made it.
