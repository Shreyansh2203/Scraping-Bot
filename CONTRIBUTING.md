# Contributing

Thank you for contributing to Scraping Bot! This document explains how to submit changes effectively.

## Commit Messages

This project uses [Conventional Commits](https://www.conventionalcommits.org/) to generate the changelog automatically. Every commit message must follow the format:

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

### Types

| Type | Section in the changelog | Description |
|------|-------------------------|-------------|
| `feat` | Features | A new feature |
| `fix` | Bug Fixes | A bug fix |
| `refactor` | Refactoring | Code change that neither fixes a bug nor adds a feature |
| `docs` | Documentation | Documentation only changes |
| `chore` | Chores | Routine tasks, maintenance |
| `chore(deps)` | Dependency Updates | Dependency updates |
| `test` | Tests | Adding or modifying tests |
| `ci` | CI | Changes to CI configuration |
| `build` | Build | Changes to build system or external dependencies |
| `perf` | Performance | Performance improvements |
| `style` | Code Style | Formatting, missing semicolons, etc. (no logic change) |

### Scopes (optional but recommended)

- `bot` — changes in `bot/`
- `core` — changes in `core/`
- `tests` — changes in `tests/`
- `docker` — changes to `Dockerfile` or `.dockerignore`
- `deps` — dependency updates
- `config` — configuration changes

### Examples

```
feat(bot): add support for Instagram carousel posts

fix(core): handle yt-dlp probe timeout correctly

refactor(bot): extract download handler into separate module

docs: update README with new configuration options

chore(deps): update yt-dlp to 2026.8.19

test(core): add test for bound probe parsing

ci: add CodeQL security scan workflow
```

## Pull Requests

1. **Branch from `main`** — Create a feature branch with a descriptive name.
2. **Write tests** — New functionality needs tests. Bug fixes need regression tests.
3. **Run the checks** — Before pushing, run:
   ```bash
   uv run ruff check .
   uv run ruff format .
   uv run mypy bot core
   uv run pytest -v --tb=short
   ```
4. **Keep PRs focused** — One logical change per PR. Large changes should be split.
5. **Update documentation** — If you change configuration or behavior, update `README.md` and relevant docs.

## Code Style

- **Formatter**: Ruff (`uv run ruff format .`)
- **Linter**: Ruff (`uv run ruff check .`)
- **Type checker**: Mypy strict mode (`uv run mypy bot core`)
- **Line length**: 100 characters
- **Python version**: 3.12+ (3.13 supported)

## Testing

```bash
# Run all tests with coverage
uv run pytest -v --tb=short --cov=bot --cov=core --cov-report=term-missing

# Run a specific test file
uv run pytest tests/test_config.py -v

# Run tests matching a pattern
uv run pytest -k "test_settings" -v
```

Target: **100% coverage** on `bot/` and `core/`. The CI enforces a 98% floor.

## Dependency Updates

Dependencies are managed with `uv`. To update:

```bash
# Update all dependencies to latest compatible versions
uv lock --upgrade

# Update a specific package
uv lock --upgrade-package yt-dlp

# Sync the environment
uv sync --dev
```

Always run the full test suite after updating dependencies.

## Security

- **Never commit secrets** — Use environment variables and `.env` (gitignored).
- **Report vulnerabilities privately** — See `SECURITY.md` (if present) or open a private security advisory on GitHub.
- **Dependencies are scanned** — `pip-audit` runs on every PR and weekly. Trivy scans the container image on release.

## Release Process

Releases are automated via [Release Please](https://github.com/googleapis/release-please):

1. Commits to `main` are analyzed for Conventional Commit types
2. A release PR is created/updated with the proposed version bump and changelog
3. When the release PR is merged, a GitHub Release is created and the Docker image is published to GHCR

You don't need to manually tag or version — the conventional commits drive it.

## Questions?

Open an issue or start a discussion. We're happy to help!