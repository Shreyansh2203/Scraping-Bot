# Architecture

## Overview

Scraping-Bot is a production Telegram bot that downloads videos from Instagram and Twitter/X.

## Components

### Bot (aiogram 3.x)
- Polling mode (default) or webhook mode
- Health server on configurable bind/port
- `/health`, `/metrics`, `/healthz` endpoints

### Core
- `config.py` — pydantic Settings (env-based)
- `downloader_wrapper.py` — yt-dlp/gallery-dl wrapper with resource limits
- `bounds.py` — File size, duration, disk usage bounds
- `output_parser.py` — Output parsing

### Middlewares
- `AuthMiddleware` — User allow-list enforcement
- `ThrottleMiddleware` — Rate limiting (Redis or in-memory)

### Deployment
- Docker: `Dockerfile` + `docker-compose.prod.yml`
- Render: `render.yaml`
- Raw: `python -m bot.main`