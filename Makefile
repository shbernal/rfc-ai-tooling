VENDORED := skill/scripts/rfc.py mcp/src/mcp_server_rfc/rfc.py

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
	pytest

# The rest of this file proves the repository works. This proves the artifact
# on PyPI works: a real stdio JSON-RPC session against whatever `uvx
# mcp-server-rfc` resolves. Hits the network, so it is not part of `make test`.
# Run it after every release, and cold — a container, not a machine that has
# ever held this repo. Pass a command to point it at the working tree instead:
#   PYTHONPATH=mcp/src python3 mcp/smoke.py -- python3 -m mcp_server_rfc.server
smoke:
	python3 mcp/smoke.py

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
