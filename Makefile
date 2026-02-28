VENV_DIR := venv
PYTHON := $(VENV_DIR)/bin/python
PIP := $(VENV_DIR)/bin/pip
ALEMBIC := $(VENV_DIR)/bin/alembic
PYTEST := $(VENV_DIR)/bin/pytest
RUFF := $(VENV_DIR)/bin/ruff

.PHONY: setup ingest pagerank run start test lint

setup:
	test -x $(PYTHON) || python3 -m venv venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt -r requirements-dev.txt
	$(ALEMBIC) upgrade head

ingest:
	$(PYTHON) -m backend.cli ingest

pagerank:
	$(PYTHON) -m backend.cli pagerank

run:
	$(PYTHON) -m uvicorn backend.api:app --reload

start:
	$(PYTHON) -m backend.cli ingest
	$(PYTHON) -m uvicorn backend.api:app --reload

test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTEST)

lint:
	$(RUFF) check .
