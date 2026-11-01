# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-23

### Features
- Initial release of Scraping Bot
- Telegram bot for downloading videos from Instagram and Twitter/X
- Dual extractor pipeline: yt-dlp (primary) → gallery-dl (fallback)
- Size and duration limits enforced pre-download
- Concurrency control with semaphore
- Graceful shutdown handling
- Health and metrics endpoints (/health, /metrics)
- Structured JSON logging with rotation
- Webhook and polling modes
- Per-process webhook secret generation
- Allow-list access control with explicit public opt-in

### Bug Fixes
- Fixed malformed allow-list entries causing silent security issues
- Fixed webhook secret persistence across deployments

### Documentation
- Added comprehensive README with configuration table
- Added CONTRIBUTING.md with commit message conventions
- Added .env.example with all configuration options

### Build
- Added multi-stage Dockerfile with non-root user
- Added GitHub Actions CI/CD pipeline
- Added dependency scanning with pip-audit and Trivy
- Added CodeQL security scanning
- Added automated releases with Release Please

[0.1.0]: https://github.com/your-org/scraping-bot/releases/tag/v0.1.0