# Scraping-Bot

![CI](https://github.com/Shreyansh2203/Scraping-Bot/workflows/CI/badge.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

A production-ready Telegram bot for downloading videos and media from Instagram and Twitter/X. Built with `aiogram 3` and `yt-dlp`.

## Features
- **Instagram**: Downloads Reels and Posts.
- **Twitter/X**: Downloads Videos from tweets.
- **Fast & Async**: Powered by `aiogram` 3.x and `asyncio`.
- **Media Grouping**: Sends multiple media files natively as albums.
- **Size Limits**: Enforces Telegram size limits automatically.

## Requirements
- Python >= 3.11
- `ffmpeg` (required by `yt-dlp` to merge formats)
- A Telegram Bot Token from [@BotFather](https://t.me/botfather)

## Installation

### Using Docker (Recommended)

1. Clone the repository:
   ```bash
   git clone https://github.com/Shreyansh2203/Scraping-Bot.git
   cd Scraping-Bot
   ```
2. Create your `.env` file:
   ```bash
   cp .env.example .env
   # Edit .env with your BOT_TOKEN and ALLOWED_USERS
   ```
3. Build and run:
   ```bash
   docker build -t scraping-bot .
   docker run --env-file .env -p 8080:8080 scraping-bot
   ```

### Manual Installation

1. Install dependencies (make sure `ffmpeg` is installed on your system):
   ```bash
   make install
   ```
2. Run the bot:
   ```bash
   make run
   ```

## Configuration

You can configure the bot via environment variables or a `.env` file.

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | *required* | Your Telegram bot token |
| `DOWNLOAD_DIR` | `./downloads` | Directory to save temporary files |
| `CONCURRENT_DOWNLOADS` | `2` | Number of simultaneous downloads |
| `MAX_FILE_SIZE_MB` | `50` | Maximum file size in MB allowed to send (Telegram limit is 50MB for bots without local API server) |
| `ALLOWED_USERS` | *empty* | Comma-separated list of User IDs. If empty, bot is public. |
| `PORT` or `HEALTH_PORT` | `8080` | Port for the health server and webhook |

## Deployment
This project is configured to be deployed easily on [Render](https://render.com) using the included `render.yaml`. It sets up the webhook automatically based on `RENDER_EXTERNAL_HOSTNAME`.

## Contributing
See [CONTRIBUTING.md](CONTRIBUTING.md).

## License
MIT License.
