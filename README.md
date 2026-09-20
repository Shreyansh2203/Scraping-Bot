# Scraping-Bot

[![CI](https://github.com/Shreyansh2203/Scraping-Bot/workflows/CI/badge.svg)](https://github.com/Shreyansh2203/Scraping-Bot/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](pyproject.toml)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A mission-critical, enterprise-grade Telegram bot for downloading and streaming media from Instagram and Twitter/X. Built with `aiogram 3`, `yt-dlp`, and `gallery-dl`.

---

## Architecture

```mermaid
flowchart TD
    User([Telegram User]) <-->|Webhook / Long Polling| TG[Telegram Bot API]
    TG <--> AI[aiogram 3 Dispatcher]
    
    subgraph Middlewares
        MW1[AuthMiddleware] --> MW2[ThrottleMiddleware (TTL Cache)]
    end
    
    AI --> Middlewares
    Middlewares --> Router[Download Router / Commands]
    
    subgraph Core Engine
        Router --> TaskRegistry[active_tasks Registry]
        TaskRegistry --> DW[DownloaderWrapper]
        DW -->|Job Dir Isolation| JobDir[downloads/job_uuid/]
        JobDir --> YTDLP[yt-dlp Subprocess]
        JobDir -->|Fallback| GDL[gallery-dl Subprocess]
        JobDir --> FFP[ffprobe Resolution Probe]
    end
    
    subgraph Observability
        HealthSrv[aiohttp Health Server]
        HealthSrv --> HealthEndpoint["/health (JSON Status)"]
        HealthSrv --> MetricsEndpoint["/metrics (Prometheus)"]
    end
    
    JobDir --> MediaDelivery[Batch Media Delivery (<= 10 per album)]
    MediaDelivery --> TG
```

---

## Features

- **Instagram**: Downloads Reels, Posts, and Carousels.
- **Twitter/X**: Downloads Videos and GIFs from tweets.
- **Concurrency Isolation**: Every download runs inside an ephemeral, dedicated job directory (`downloads/job_{uuid}/`), eliminating race conditions and media cross-talk.
- **Automatic Album Chunking**: Carousels exceeding Telegram's 10-item limit are automatically partitioned and delivered in consecutive albums.
- **Resilient Fallback**: Primary extraction via `yt-dlp` with automatic exponential backoff retry and secondary fallback to `gallery-dl`.
- **Memory-Safe Rate Limiting**: Bounded TTL in-memory rate limiter evicts expired timestamps to prevent memory leaks.
- **Observability**: Built-in `/health` status and Prometheus-compatible `/metrics` endpoints.
- **Security & RBAC**: Optional user-level access restriction via `ALLOWED_USERS`.

---

## Requirements

- Python >= 3.11
- `ffmpeg` (required by `yt-dlp` to merge audio/video streams)
- Telegram Bot Token from [@BotFather](https://t.me/botfather)

---

## Installation

### Using Docker (Recommended)

1. Clone the repository:
   ```bash
   git clone https://github.com/Shreyansh2203/Scraping-Bot.git
   cd Scraping-Bot
   ```
2. Configure your environment:
   ```bash
   cp .env.example .env
   # Edit .env with your BOT_TOKEN and ALLOWED_USERS
   ```
3. Build and launch:
   ```bash
   docker build -t scraping-bot .
   docker run --env-file .env -p 8080:8080 scraping-bot
   ```

### Local Development

1. Install dependencies:
   ```bash
   make dev
   ```
2. Run linters and tests:
   ```bash
   make lint
   make test
   ```
3. Run the bot:
   ```bash
   make run
   ```

---

## Configuration

Configure the application via environment variables or a `.env` file:

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | *required* | Telegram Bot API token from @BotFather |
| `DOWNLOAD_DIR` | `./downloads` | Directory to store temporary job directories |
| `CONCURRENT_DOWNLOADS` | `2` | Maximum concurrent downloads allowed |
| `MAX_FILE_SIZE_MB` | `50` | Maximum file size in MB (Telegram Bot API limit is 50MB) |
| `ALLOWED_USERS` | *empty* | Comma-separated list of Telegram user IDs (empty = public bot) |
| `PORT` or `HEALTH_PORT` | `8080` | Port for the aiohttp health & metrics server |
| `HEALTH_BIND` | `127.0.0.1` | Network interface to bind the health server (`0.0.0.0` in Docker) |
| `SUBPROCESS_TIMEOUT` | `180` | Timeout in seconds for extraction subprocesses |
| `FFPROBE_TIMEOUT` | `10` | Timeout in seconds for ffprobe metadata probing |
| `RENDER_EXTERNAL_HOSTNAME`| *empty* | If set, switches bot from long polling to webhook mode |

---

## Observability

The application exposes two HTTP endpoints on the configured health port (default `8080`):

- **`GET /health`**: Returns JSON status, uptime, concurrency limit, and active download count.
- **`GET /metrics`**: Prometheus-formatted metrics:
  ```text
  scraping_bot_uptime_seconds 3600.00
  scraping_bot_active_downloads 1
  scraping_bot_concurrent_limit 2
  ```

---

## Deployment on Render

This repository includes a `render.yaml` blueprint:
1. Connect your repository on [Render](https://render.com).
2. Set the `BOT_TOKEN` secret in the Render dashboard.
3. The webhook URL is configured automatically via `RENDER_EXTERNAL_HOSTNAME`.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflows and coding standards.

## License

[MIT License](LICENSE).
