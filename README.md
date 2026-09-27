# Scraping-Bot

[![CI](https://github.com/Shreyansh2203/Scraping-Bot/workflows/CI/badge.svg)](https://github.com/Shreyansh2203/Scraping-Bot/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](pyproject.toml)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Docker](https://img.shields.io/badge/docker-gHCR-2496ED?logo=docker&logoColor=white)](https://github.com/Shreyansh2203/Scraping-Bot/pkgs/container/scraping-bot)

Telegram bot that downloads the media behind an Instagram or Twitter/X link.

## Scope and responsible use

**What it is.** A self-hosted Telegram bot. You send it an Instagram or X/Twitter link, it
extracts the media behind that link with `yt-dlp` (falling back to `gallery-dl`), and it
sends the file back to the chat it came from. That is the whole feature set: one link in,
one file or album out.

**What it is not.**

- It is not a bulk downloader. There is no batch mode, no profile or hashtag crawling, no
  media library, and no scheduling. One message yields at most one post's media.
- It does not defeat authentication, paywalls, DRM, or age gates. If a platform refuses a
  request the bot reports the failure; it does not try to route around it.
- It stores nothing. Each job gets a throwaway directory that is deleted once the file has
  been delivered, successfully or not.

**Use it on media you are allowed to download** — your own uploads, content you have
permission or a licence to fetch, and material published under terms that allow it.
Downloading media in bulk generally conflicts with Instagram's and X's Terms of Use, and
depending on your jurisdiction and the content it can engage other law as well. Deciding
what you are entitled to fetch is the operator's responsibility: nothing in this code
checks ownership, and none of this is legal advice.

**Set `ALLOWED_USERS` before you expose the bot.** Left empty, the allow-list makes the bot
public — any Telegram account that finds it can spend your bandwidth, disk, and platform
quota. Put your own Telegram user ID in it, plus anyone else who needs access. The bot logs
`ALLOWED_USERS is empty; bot is public` at startup; treat that line as the checkpoint
before you attach a public hostname.

**Rate limits and courtesy.** Every download is a request to a server you do not control.
Keep `CONCURRENT_DOWNLOADS` low (default `2`), keep `SUBPROCESS_TIMEOUT` and
`MAX_FILE_SIZE_MB` conservative, and do not stand up a shared instance and circulate the
link. The bot throttles each user to roughly one request per second and bounds concurrency
globally, but neither of those is a licence to hammer an origin.

## Table of contents

- [Scope and responsible use](#scope-and-responsible-use)
- [The problem](#the-problem)
- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
  - [Using Docker (Recommended)](#using-docker-recommended)
  - [Local Development](#local-development)
- [Configuration](#configuration)
- [Observability](#observability)
- [Deployment on Render](#deployment-on-render)
- [Contributing](#contributing)
- [Portfolio](#portfolio)
- [License](#license)

## The problem

Instagram and X ship no way to save a post's media. Saving a Reel or a tweet video
means either the official app's single-item, single-post flow or a third-party site
that keeps the file, wraps it in ads, and is frequently blocked from a datacenter IP.
For a carousel or an album of clips there is no batch option at all: every item has
to be saved by hand, one message at a time.

## What it does

Paste a link into a Telegram chat and the bot sends the media back, as a single file
or as an album. It extracts with `yt-dlp`, retries transient failures with exponential
backoff, and falls back to `gallery-dl` when Instagram or X refuses the request. Each
download runs in its own throwaway directory, so concurrent jobs cannot collide.
Carousels larger than Telegram's 10-item album limit are split into consecutive albums.

The service runs as a single container, exposes `/health` and Prometheus `/metrics`,
and can be restricted to a list of Telegram user IDs with `ALLOWED_USERS`.

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
| `MAX_FILE_SIZE_MB` | `50` | Maximum size in MB for a single file; anything larger is rejected after download (Telegram Bot API limit is 50MB) |
| `ALLOWED_USERS` | *empty* | Comma-separated list of Telegram user IDs. **Empty means a public bot** — set it before exposing the bot, see [Scope and responsible use](#scope-and-responsible-use) |
| `PORT`, then `HEALTH_PORT` | `8080` | Port for the aiohttp health & metrics server. `PORT` is checked first and takes precedence, which is what Render's injected value relies on |
| `HEALTH_BIND` | `127.0.0.1` | Network interface to bind the health server (`0.0.0.0` in Docker) |
| `SUBPROCESS_TIMEOUT` | `180` | Timeout in seconds for extraction subprocesses |
| `FFPROBE_TIMEOUT` | `10` | Timeout in seconds for ffprobe metadata probing |
| `BOT_MODE` | *empty* | Set to `polling` to force long polling and ignore `WEBHOOK_URL`; useful for local development or hosts without a public URL |
| `WEBHOOK_URL` | *derived* | Overrides the webhook endpoint. Defaults to `https://$RENDER_EXTERNAL_HOSTNAME/webhook` when that is set, otherwise empty (long polling) |
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
2. When prompted, set the `BOT_TOKEN` secret and the `ALLOWED_USERS` allow-list.
   An empty allow-list deploys a public bot.
3. The webhook URL is configured automatically via `RENDER_EXTERNAL_HOSTNAME`.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflows and coding standards, and
[SECURITY.md](SECURITY.md) for how to report a vulnerability and what to expect when
running the bot against untrusted media.

## Portfolio

Part of a small set of personal projects:

| Repository | What it is |
|---|---|
| [Merge-TIFF](https://github.com/Shreyansh2203/Merge-TIFF) | Browser tool that merges multiple TIFF images into a single multi-page `.tif`; a serverless function does the work with Pillow so the page never handles the files directly. |
| [Oracle BIP Reconciler](https://github.com/Shreyansh2203/oracle-bip-reconciler) | FastAPI service that reconciles payment and remittance ledger rows — often OCR of a paper advice — against invoice and receipt history in Oracle Fusion ERP Cloud BI Publisher. |
| [OTL Timesheet Assistant](https://github.com/Shreyansh2203/OTL-Voice) | React/FastAPI PWA that turns a spoken shift description into a validated timecard proposal for Oracle Fusion Cloud Time and Labour; nothing is written to Oracle until you approve it. |
| [Oracle Fusion Product Comparison Advisor](https://github.com/Shreyansh2203/Product-Comparison-Advisor-AI-Agent) | Agent configuration for automating product-comparison workflows in Oracle Fusion Supply Chain Management. |

## License

[MIT License](LICENSE).
