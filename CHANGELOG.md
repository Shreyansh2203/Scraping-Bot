# Changelog

## [0.2.0](https://github.com/Shreyansh2203/Scraping-Bot/compare/scraping-bot-v0.1.0...scraping-bot-v0.2.0) (2026-09-19)


### Added

* add CodeQL, dependency review, CODEOWNERS, release automation, and repo metadata ([ffbf84a](https://github.com/Shreyansh2203/Scraping-Bot/commit/ffbf84ab1d31be2602ca9f8a59e8b7721a52e2c6))
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
* correct release-please manifest key ([ec3d219](https://github.com/Shreyansh2203/Scraping-Bot/commit/ec3d219e2862e80ed87b0fd0d9939c88e2457a94))
* expose health server for Render deployments ([9ab2976](https://github.com/Shreyansh2203/Scraping-Bot/commit/9ab2976f3b74cbbaa721878c98f956827843b9cd))
* force yt-dlp to use twitter syndication API to bypass datacenter IP restrictions ([440fdb1](https://github.com/Shreyansh2203/Scraping-Bot/commit/440fdb19bfd50a339dfaad90cc1366a1e4138565))
* resolve linting errors and deprecation warnings ([ff50d15](https://github.com/Shreyansh2203/Scraping-Bot/commit/ff50d158f1fa07ee1114ea4bc08b3dfcb3a7f7dc))
* run downloads in background task to avoid webhook timeout ([05aa27b](https://github.com/Shreyansh2203/Scraping-Bot/commit/05aa27bdfe923c3113f222ed1d2e0f6411901bc5))
* yt-dlp format sorting on Render penalizes unknown codecs, use size-based sorting ([c36419a](https://github.com/Shreyansh2203/Scraping-Bot/commit/c36419a9cef173249b57fc0394b0765e4f152c0e))
* yt-dlp selecting lower bitrate video-only streams over higher bitrate pre-merged streams ([9b3b6c0](https://github.com/Shreyansh2203/Scraping-Bot/commit/9b3b6c038ff6dac5fdd69c69509c414a8b11c945))


### Dependencies

* remove obsolete data files and legacy scripts ([3ef2d10](https://github.com/Shreyansh2203/Scraping-Bot/commit/3ef2d1035b1261e9a07996c6e7200a36e90b0793))
* trigger release pipeline ([6815889](https://github.com/Shreyansh2203/Scraping-Bot/commit/6815889b5c677341232ea4b156cd5416268cda27))
