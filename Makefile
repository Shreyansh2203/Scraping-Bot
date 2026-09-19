.PHONY: help install dev test lint format clean run docker-build docker-run

help:
	@echo "Available targets:"
	@echo "  install      - Install dependencies"
	@echo "  dev          - Install with dev dependencies"
	@echo "  test         - Run tests"
	@echo "  lint         - Run linters"
	@echo "  format       - Format code"
	@echo "  clean        - Clean artifacts"
	@echo "  run          - Run bot locally"
	@echo "  docker-build - Build Docker image"
	@echo "  docker-run   - Run Docker container"

install:
	pip install .

dev:
	pip install .[dev]

test:
	pytest

lint:
	ruff check .
	black --check .
	mypy --strict bot/ core/

format:
	black .
	ruff check . --fix

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache

run:
	python -m bot.main

docker-build:
	docker build -t scraping-bot .

docker-run:
	docker run --rm -p 8080:8080 scraping-bot
