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

## Dependency Scanning

`pip-audit` is part of the dev extras and checks the dependencies declared in
`pyproject.toml` against the PyPA advisory database:

```bash
pip install ".[dev]"
pip-audit --progress-spinner off .
```

CI runs the same command on every push and pull request, and a scheduled weekly
workflow re-runs it against `main` to catch advisories published after a branch was cut.
Pull requests additionally get a dependency review, which fails on a vulnerable or
badly licensed package entering through the diff. Dependabot opens the upgrade PRs for
the Python dependencies, the GitHub Actions, and the Docker base image.

## Pull Request Process

1. Create a descriptive branch name.
2. Ensure you have added or updated tests if adding new functionality.
3. Submit a pull request against the `main` branch.
4. Ensure CI checks pass.

## Releases

Releases are automated. [release-please](https://github.com/googleapis/release-please) runs on
every merge to `main` and opens a release pull request that bumps the version in
`pyproject.toml` and `.release-please-manifest.json` and writes [CHANGELOG.md](CHANGELOG.md).
The changelog is therefore generated, not hand-edited, and it only sees commits that use
[Conventional Commits](https://www.conventionalcommits.org/):

| Commit type | Changelog section |
|---|---|
| `feat` | Added |
| `refactor` | Changed |
| `fix` | Fixed |
| `docs` | Documentation |
| `chore` | Dependencies |

Commits that do not follow the format are skipped entirely, so a commit without a recognised
type or a breaking-change marker will be missing from the release notes.
