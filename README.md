# Scraping Bot

Telegram bot for downloading videos from Instagram and Twitter/X.

Built with Python 3.12+, aiogram 3.x, yt-dlp, and gallery-dl.

## Table of contents

- [Requirements](#requirements)
- [Quick Start](#quick-start)
  - [With Docker](#with-docker)
  - [On Render](#on-render)
- [Configuration](#configuration)
- [Supported URLs](#supported-urls)
- [Architecture](#architecture)
  - [Key Features](#key-features)
- [Health & Metrics](#health--metrics)
- [Security](#security)
- [Development](#development)
  - [Install development dependencies](#install-development-dependencies)
  - [Run tests](#run-tests)
  - [Lint and format](#lint-and-format)
  - [Type check](#type-check)
  - [Pre-commit hooks](#pre-commit-hooks)
- [Deployment](#deployment)
  - [Render (recommended)](#render-recommended)
  - [Other platforms](#other-platforms)
- [License](#license)


## Requirements

- **Python** >= 3.12
- **ffmpeg** (required for yt-dlp to merge separate audio/video streams)
- **uv** (recommended) or pip for dependency management

The Docker image includes ffmpeg. On a host without Docker, install ffmpeg via your package manager (e.g. `apt-get install ffmpeg`, `brew install ffmpeg`, `choco install ffmpeg`).


## Quick Start

```bash
# Clone and enter the repository
git clone https://github.com/your-org/scraping-bot.git
cd scraping-bot

# Install dependencies (uv recommended)
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your BOT_TOKEN and ALLOWED_USERS

# Run the bot
uv run python -m bot.main
```

### With Docker

```bash
docker build -t scraping-bot .
docker run -d \
  -e BOT_TOKEN=your_token \
  -e ALLOWED_USERS=123456789 \
  -p 8080:8080 \
  scraping-bot
```

### On Render

The repository includes a `render.yaml` blueprint. Connect the repository to Render and the service will be created with the correct configuration. You only need to provide `BOT_TOKEN` and `ALLOWED_USERS` in the Render dashboard (both are `sync: false` so they are never overwritten).


## Configuration

All configuration is via environment variables. The bot validates its configuration at startup and refuses to start if required values are missing or malformed.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BOT_TOKEN` | **Yes** | — | Telegram bot token from [@BotFather](https://t.me/BotFather). Format: `<bot_id>:<secret>` |
| `ALLOWED_USERS` | **Yes**¹ | — | Comma-separated Telegram user IDs (e.g. `123456789,987654321`). The only access control. |
| `ALLOW_PUBLIC` | No | `0` | Set to `1` to run a deliberately public bot. **Only do this if anyone who finds the bot is meant to be able to spend your bandwidth, disk and platform quota.** |
| `DOWNLOAD_DIR` | No | `./downloads` | Directory where per-job download directories are created. |
| `CONCURRENT_DOWNLOADS` | No | `2` | Maximum number of downloads running at the same time. |
| `MAX_FILE_SIZE_MB` | No | `50` | Reject single files larger than this. Also passed to yt-dlp as `--max-filesize` so oversized downloads are refused before bytes are written. Telegram Bot API limit is 50 MB. |
| `MAX_DURATION_SECONDS` | No | `600` | Refuse media longer than this many seconds. Enforced from metadata yt-dlp reports before downloading. |
| `HEALTH_PORT` | No | `8080` | Port for the aiohttp health and metrics server. Superseded by `PORT` if set (Render injects `PORT`). |
| `HEALTH_BIND` | No | `127.0.0.1` | Interface the health server binds to. Use `0.0.0.0` inside Docker/Render. |
| `SUBPROCESS_TIMEOUT` | No | `180` | Seconds before an extraction subprocess is killed. |
| `FFPROBE_TIMEOUT` | No | `10` | Seconds before ffprobe is killed when probing resolution. |
| `BOT_MODE` | No | `auto` | Set to `polling` to force long polling. Otherwise a webhook is used when `RENDER_EXTERNAL_HOSTNAME` or `WEBHOOK_URL` is present. |
| `RENDER_EXTERNAL_HOSTNAME` | No | — | Injected by Render at runtime. Used to derive the webhook URL. |
| `WEBHOOK_URL` | No | — | Explicit webhook URL. Takes precedence over the derived one. |

¹ Either `ALLOWED_USERS` (non-empty) or `ALLOW_PUBLIC=1` is required. An empty allow-list without the explicit opt-in stops the bot at startup.


## Supported URLs

- **Instagram**: `instagram.com/reel/...`, `instagram.com/p/...`, `instagram.com/tv/...`, `instagram.com/share/reel/...`
- **Twitter/X**: `x.com/.../status/...`, `twitter.com/.../status/...`, `x.com/i/status/...`


## Architecture

```
Scraping-Bot/
├── bot/
│   ├── main.py                 # Entry point, webhook/polling, health/metrics server
│   ├── handlers/
│   │   ├── commands.py         # /start, /help commands
│   │   └── download.py         # URL detection, download processing, media replies
│   └── middlewares/
│       └── throttle.py         # Rate limiting (1 req/s) + user allow-list auth
├── core/
│   ├── config.py               # Settings from .env with validation
│   └── downloader_wrapper.py   # yt-dlp + gallery-dl orchestration
└── tests/                      # Pytest suite (100% coverage target)
```

### Key Features

- **Dual extractor pipeline**: yt-dlp (primary) → gallery-dl (fallback)
- **Size/duration limits enforced pre-download** via yt-dlp's `--max-filesize` and probe metadata
- **Concurrency control**: semaphore with immediate rejection when slots full (no unbounded queue)
- **Graceful shutdown**: drains active downloads on SIGTERM/SIGINT
- **Health/metrics endpoints**: `/health` (JSON), `/metrics` (Prometheus)
- **Structured JSON logging** with rotation
- **Webhook or polling mode** (auto-detects Render via `RENDER_EXTERNAL_HOSTNAME`)


## Health & Metrics

The bot exposes an aiohttp server on `HEALTH_BIND:HEALTH_PORT`:

- `GET /health` — JSON health check with version, uptime, active downloads, concurrent limit, output directory
- `GET /metrics` — Prometheus-compatible plain text metrics (uptime, active downloads, concurrent limit)


## Security

- **Per-process webhook secret**: Generated at boot with `secrets.token_urlsafe(32)`. Never stored, logged, or configured.
- **Allow-list only access**: No authentication bypass. Empty allow-list = no access unless `ALLOW_PUBLIC=1` is explicitly set.
- **Malformed allow-list entries are fatal**: A typo in `ALLOWED_USERS` stops the bot at startup rather than silently shrinking the list.
- **Non-root Docker user**: Image runs as `botuser` (UID 1000).
- **Input validation**: URLs are validated before being passed to subprocesses.
- **Dependency scanning**: `pip-audit` runs on every PR and weekly on main. Trivy scans the container image on release.
- **CodeQL**: Security and quality queries on Python and GitHub Actions workflows.


## Development

### Install development dependencies

```bash
uv sync --dev
```

### Run tests

```bash
uv run pytest -v --tb=short --cov=bot --cov=core --cov-report=term-missing
```

### Lint and format

```bash
uv run ruff check .
uv run ruff format .
```

### Type check

```bash
uv run mypy bot core
```

### Pre-commit hooks

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```


## Deployment

### Render (recommended)

1. Fork/clone this repository
2. Connect to Render as a **Web Service** using the `render.yaml` blueprint
3. Set `BOT_TOKEN` and `ALLOWED_USERS` in the Render dashboard (Environment Variables)
4. Deploy

The blueprint configures:
- Docker build from the repository `Dockerfile`
- Health check on `/health`
- `HEALTH_BIND=0.0.0.0` for container networking
- `sync: false` for secrets (`BOT_TOKEN`, `ALLOWED_USERS`, `ALLOW_PUBLIC`)

### Other platforms

The bot runs anywhere Python 3.12+ and ffmpeg are available. Set `BOT_MODE=polling` if the platform cannot provide a public HTTPS URL for webhooks.


## License

MIT License — see `LICENSE` for details.