VENDORED := skill/scripts/rfc.py mcp/src/mcp_server_rfc/rfc.py

.PHONY: sync-core check-vendor test lint format

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

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
