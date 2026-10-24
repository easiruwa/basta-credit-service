BACKEND := credit-service/backend
COMPOSE := docker compose -f credit-service/docker-compose.yml

.DEFAULT_GOAL := help
.PHONY: help setup up down logs test lint fmt check

help: ## Show available commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-8s %s\n", $$1, $$2}'

setup: ## Install dependencies and the pre-commit hook
	cd $(BACKEND) && uv sync
	uvx pre-commit install

up: ## Build and start the API, worker, Mongo and Redis
	$(COMPOSE) up -d --build --wait
	@echo "API running at http://localhost:8000 (docs at /docs)"

down: ## Stop all services
	$(COMPOSE) down

logs: ## Follow the API and worker logs
	$(COMPOSE) logs -f api worker

test: ## Run the test suite (starts Mongo if needed)
	$(COMPOSE) up -d --wait mongo
	cd $(BACKEND) && uv run pytest

lint: ## Check formatting and lint, without changing files
	cd $(BACKEND) && uv run ruff format --check . && uv run ruff check .

fmt: ## Format and auto-fix lint issues
	cd $(BACKEND) && uv run ruff check --fix . && uv run ruff format .

check: lint test ## Run lint and tests, as CI does
