# Contributing

Contributions are welcome! Please follow these guidelines.

## Development Setup

```bash
git clone https://github.com/Shreyansh2203/Scraping-Bot.git
cd Scraping-Bot
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
# Edit .env with test values
```

## Pre-commit Hooks

```bash
pip install pre-commit
pre-commit install
```

This will run `ruff`, `black`, and `mypy` on every commit.

## Running Tests

```bash
pytest --cov=bot --cov=core
```

## Code Style

- **Formatter:** `black .` (line length 100)
- **Linter:** `ruff check .`
- **Type checker:** `mypy --strict bot/ core/`

## Pull Request Process

1. Fork the repo
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Make changes and ensure tests pass
4. Run `ruff check . && black . && mypy --strict bot/ core/`
5. Commit with conventional commit message (`feat:`, `fix:`, `docs:`, etc.)
6. Push to your fork
7. Open a Pull Request

## Commit Message Format

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `refactor:` Code refactoring
- `test:` Test changes
- `chore:` Maintenance tasks

Example: `feat: add support for Instagram stories`

## Reporting Bugs

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md) and include:
- Version (`__version__` or git commit)
- Steps to reproduce
- Relevant logs

## Feature Requests

Use the [feature request template](.github/ISSUE_TEMPLATE/feature_request.md).

## Questions?

Open a [discussion](https://github.com/Shreyansh2203/Scraping-Bot/discussions) for general questions.
