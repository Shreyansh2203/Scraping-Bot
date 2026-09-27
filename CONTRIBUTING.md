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
