# Scraping Bot

[![CI](https://github.com/Shreyansh2203/Scraping-Bot/actions/workflows/ci.yml/badge.svg)](https://github.com/Shreyansh2203/Scraping-Bot/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Telegram bot for downloading videos from Instagram and Twitter/X at maximum available quality.

## Features

- Download Instagram reels/posts and Twitter/X videos
- Best available quality selection
- Concurrent downloads with rate limiting
- Auto-cleanup of files after sending
- Browser cookie support for restricted content
- State persistence and resume support
- Docker-ready for Render/Railway deployment
- Health check endpoint
- Structured JSON logging

## Quick Start

```bash
git clone https://github.com/Shreyansh2203/Scraping-Bot.git
cd Scraping-Bot
cp .env.example .env
# Edit .env with your BOT_TOKEN
pip install -r requirements.txt
python -m bot.main
```

## Deployment

See [README_BOT.md](README_BOT.md) for Render deployment instructions.

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run linting
ruff check .
black .
mypy --strict bot/ core/

# Run tests with coverage
pytest --cov=bot --cov=core
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Branch Protection

The `main` branch is protected. All changes require:
- Passing CI checks (lint, tests, Docker build)
- At least one approving review
- All conversations resolved

## Architecture

```
telegram-bot/
├── bot/                 # Aiogram handlers and middlewares
├── core/                # Downloader wrapper and config
├── tests/               # Unit tests
├── downloads/           # Temporary download directory
├── Dockerfile           # Production container
├── render.yaml          # Render deployment config
├── pyproject.toml       # Project metadata and tools
└── requirements.txt     # Python dependencies
```

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## Security

See [SECURITY.md](SECURITY.md) for security policy and vulnerability reporting.

## License

MIT — see [LICENSE](LICENSE)
