# Telegram Video Downloader Bot

A Telegram bot that downloads videos from Instagram and Twitter/X.

## Local Setup

```bash
cp .env.example .env
# Edit .env with your BOT_TOKEN
pip install -r requirements.txt
python -m bot.main
```

## Render Deployment

1. Push this repo to GitHub
2. Create a new **Web Service** on Render
3. Connect your repo
4. Render will detect `render.yaml` and deploy automatically
5. Set `BOT_TOKEN` in Render environment variables
6. Deploy

The bot runs as a long-lived web service on Render's free tier.

## Usage

Send any Instagram reel/post URL or Twitter/X status URL to the bot.

## Notes

- Instagram may rate-limit anonymous access. Use `--cookies-from-browser` locally if needed.
- Telegram has a 50MB file size limit.
- Download speed depends on yt-dlp extractor availability.
