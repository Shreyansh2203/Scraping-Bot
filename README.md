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

**Set `ALLOWED_USERS` before you expose the bot.** It is the only access control the bot
has, so the configuration fails closed: an unset, empty, whitespace-only or partly
non-numeric value stops the bot at startup with the offending entry named, rather than
starting and leaving you to notice. A stray comma or a space where a comma should be
used to be enough to turn a private bot into a public one — a public bot is a subprocess
spawner anyone on the internet can queue work for. Put your own Telegram user ID in it,
plus anyone else who needs access. If you do want the bot open, say so with
`ALLOW_PUBLIC=1`; the bot then logs `ALLOWED_USERS is empty and ALLOW_PUBLIC=1; bot is
public` at startup, and that line is still the checkpoint to read before you attach a
public hostname.

**Rate limits and courtesy.** Every download is a request to a server you do not control.
Keep `CONCURRENT_DOWNLOADS` low (default `2`), keep `SUBPROCESS_TIMEOUT` and
`MAX_FILE_SIZE_MB` conservative, and do not stand up a shared instance and circulate the
link. The bot throttles each user to roughly one request per second and bounds concurrency
globally, but neither of those is a licence to hammer an origin. Note that
`SUBPROCESS_TIMEOUT` bounds a single attempt rather than a request: the worst case for one
link is about four times that value, so a slot can be held for many minutes. Rather than
queue behind that — a wait with no timeout of its own — a request that arrives when every
slot is taken is told so immediately and can be retried, so two slow links cannot park the
bot for everyone else. Media over `MAX_FILE_SIZE_MB` or `MAX_DURATION_SECONDS` is refused
before it is fetched: yt-dlp is given `--max-filesize` as a hard ceiling on the transfer,
and the size and duration the extractor already knows decide the rest.

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
| `CONCURRENT_DOWNLOADS` | `2` | Maximum concurrent downloads. A request that arrives when every slot is taken is refused immediately rather than queued, because one request can occupy a slot for up to four times `SUBPROCESS_TIMEOUT` |
| `MAX_FILE_SIZE_MB` | `50` | Maximum size in MB for a single file. Anything above this is rejected **before** the bytes are written, as yt-dlp's `--max-filesize`, and the finished file is still re-checked after the download. Telegram's own limit is type-dependent — 10 MB for a photo, 50 MB for a video, audio and document — and this one flat cap is applied to every media type, so a photo between 10 MB and this value passes here and is refused by Telegram |
| `MAX_DURATION_SECONDS` | `600` | Refuse media longer than this many seconds. Read from the metadata yt-dlp reports before it starts downloading, so a multi-hour stream is rejected in seconds rather than filling the disk. A Reel is 90 s and an X video 140 s, so the default is generous |
| `ALLOWED_USERS` | *unset* | Comma-separated list of Telegram user IDs, e.g. `123456789,987654321`. This is the bot's only access control, so an unset, empty, or partly non-numeric value **stops the bot at startup** rather than quietly leaving it open — see [Scope and responsible use](#scope-and-responsible-use) |
| `ALLOW_PUBLIC` | *unset* | Set to `1` to run a deliberately public bot. It exists so that the safe direction is the one that needs no action: without it, a bot with no allow-list refuses to start |
| `PORT`, then `HEALTH_PORT` | `8080` | Port for the aiohttp health & metrics server. `PORT` is checked first and takes precedence, which is what Render's injected value relies on |
| `HEALTH_BIND` | `127.0.0.1` | Network interface to bind the health server (`0.0.0.0` in Docker) |
| `SUBPROCESS_TIMEOUT` | `180` | Timeout in seconds for **one extraction attempt**, which also bounds the process tree (`ffmpeg` included). A request makes up to three `yt-dlp` attempts plus one `gallery-dl` attempt, so the worst case for a single link is roughly four times this — which is why a saturated bot sheds load instead of queueing it |
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
  scraping_bot_uptime_seconds 3600.0
  scraping_bot_active_downloads 1
  scraping_bot_concurrent_limit 2
  ```

`POST /webhook` is the third route, and it is not a public API. Telegram echoes the
secret the bot registered with `set_webhook` in the `X-Telegram-Bot-Api-Secret-Token`
header of every delivery, and the bot refuses any request without it. The secret is
generated at process start from the OS CSPRNG and lives only in memory: there is nothing
to configure, nothing to rotate and nothing to commit, and a request that does not come
from Telegram never reaches the dispatcher. Restarting the bot mints a new one and
re-registers it with Telegram during startup.

---

## Deployment on Render

This repository includes a `render.yaml` blueprint:
1. Connect your repository on [Render](https://render.com).
2. When prompted, set the `BOT_TOKEN` secret and the `ALLOWED_USERS` allow-list. A
   deploy with no allow-list refuses to start; that is the intended behaviour.
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
| [Oracle Fusion Product Comparison Advisor](https://github.com/Shreyansh2203/Product-Comparison-Advisor---AI-Agent) | Agent configuration for automating product-comparison workflows in Oracle Fusion Supply Chain Management. |

## License

[MIT License](LICENSE).
