# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0](https://github.com/Shreyansh2203/Scraping-Bot/compare/scraping-bot-v0.1.0...scraping-bot-v0.2.0) (2026-09-20)


### Added

* add CodeQL, dependency review, CODEOWNERS, release automation, and repo metadata ([ffbf84a](https://github.com/Shreyansh2203/Scraping-Bot/commit/ffbf84ab1d31be2602ca9f8a59e8b7721a52e2c6))
* add fallback handler, expand URL regex for reels/tv/share, support BOT_MODE=polling ([2e66aee](https://github.com/Shreyansh2203/Scraping-Bot/commit/2e66aee0257bcbc13d8388ccca26a2b534a58c86))
* harden production readiness and Omega Standard compliance ([b834894](https://github.com/Shreyansh2203/Scraping-Bot/commit/b834894dd81127e02a0400395bceac91ea9685b4))
* integrate gallery-dl to support image downloading ([82cf9e0](https://github.com/Shreyansh2203/Scraping-Bot/commit/82cf9e0ff7a818b88a50f6802909dc0d47e28e7e))
* make project production-ready and adopt open-source standards ([233bf0d](https://github.com/Shreyansh2203/Scraping-Bot/commit/233bf0d698ec0684cb36afbf05ebd01e80a27e79))
* productionize repo with tests, CI, health endpoint, and structured logging ([d5563b2](https://github.com/Shreyansh2203/Scraping-Bot/commit/d5563b2d7ebf7d18cc2ff5421261cd12b0747401))
* remove deduplication check to allow downloading the same link multiple times ([af41bcd](https://github.com/Shreyansh2203/Scraping-Bot/commit/af41bcda6af5e0bb2897f4cfc35268b9d414e828))
* send original media as photos and videos instead of documents ([60fb3f8](https://github.com/Shreyansh2203/Scraping-Bot/commit/60fb3f8338223a157eb658199200154a7c8ba3eb))


### Changed

* Switch to Webhooks on Render and remove state_file ([dea8fb9](https://github.com/Shreyansh2203/Scraping-Bot/commit/dea8fb9cc090e641e782b7e41a419f5c6a627279))


### Fixed

* add timestamp to yt-dlp output to avoid persistent disk caching on Render ([bf7989d](https://github.com/Shreyansh2203/Scraping-Bot/commit/bf7989dbd2eb03cfe61834f6e66d988d208235de))
* attach middlewares to dp.message instead of dp.update ([3037e5b](https://github.com/Shreyansh2203/Scraping-Bot/commit/3037e5bdaa7c7df755282c4ac1bf7bfe8717162d))
* **ci:** resolve POSIX pathlib mocking and test timing issues ([37d7b12](https://github.com/Shreyansh2203/Scraping-Bot/commit/37d7b12ba28c986f8fb4594cbcc909888aa4af0b))
* correct release-please manifest key ([ec3d219](https://github.com/Shreyansh2203/Scraping-Bot/commit/ec3d219e2862e80ed87b0fd0d9939c88e2457a94))
* **download:** escape html entities in url captions ([7fa0132](https://github.com/Shreyansh2203/Scraping-Bot/commit/7fa013260622f908e25c9d92a84ded11087161a6))
* **download:** initialize InputMedia with caption directly to support frozen models ([ec9f32f](https://github.com/Shreyansh2203/Scraping-Bot/commit/ec9f32f5548e3e21cbaaf0ae7a4380baad1ce7d4))
* expose health server for Render deployments ([9ab2976](https://github.com/Shreyansh2203/Scraping-Bot/commit/9ab2976f3b74cbbaa721878c98f956827843b9cd))
* force yt-dlp to use twitter syndication API to bypass datacenter IP restrictions ([440fdb1](https://github.com/Shreyansh2203/Scraping-Bot/commit/440fdb19bfd50a339dfaad90cc1366a1e4138565))
* resolve linting errors and deprecation warnings ([ff50d15](https://github.com/Shreyansh2203/Scraping-Bot/commit/ff50d158f1fa07ee1114ea4bc08b3dfcb3a7f7dc))
* run downloads in background task to avoid webhook timeout ([05aa27b](https://github.com/Shreyansh2203/Scraping-Bot/commit/05aa27bdfe923c3113f222ed1d2e0f6411901bc5))
* **webhook:** preserve pending updates on startup so cold-start messages are delivered ([df1347c](https://github.com/Shreyansh2203/Scraping-Bot/commit/df1347ca6f6965c0c991607eac3eec7b7b33ff6b))
* yt-dlp format sorting on Render penalizes unknown codecs, use size-based sorting ([c36419a](https://github.com/Shreyansh2203/Scraping-Bot/commit/c36419a9cef173249b57fc0394b0765e4f152c0e))
* yt-dlp selecting lower bitrate video-only streams over higher bitrate pre-merged streams ([9b3b6c0](https://github.com/Shreyansh2203/Scraping-Bot/commit/9b3b6c038ff6dac5fdd69c69509c414a8b11c945))


### Dependencies

* remove obsolete data files and legacy scripts ([3ef2d10](https://github.com/Shreyansh2203/Scraping-Bot/commit/3ef2d1035b1261e9a07996c6e7200a36e90b0793))
* trigger release pipeline ([6815889](https://github.com/Shreyansh2203/Scraping-Bot/commit/6815889b5c677341232ea4b156cd5416268cda27))

## [0.1.0] - 2026-09-21

### Added
- **Concurrency Isolation**: Per-request ephemeral job directories (`downloads/job_{uuid}/`) preventing cross-talk.
- **Resilient Fallback**: Automatic retry loop for transient extraction errors with secondary fallback to `gallery-dl`.
- **Album Chunking**: Automatic batching of media groups exceeding 10 items into sequential albums.
- **Memory-Safe Rate Limiting**: `ThrottleMiddleware` equipped with bounded TTL cache to prevent memory leaks.
- **Prometheus Observability**: `/metrics` endpoint on the aiohttp health server exposing uptime, concurrency, and active tasks.
- **Graceful Shutdown**: Task draining for active downloads on SIGTERM / application exit.
- **Developer Experience**: Added `.devcontainer/devcontainer.json` for 1-click VS Code and Codespaces onboarding.
- **Repository Governance**: Added `.github/CODEOWNERS`, updated `SECURITY.md` with disclosure policy and SLA, and enriched `README.md` with Mermaid diagrams.
- **Test Suite**: Comprehensive test suite achieving 89.18% coverage (exceeding the 80% threshold).

### Changed
- **Middleware Ordering**: `AuthMiddleware` now executes before `ThrottleMiddleware`.
- **Dependency Optimization**: Pruned unused `browser-cookie3` and `aiosqlite` dependencies.
- **Docker Layer Caching**: Optimized `Dockerfile` to cache dependency installation independently of application code.
