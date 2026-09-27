.PHONY: help install dev lock test lint format audit clean run docker-build docker-run

help:
	@echo "Available targets:"
	@echo "  install      - Install the locked runtime dependencies"
	@echo "  dev          - Install the locked runtime and development dependencies"
	@echo "  lock         - Regenerate uv.lock and requirements.txt from pyproject.toml"
	@echo "  test         - Run tests"
	@echo "  lint         - Run the format, lint and type checks"
	@echo "  format       - Rewrite files with ruff format and apply lint fixes"
	@echo "  audit        - Audit the locked runtime dependency set with pip-audit"
	@echo "  clean        - Clean artifacts"
	@echo "  run          - Run bot locally"
	@echo "  docker-build - Build Docker image"
	@echo "  docker-run   - Run Docker container"

install:
	uv sync --locked --no-dev

dev:
	uv sync --locked

# Run this in the same commit that changes pyproject.toml. `uv lock` resolves the
# transitive closure into uv.lock; `uv export` renders the hash-pinned requirements.txt
# that pip-audit reads and that anyone installing without uv can use.
lock:
	uv lock
	uv export --no-dev --no-emit-project --format requirements-txt -o requirements.txt

test:
	uv run pytest

lint:
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy bot core

format:
	uv run ruff format .
	uv run ruff check . --fix

# Needs network access to the advisory database, so it is deliberately not part of
# `lint`. The Dependency Audit workflow is the gate; this is the same command locally.
audit:
	uv run pip-audit --strict --progress-spinner off --requirement requirements.txt

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	rm -f bot.log .coverage coverage.xml

run:
	uv run python -m bot.main

docker-build:
	docker build -t scraping-bot .

docker-run:
	docker run --rm -p 8080:8080 scraping-bot
