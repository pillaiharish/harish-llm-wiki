# =============================================================================
# Harish LLM Wiki - Makefile
# =============================================================================

.PHONY: init install dev-install test clean lint format help

# Default target
.DEFAULT_GOAL := help

# =============================================================================
# Setup
# =============================================================================

init: ## Initialize the project structure and external data directory
	python -m wiki init

install: ## Install package in production mode
	pip install -e .

dev-install: ## Install package with dev dependencies
	pip install -e ".[dev]"

# =============================================================================
# Pipeline Commands
# =============================================================================

ingest: ## Ingest resources from inputs/
	python -m wiki ingest

normalize: ## Normalize raw data into clean chunks
	python -m wiki normalize

notes: ## Generate LLM notes from normalized chunks
	python -m wiki generate-notes

site: ## Build static VitePress site
	python -m wiki build-site

full: ## Run complete pipeline: ingest -> normalize -> notes -> build-site
	python -m wiki full-run

validate: ## Validate the generated content
	python -m wiki validate

# =============================================================================
# Resource Management
# =============================================================================

add-resource: ## Add a single resource (usage: make add-resource URL=<url>)
	@if [ -z "$(URL)" ]; then \
		echo "Usage: make add-resource URL=<url>"; \
		exit 1; \
	fi
	python -m wiki add-resource --url "$(URL)"

add-batch: ## Add resources from batch file (usage: make add-batch FILE=<path>)
	@if [ -z "$(FILE)" ]; then \
		echo "Usage: make add-batch FILE=<path>"; \
		exit 1; \
	fi
	python -m wiki add-batch --file "$(FILE)"

list-resources: ## List all resources in registry
	python -m wiki list-resources

list-pending: ## List resources waiting to be processed
	python -m wiki list-pending

process-new: ## Process new resources
	python -m wiki process-new

# =============================================================================
# Development
# =============================================================================

test: ## Run all tests
	python3 -m pytest -q

lint: ## Run linting checks
	ruff check wiki/ tests/
	mypy wiki/

format: ## Format code
	black wiki/ tests/
	ruff check --fix wiki/ tests/

clean: ## Clean generated files and caches
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache/
	rm -rf site/node_modules/
	rm -rf site/docs/.vitepress/cache/

# =============================================================================
# Site Development
# =============================================================================

dev-server: ## Start VitePress dev server
	cd site && npm run docs:dev

build-site-npm: ## Build site using npm
	cd site && npm run docs:build

install-site-deps: ## Install VitePress dependencies
	cd site && npm install

# =============================================================================
# Help
# =============================================================================

help: ## Show this help message
	@echo "Harish LLM Wiki - Available Commands"
	@echo "======================================"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'
