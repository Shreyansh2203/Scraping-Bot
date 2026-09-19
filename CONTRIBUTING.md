# Contributing

Thank you for your interest in contributing to Scraping-Bot! We welcome contributions of all kinds, including bug fixes, new features, documentation improvements, and more.

## Development Setup

1. Fork and clone the repository.
2. Install development dependencies:
   ```bash
   make dev
   ```
3. Set up your `.env` file from `.env.example`.

## Code Quality

We use `black` for formatting, `ruff` for linting, and `mypy` for static type checking.

Before submitting a pull request, ensure your code passes all checks:
```bash
make format
make lint
make test
```

## Pull Request Process

1. Create a descriptive branch name.
2. Ensure you have added or updated tests if adding new functionality.
3. Submit a pull request against the `main` branch.
4. Ensure CI checks pass.
