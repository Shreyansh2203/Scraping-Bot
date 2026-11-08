# Scraping-Bot

<div align="center">

[![Build Status](https://img.shields.io/github/actions/workflow/status/Shreyansh2203/Scraping-Bot/ci.yml?branch=main&label=CI&logo=github-actions&style=for-the-badge)](https://github.com/Shreyansh2203/Scraping-Bot/actions)
[![CodeQL](https://img.shields.io/github/actions/workflow/status/Shreyansh2203/Scraping-Bot/codeql.yml?branch=main&label=CodeQL&logo=github&style=for-the-badge)](https://github.com/Shreyansh2203/Scraping-Bot/security/code-scanning)
[![Container Scan](https://img.shields.io/github/actions/workflow/status/Shreyansh2203/Scraping-Bot/trivy.yml?branch=main&label=Trivy&logo=docker&style=for-the-badge)](https://github.com/Shreyansh2203/Scraping-Bot/actions/workflows/trivy.yml)
[![Dependency Audit](https://img.shields.io/github/actions/workflow/status/Shreyansh2203/Scraping-Bot/dependency-audit.yml?branch=main&label=pip-audit&logo=python&style=for-the-badge)](https://github.com/Shreyansh2203/Scraping-Bot/actions/workflows/dependency-audit.yml)
[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg?style=for-the-badge)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-blue?style=for-the-badge&logo=python)](https://www.python.org/)
[![aiogram](https://img.shields.io/badge/aiogram-3.x-blue?style=for-the-badge)](https://docs.aiogram.dev/)
[![yt-dlp](https://img.shields.io/badge/yt--dlp-latest-green?style=for-the-badge)](https://github.com/yt-dlp/yt-dlp)

</div>

## Table of contents

- [Overview](#overview)
- [Features](#features)
- [Requirements](#requirements)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Endpoints](#endpoints)
- [Security](#security)
- [Testing](#testing)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

**Scraping-Bot** is a production Telegram bot that downloads videos from Instagram and Twitter/X. Built with [aiogram](https://docs.aiogram.dev/) and [yt-dlp](https://github.com/yt-dlp/yt-dlp), it runs in polling or webhook mode, serves a health/metrics HTTP server, and enforces auth + throttle middleware with optional Redis backing.

Production-ready: version `1.0.0`, `Development Status :: 5 - Production/Stable`, 270 tests at 100% coverage, Docker + Render-ready.

---

## Features

| Feature | Description |
|---------|-------------|
| **Telegram bot** | aiogram 3.x, HTML parse mode, polling or webhook mode |
| **Video downloads** | Instagram + Twitter/X via yt-dlp + gallery-dl |
| **Dual health server** | `/health`, `/metrics`, `/healthz` on configurable bind/port |
| **Auth middleware** | `ALLOWED_USERS` allow-list or `ALLOW_PUBLIC=1` |
| **Throttle middleware** | Redis-backed or in-memory rate limiting |
| **Resource guards** | `MAX_FILE_SIZE_MB`, `MAX_DURATION_SECONDS`, `MAX_DISK_USAGE_PERCENT` |
| **Concurrent downloads** | Tunable `CONCURRENT_DOWNLOADS` |
| **Webhook secret** | Per-process minted `secret_token` (never logged or persisted) |
| **Graceful shutdown** | Download drain + resource cleanup on SIGTERM/SIGINT |
| **100% test coverage** | 270 tests passing |

---

## Requirements

- Python 3.12+
- ffmpeg (required by yt-dlp to merge separate audio and video streams)
- A Telegram bot token from [@BotFather](https://t.me/botfather)

---

## Tech Stack

<details>
<summary><b>Runtime</b></summary>

- [Python 3.12+](https://www.python.org/)
- [aiogram 3.x](https://docs.aiogram.dev/) — Telegram Bot API framework
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — video downloader
- [gallery-dl](https://github.com/mikf/gallery-dl) — gallery downloader
- [aiohttp](https://docs.aiohttp.org/) — health HTTP server
- [python-dotenv](https://pypi.org/project/python-dotenv/) — env loading

</details>

<details>
<summary><b>Dev / Security</b></summary>

- [pytest](https://docs.pytest.org/) + [pytest-asyncio](https://pytest-asyncio.readthedocs.io/) — testing
- [pytest-cov](https://pypi.org/project/pytest-cov/) — coverage
- [ruff](https://docs.astral.sh/ruff/) — lint + format
- [mypy](http://mypy.readthedocs.io/) — static typing (scoped to `bot`/`core`)
- [pip-audit](https://pypa.github.io/pip-audit/) — dependency audit
- [Trivy](https://aquasecurity.github.io/trivy/) — container vulnerability scan

</details>

---

## Project Structure

```
Scraping-Bot/
├── bot/
│   ├── main.py                 # entry: health server + polling/webhook
│   ├── handlers/
│   │   ├── commands.py         # /start, /help, etc.
│   │   └── download.py         # download handlers
│   └── middlewares/
│       └── throttle.py         # auth + throttle middleware
├── core/
│   ├── config.py               # pydantic Settings (env-based)
│   ├── downloader_wrapper.py   # yt-dlp/gallery-dl wrapper + limits
│   ├── bounds.py               # size/duration/disk bounds
│   └── output_parser.py
├── tests/                      # 270 tests, 100% coverage
├── .github/workflows/
│   ├── ci.yml, codeql.yml, dependency-audit.yml, release.yml, trivy.yml
├── Dockerfile
├── docker-compose.prod.yml
├── render.yaml
├── pyproject.toml
├── uv.lock
├── .env.example
└── LICENSE
```

---

## Quick Start

**Prerequisites**

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)
- A Telegram bot token from [@BotFather](https://t.me/botfather)

**Install & Run**

```bash
cd Scraping-Bot

# Create venv
uv venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install
uv sync

# Configure environment
cp .env.example .env
# Edit .env: set BOT_TOKEN=123456:ABC-DEF... (real BotFather token)

# Run in polling mode (default, no public URL needed)
BOT_TOKEN="123456:ABC-DEF..." \
ALLOW_PUBLIC="1" \
HEALTH_PORT="8080" \
HEALTH_BIND="127.0.0.1" \
python -m bot.main
```

Verify:

```bash
curl http://127.0.0.1:8080/health
# {"status":"ok","version":"1.0.0","active_downloads":0,...}
```

**Run with Docker**

```bash
docker build -t scraping-bot .
docker run -p 8080:8080 -e BOT_TOKEN="..." scraping-bot
```

Or via docker-compose:

```bash
docker compose -f docker-compose.prod.yml up --build
```

---

## Configuration

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `BOT_TOKEN` | — | Yes | Telegram bot token from @BotFather |
| `ALLOW_PUBLIC` | `0` | No | `1` = allow all users; `0` = allow-list only |
| `ALLOWED_USERS` | `""` | No | Comma-separated allowed Telegram user IDs |
| `WEBHOOK_URL` | `""` | No | Set for webhook mode; empty = polling |
| `RENDER_EXTERNAL_HOSTNAME` | `""` | No | Auto-derives webhook URL on Render |
| `HEALTH_PORT` | `8080` | No | Health server port |
| `HEALTH_BIND` | `0.0.0.0` | No | Health server bind address |
| `BOT_MODE` | `polling` | No | `polling` or `webhook` |
| `DOWNLOAD_DIR` | `downloads` | No | Download output directory |
| `CONCURRENT_DOWNLOADS` | `2` | No | Max concurrent downloads |
| `MAX_FILE_SIZE_MB` | `2000` | No | Max file size per download |
| `MAX_DURATION_SECONDS` | `3600` | No | Max video duration |
| `MAX_DISK_USAGE_PERCENT` | `85` | No | Max disk usage before refusal |
| `SUBPROCESS_TIMEOUT` | `300` | No | yt-dlp subprocess timeout |
| `FFPROBE_TIMEOUT` | `30` | No | ffprobe timeout |

All settings load via pydantic `Settings.validate()` — `BOT_TOKEN` is required and must match `<bot_id>:<secret>`.

---

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Service status, version, uptime, concurrent downloads |
| `/metrics` | GET | Prometheus-formatted metrics |
| `/healthz` | GET | Deep health (extractors, ffprobe, disk headroom) |
| `/webhook` | POST | Telegram webhook (when `WEBHOOK_URL` set) |

---

## Security

| Control | Implementation |
|---------|---------------|
| **Token validation** | `BOT_TOKEN` must match `^\d+:[A-Za-z0-9_-]+$` |
| **User allow-list** | `ALLOWED_USERS` enforcement via `AuthMiddleware` |
| **Public toggle** | `ALLOW_PUBLIC=1` opts into public mode (logged as warning) |
| **Webhook secret** | Per-process minted `secret_token`, never logged or persisted |
| **Rate limiting** | `ThrottleMiddleware` with optional Redis backend |
| **Resource guards** | File size, duration, and disk-usage caps |
| **Dependency audit** | `pip-audit --strict` in CI |
| **Container scan** | `Trivy` (CRITICAL/HIGH) in CI |

---

## Testing

```bash
# Full test suite (270 tests, 100% coverage)
uv run pytest tests/ -q

# With coverage
uv run pytest tests/ --cov=bot --cov=core --cov-report=term-missing

# Lint + format
uv run ruff check . && uv run ruff format --check .

# Type check (scoped)
uv run mypy bot core

# Dependency audit
uv run pip-audit --strict --requirement requirements.txt
```

CI enforces: `ruff` clean, `mypy` clean, `pytest` 270/270, `pip-audit` clean, `Trivy` CRITICAL/HIGH clean.

---

## Deployment

| Platform | Target |
|----------|--------|
| **Render** | `render.yaml` (pre-configured) |
| **Docker** | `Dockerfile` + `docker-compose.prod.yml` |
| **Raw** | `python -m bot.main` |

**Production requirements:**
- Real Telegram bot token from @BotFather
- `ALLOW_PUBLIC=0` with a real `ALLOWED_USERS` list (recommended)
- Redis for `ThrottleMiddleware` in multi-instance deployments
- TLS termination + public URL if using webhook mode

---

## Contributing

1. Fork the repo
2. Create a feature branch (`git checkout -b feat/your-feature`)
3. Run checks: `ruff check .`, `ruff format --check .`, `mypy bot core`, `pytest tests/`
4. Commit and open a Pull Request

---

## License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.

---

<div align="center">

**Made with ❤️ by [Shreyansh Srivastava](https://github.com/Shreyansh2203)**

[![GitHub stars](https://img.shields.io/github/stars/Shreyansh2203/Scraping-Bot?style=social)](https://github.com/Shreyansh2203/Scraping-Bot/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/Shreyansh2203/Scraping-Bot?style=social)](https://github.com/Shreyansh2203/Scraping-Bot/network)

</div>