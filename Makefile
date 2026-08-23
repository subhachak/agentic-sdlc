.PHONY: api web test test-api test-qa qa-demo preflight demo-reset

# --- control plane ---------------------------------------------------------

api:
	cd control-plane/api && uv run uvicorn app.main:app --reload --port 8000

web:
	cd control-plane/web && npm run dev

preflight:
	cd control-plane/api && uv run python scripts/preflight_check.py

demo-reset:
	cd control-plane/api && uv run python scripts/demo_reset.py

# --- execution plane -------------------------------------------------------

qa-demo:
	./scripts/local-demo.sh

# --- tests -----------------------------------------------------------------

test: test-api test-qa

test-api:
	cd control-plane/api && uv run pytest -q

test-qa:
	cd execution-plane/qa && python -m pytest tests/ -q
