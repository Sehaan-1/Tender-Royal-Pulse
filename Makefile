.PHONY: test test-all test-unit test-integration run export lint typecheck fmt clean clean-win

PYTHON    := python
PIP       := $(PYTHON) -m pip
PYTEST    := $(PYTHON) -m pytest
RUFF      := $(PYTHON) -m ruff
MYPY      := $(PYTHON) -m mypy

## ----------------------------------------------------------------------------- ##
##  Test targets                                                                 ##
## ----------------------------------------------------------------------------- ##

test:
	$(PYTEST) --cov=src --cov-report=term-missing --cov-report=xml -q

test-all:
	$(PYTEST) -v

test-unit:
	$(PYTEST) -m "not integration" -q

test-integration:
	$(PYTEST) tests/integration/ -v

## ----------------------------------------------------------------------------- ##
##  Lint + typecheck                                                             ##
## ----------------------------------------------------------------------------- ##

lint:
	$(RUFF) check src tests

typecheck:
	$(MYPY) src/

fmt:
	$(RUFF) format src tests

## ----------------------------------------------------------------------------- ##
##  Run a sample crawl (mock)                                                   ##
## ----------------------------------------------------------------------------- ##

run:
	$(PYTHON) -m tender_royal_pulse.cli crawl \
		--input samples/INPUT.example.json \
		--db data/tenderpulse.db \
		--output data/tenders.csv

## ----------------------------------------------------------------------------- ##
##  Export from existing DB                                                     ##
## ----------------------------------------------------------------------------- ##

export:
	$(PYTHON) -m tender_royal_pulse.cli export \
		--db data/tenderpulse.db \
		--output exports/tenders.jsonl \
		--format jsonl

## ----------------------------------------------------------------------------- ##
##  Utilities                                                                    ##
## ----------------------------------------------------------------------------- ##

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov dist

# Detect OS for cross-platform clean
clean-win:
	Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
	Get-ChildItem -Recurse -File -Filter *.pyc | Remove-Item -Force
	Remove-Item -Recurse -ErrorAction SilentlyContinue .pytest_cache,.mypy_cache,.ruff_cache,htmlcov,dist
