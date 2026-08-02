VENDORED := skill/scripts/rfc.py mcp/src/mcp_server_rfc/rfc.py

# pytest and ruff are dev dependencies, not system commands, so calling them
# bare only works inside an activated venv. `uv run` creates and syncs the venv
# on demand, which makes these targets work in a fresh shell. Override to use
# an environment you manage yourself: `make test RUN=` in an active venv.
RUN ?= uv run

.PHONY: sync-core check-vendor test lint format smoke

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

# The rest of this file proves the repository works. This proves the artifact
# on PyPI works: a real stdio JSON-RPC session against whatever `uvx
# mcp-server-rfc` resolves. Hits the network, so it is not part of `make test`.
# Run it after every release, and cold — a container, not a machine that has
# ever held this repo. Pass a command to point it at the working tree instead:
#   PYTHONPATH=mcp/src python3 mcp/smoke.py -- python3 -m mcp_server_rfc.server
smoke:
	python3 mcp/smoke.py

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format:
	$(RUN) ruff format .
