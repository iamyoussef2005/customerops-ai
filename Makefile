PYTHON ?= python

.PHONY: install dev test lint format typecheck check up down migrate seed test-db test-integration test-offline smoke-agent test-rag evaluate-rag retention

install:
	$(PYTHON) -m pip install -c requirements.lock -e . --group dev

dev:
	$(PYTHON) -m uvicorn customerops_ai.main:app --reload --host 127.0.0.1 --port 8000

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff format .

typecheck:
	$(PYTHON) -m mypy

check: lint typecheck test

up:
	docker compose up --build -d --wait

down:
	docker compose down

migrate:
	docker compose run --rm migrate

seed:
	docker compose exec backend python -m customerops_ai.seed --confirm-fictional-data

test-db:
	docker compose --profile test up -d --wait test-postgres

test-integration:
	$(PYTHON) -m pytest -m integration --require-database

test-offline:
	$(PYTHON) -m pytest -m "not live"

# Requires explicit CUSTOMEROPS_RUN_LIVE_SMOKE=1, OPENAI_API_KEY, CUSTOMEROPS_AGENT_MODEL.
smoke-agent:
	$(PYTHON) -m pytest tests/live/test_openai_smoke.py -m live -q

test-rag:
	$(PYTHON) -m pytest tests/test_rag.py -q

# Explicit opt-in: paid embeddings against already ingested sample documents.
evaluate-rag:
	$(PYTHON) -m customerops_ai.rag.evaluate --allow-paid-requests

retention:
	$(PYTHON) -m customerops_ai.retention --apply
