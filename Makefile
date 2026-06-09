.PHONY: setup ingest query watch-chat lint reflect install-service uninstall-service test clean

VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip

setup:
	@echo "Configurazione dell'ambiente virtuale..."
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e .[dev]
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Creato file .env da .env.example. Modificalo con le tue chiavi API."; \
	fi
	@echo "Setup completato con successo."

ingest:
	$(PYTHON) -m engine.main ingest

query:
	$(PYTHON) -m engine.main query

watch-chat:
	$(PYTHON) -m engine.main watch-chat

lint:
	$(PYTHON) -m engine.main lint

reflect:
	$(PYTHON) -m engine.main reflect

ontology-gen:
	$(PYTHON) -m engine.main ontology

ontology-apply:
	$(PYTHON) -m engine.main ontology --apply

install-service:
	$(PYTHON) -m engine.plist_generator install

uninstall-service:
	$(PYTHON) -m engine.plist_generator uninstall

dashboard:
	$(PYTHON) -m uvicorn engine.dashboard:app --reload --port 8000

test:
	$(PYTHON) -m pytest

clean:
	rm -rf $(VENV) build/ *.egg-info .pytest_cache/
	find . -type d -name "__pycache__" -exec rm -rf {} +
