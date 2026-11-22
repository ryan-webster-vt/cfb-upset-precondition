PYTHON ?= python
STREAMLIT ?= streamlit

.PHONY: help setup test test-cov lint format check schemas probe app clean

help:
	@echo "Targets:"
	@echo "  setup      install runtime + dev dependencies"
	@echo "  test       run the offline test suite"
	@echo "  test-cov   run tests with coverage on the Phase 0 core"
	@echo "  lint       ruff + black check"
	@echo "  format     auto-fix lint/format"
	@echo "  check      lint + tests (P0 gate)"
	@echo "  schemas    export Pydantic JSON Schemas to docs/contracts/"
	@echo "  probe      run the live capability probe and write docs/CAPABILITIES.md"
	@echo "  app        run the Streamlit walking skeleton"
	@echo "  clean      remove local caches"

setup:
	$(PYTHON) -m pip install -r requirements-dev.txt

test:
	$(PYTHON) -m pytest

test-cov:
	$(PYTHON) -m pytest --cov=cfb_upset.domain.rules --cov=cfb_upset.domain.screen --cov-report=term-missing

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m black --check .

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m black .

check: lint test

schemas:
	$(PYTHON) -m cfb_upset.contracts.export

probe:
	$(PYTHON) scripts/probe.py --write

app:
	$(STREAMLIT) run app.py

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
