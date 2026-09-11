# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability, please email **security@example.com** instead of opening a public issue.

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge receipt within 48 hours and provide a detailed response within 7 days.

## Security Best Practices

When deploying this bot:

1. **Never commit `.env`** — use environment variables
2. **Rotate BOT_TOKEN** regularly via @BotFather
3. **Use private bot** (`ALLOWED_USERS`) for personal use
4. **Keep yt-dlp updated** — extractors break frequently
5. **Monitor disk usage** — implement cleanup in production
6. **Use HTTPS** for all external communications
7. **Validate all URLs** — prevent SSRF attacks
8. **Limit file sizes** — respect Telegram's 50MB limit
