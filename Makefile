VENDORED := skill/scripts/rfc.py mcp/src/mcp_server_rfc/rfc.py

# What the smoke targets require the server to report. Read from the packaged
# manifest rather than core/rfc.py, because this is the version that gets
# uploaded; a test asserts the two agree.
VERSION := $(shell grep -m1 '^version = ' mcp/pyproject.toml | cut -d'"' -f2)

# pytest and ruff are dev dependencies, not system commands, so calling them
# bare only works inside an activated venv. `uv run` creates and syncs the venv
# on demand, which makes these targets work in a fresh shell. Override to use
# an environment you manage yourself: `make test RUN=` in an active venv.
RUN ?= uv run

.PHONY: sync-core check-vendor test lint format smoke smoke-local print-version

# For the container recipe in AGENTS.md, which needs the version on a command
# line built outside this Makefile.
print-version:
	@echo $(VERSION)

sync-core:
	@for dest in $(VENDORED); do \
		mkdir -p "$$(dirname $$dest)"; \
		cp core/rfc.py "$$dest"; \
		echo "wrote $$dest"; \
	done

# Both surfaces are thin adapters over one implementation; if a vendored copy
# drifts from core/rfc.py they silently stop behaving the same way.
check-vendor:
	@status=0; \
	for dest in $(VENDORED); do \
		if cmp -s core/rfc.py "$$dest"; then \
			echo "ok   $$dest"; \
		else \
			echo "DRIFT $$dest differs from core/rfc.py (run: make sync-core)"; \
			status=1; \
		fi; \
	done; \
	exit $$status

test:
	$(RUN) pytest

# The same JSON-RPC session against two different things, and the difference is
# the point.
#
# smoke-local drives the working tree, so it can run before the tag. That
# ordering matters: `smoke` can only ever test a version that is already
# published, which is how 0.2.1's section-guard regression reached PyPI before
# anything ran the call that would have caught it. Run this before every
# release, and on pull requests.
#
# smoke proves the *artifact*: entry point, wheel contents, metadata, and
# dependency resolution, none of which the working tree can vouch for. It is a
# release step, and it runs cold — a container, not a machine that has ever
# held this repo, because a warm ~/.cache/uv invalidates the result.
#
# Both pass --expect-version. For smoke it is the point of the run: until PyPI's
# simple index propagates, `uvx` resolves the *previous* release and every other
# check passes against it, which is how the 0.2.4 release was first reported
# green while testing 0.2.3. For smoke-local it is nearly free and catches
# core/rfc.py's __version__ drifting from the packaged one.
#
# Both hit the network, so neither is part of `make test`.
smoke-local:
	PYTHONPATH=mcp/src python3 mcp/smoke.py --expect-version $(VERSION) \
	  -- python3 -m mcp_server_rfc.server

smoke:
	python3 mcp/smoke.py --expect-version $(VERSION)

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format:
	$(RUN) ruff format .
