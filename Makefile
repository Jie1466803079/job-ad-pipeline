VENV := api/.venv
PY := $(VENV)/bin/python

.PHONY: venv test lint

venv:
	python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e "./api[dev]"

test:
	cd api && .venv/bin/pytest -q

lint:
	cd api && .venv/bin/ruff check .
