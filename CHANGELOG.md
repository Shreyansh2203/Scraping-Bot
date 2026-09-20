# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
