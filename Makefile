PYTHON ?= python
STREAMLIT ?= streamlit

.PHONY: help setup doctor test test-cov lint format check schemas probe app ingest verify-corpus clean

help:
	@echo "Targets:"
	@echo "  setup      install runtime + dev dependencies"
	@echo "  doctor     print the active interpreter and verify chromadb"
	@echo "  test       run the offline test suite"
	@echo "  test-cov   run tests with coverage on the Phase 0 core"
	@echo "  lint       ruff + black check"
	@echo "  format     auto-fix lint/format"
	@echo "  check      lint + tests (P0 gate)"
	@echo "  schemas    export Pydantic JSON Schemas to docs/contracts/"
	@echo "  probe      run the live capability probe and write docs/CAPABILITIES.md"
	@echo "  app        run the Streamlit walking skeleton"
	@echo "  ingest     build the 2021-2025 FBS-vs-FBS corpus (resume-safe)"
	@echo "  verify-corpus  check dedupe, leakage, and +/-5% per-season counts"
	@echo "  clean      remove local caches"
	@echo ""
	@echo "Use the canonical env first: conda activate ads_5984"

setup:
	$(PYTHON) -m pip install -r requirements-dev.txt

doctor:
	@$(PYTHON) -c "import sys, chromadb, streamlit, pydantic; print('python:', sys.executable); print('version:', sys.version.split()[0]); print('streamlit:', streamlit.__version__); print('pydantic:', pydantic.__version__); print('chromadb:', chromadb.__version__)"

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

ingest:
	$(PYTHON) -m cfb_upset.pipelines.ingest_corpus --seasons 2021 2022 2023 2024 2025 --resume

verify-corpus:
	$(PYTHON) scripts/verify_corpus.py --db data/cfb.db --seasons 2021 2022 2023 2024 2025

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
