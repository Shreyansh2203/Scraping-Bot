# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.x | ✅ |
| < 1.0 | ❌ |

## Reporting a Vulnerability

If you discover a security vulnerability in Scraping-Bot, please report it responsibly.

**Do NOT** open a public GitHub issue for security vulnerabilities.

### How to Report

1. Email: [main.doga@gmail.com](mailto:main.doga@gmail.com) with subject "Scraping-Bot Security Vulnerability"
2. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial assessment**: Within 7 days
- **Fix release**: Within 14 days (critical), 30 days (non-critical)

### Security Measures

- **Token validation**: BOT_TOKEN must match `^\d+:[A-Za-z0-9_-]+$`
- **User allow-list**: ALLOWED_USERS enforcement via AuthMiddleware
- **Public toggle**: ALLOW_PUBLIC=1 opts into public mode (logged as warning)
- **Webhook secret**: Per-process minted secret_token, never logged or persisted
- **Rate limiting**: ThrottleMiddleware with optional Redis backend
- **Resource guards**: File size, duration, and disk-usage caps
- **Dependency audit**: pip-audit --strict in CI
- **Container scan**: Trivy (CRITICAL/HIGH) in CI
- **SAST**: CodeQL on every push

### Disclosure Policy

- Vulnerabilities are disclosed after a fix is released
- Credit is given to the reporter (unless they prefer anonymity)
- Public disclosure timeline: 90 days after fix release

## Security Contacts

- **Maintainer**: Shreyansh Srivastava ([@Shreyansh2203](https://github.com/Shreyansh2203))
- **Email**: main.doga@gmail.com