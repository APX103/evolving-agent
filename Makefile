.PHONY: test test-all coverage lint format install-dev

VENV_PYTHON := .venv/bin/python
VENV_PIP := .venv/bin/pip

install-dev:
	$(VENV_PIP) install -r requirements-dev.txt

test:
	$(VENV_PYTHON) -m pytest tests/ -m "not integration and not slow"

test-all:
	$(VENV_PYTHON) -m pytest tests/

coverage:
	$(VENV_PYTHON) -m pytest tests/ -m "not integration and not slow" \
		--cov=agent --cov-report=term-missing --cov-report=html

lint:
	$(VENV_PYTHON) -m mypy agent/

format:
	$(VENV_PYTHON) -m black agent/ tests/ benchmarks/
