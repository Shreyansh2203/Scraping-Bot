# Changelog

All notable changes to this project will be documented in this file.

## [1.0.1](https://github.com/Shreyansh2203/Scraping-Bot/compare/scraping-bot-v1.0.0...scraping-bot-v1.0.1) (2026-11-08)


### Bug Fixes

* exclude project itself from pip-audit export ([afd8f46](https://github.com/Shreyansh2203/Scraping-Bot/commit/afd8f4650d17026de8128dccfef18943338a1a03))
* force upgrade apt and libapt-pkg6.0 in Dockerfile ([48cdae3](https://github.com/Shreyansh2203/Scraping-Bot/commit/48cdae34d0902dfd03076aec302ae5c5daa8f736))
* keep ffmpeg install on first apt-get line for test ([9a51813](https://github.com/Shreyansh2203/Scraping-Bot/commit/9a5181371d46dd22b8fd907dd0e7639a059ad30b))
* resolve failing security scan workflows ([45ac9a7](https://github.com/Shreyansh2203/Scraping-Bot/commit/45ac9a76df1cc2d11d1f16e96d9c586cd7a8dd3d))
* resolve Trivy container scan findings ([1a0a042](https://github.com/Shreyansh2203/Scraping-Bot/commit/1a0a042b235c2791866480661d0c493ec38da640))


### Documentation

* add industry-standard documentation and best-practice files ([f8efed0](https://github.com/Shreyansh2203/Scraping-Bot/commit/f8efed031f296c6c57b9bdf056dc1a33f0a00595))
* add production README ([d9cabf4](https://github.com/Shreyansh2203/Scraping-Bot/commit/d9cabf4a63816cd4f85b0f2f17974a8edc6b48b8))


### Chores

* remove all documentation and reset history ([046cb23](https://github.com/Shreyansh2203/Scraping-Bot/commit/046cb230b44a8dabbc7602ad802c8689002aa05a))

## [1.0.0] - 2026-11-06

### Features
- Initial release of Scraping-Bot with Instagram and Twitter/X video download support.
- Dual health server with `/health`, `/metrics`, and `/healthz`.
- Rate limiting and abuse prevention with per-user allow-lists.
- Multi-backend download pipeline with automatic fallback and media probing.
