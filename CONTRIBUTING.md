# Contributing to Scraping-Bot

Thank you for your interest in contributing to Scraping-Bot.

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).

## Commit Message Format

We follow Conventional Commits. The table below lists the types recognized by our release automation:

| Type | Section in the changelog | Description |
|---|---|---|
| `feat` | Features | A new feature |
| `fix` | Bug Fixes | A bug fix |
| `refactor` | Refactoring | A code change that neither fixes a bug nor adds a feature |
| `docs` | Documentation | Documentation only changes |
| `chore` | Chores | Other changes that don't modify src or test files |
| `chore(deps)` | Dependency Updates | Changes to dependencies |
| `test` | Tests | Adding missing tests or correcting existing tests |
| `ci` | CI | Changes to our CI configuration files and scripts |
| `build` | Build | Changes that affect the build system or external dependencies |
| `perf` | Performance | A code change that improves performance |
| `style` | Code Style | Changes that do not affect the meaning of the code |

## Development Setup

1. Install Python 3.12+ and [uv](https://github.com/astral-sh/uv).
2. Clone the repository and install dependencies:
   ```bash
   uv sync
   ```
3. Run test suite:
   ```bash
   uv run pytest
   ```
4. Run linters and type checkers:
   ```bash
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy bot core
   ```
