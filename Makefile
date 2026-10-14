VENV := api/.venv
PY := $(VENV)/bin/python

.PHONY: venv test lint db down up ingest-once smoke env n8n-setup user web web-test web-dev

venv:
	python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e "./api[dev]"

test:
	cd api && .venv/bin/pytest -q

lint:
	cd api && .venv/bin/ruff check .

db:
	docker compose up -d --wait db

down:
	docker compose down

up:
	docker compose up -d --build --wait

ingest-once:
	set -a; . ./.env; set +a; $(PY) scripts/ingest_once.py "$(COMPANY)"

smoke:
	set -a; . ./.env; set +a; $(PY) -m jobpipe.llm.smoke --provider $(PROVIDER)

env:
	python3 scripts/make_env.py

n8n-setup: up
	scripts/n8n-setup.sh

user:
	docker compose exec api python -m jobpipe.create_user "$(USERNAME)"

web:
	cd web && npm ci && npm run build

web-test:
	cd web && npm run typecheck && npm test

web-dev:
	cd web && npm run dev
