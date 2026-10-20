PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: venv install test lint fmt demo clean

venv:
	$(PY) -m venv $(VENV)

install: venv
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"

test:
	$(BIN)/pytest

lint:
	$(BIN)/ruff check src tests

fmt:
	$(BIN)/ruff format src tests
	$(BIN)/ruff check --fix src tests

demo:
	OSRM_BACKEND=fake $(BIN)/osrm audit
	OSRM_BACKEND=fake $(BIN)/osrm cost estimate

clean:
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info src/*.egg-info
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
