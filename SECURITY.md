# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

Please report security vulnerabilities privately via [GitHub Security Advisories](https://github.com/your-org/scraping-bot/security/advisories/new).

Do not open a public issue for security vulnerabilities.

## Security Measures

- **Per-process webhook secret**: Generated at boot with `secrets.token_urlsafe(32)`. Never stored, logged, or configured.
- **Allow-list only access**: No authentication bypass. Empty allow-list = no access unless `ALLOW_PUBLIC=1` is explicitly set.
- **Malformed allow-list entries are fatal**: A typo in `ALLOWED_USERS` stops the bot at startup rather than silently shrinking the list.
- **Non-root Docker user**: Image runs as `botuser` (UID 1000).
- **Input validation**: URLs are validated before being passed to subprocesses.
- **Dependency scanning**: `pip-audit` runs on every PR and weekly on main. Trivy scans the container image on release.
- **CodeQL**: Security and quality queries on Python and GitHub Actions workflows.