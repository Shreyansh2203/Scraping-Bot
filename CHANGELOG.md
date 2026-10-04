# Changelog

## [0.2.0](https://github.com/Shreyansh2203/Scraping-Bot/compare/scraping-bot-v0.1.0...scraping-bot-v0.2.0) (2026-10-04)


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

* **main:** collapse the duplicated shutdown path and read the version from metadata ([bc2ec0b](https://github.com/Shreyansh2203/Scraping-Bot/commit/bc2ec0b0f402256388eccd5457204c118ff4c0fd))
* Switch to Webhooks on Render and remove state_file ([dea8fb9](https://github.com/Shreyansh2203/Scraping-Bot/commit/dea8fb9cc090e641e782b7e41a419f5c6a627279))


### Fixed

* add timestamp to yt-dlp output to avoid persistent disk caching on Render ([bf7989d](https://github.com/Shreyansh2203/Scraping-Bot/commit/bf7989dbd2eb03cfe61834f6e66d988d208235de))
* apply the size floor to the fallback, and cover the wiring the suite skipped ([da86611](https://github.com/Shreyansh2203/Scraping-Bot/commit/da866110ce197e60150e353f77d60cce7804d6af))
* attach middlewares to dp.message instead of dp.update ([3037e5b](https://github.com/Shreyansh2203/Scraping-Bot/commit/3037e5bdaa7c7df755282c4ac1bf7bfe8717162d))
* **auth:** an empty allow-list denies everyone unless the bot is explicitly public ([edde5ab](https://github.com/Shreyansh2203/Scraping-Bot/commit/edde5abf90542ea12e5f29f2c72e7522b5a468de))
* bound the gallery-dl fallback, stop leaking exception text, rotate bot.log ([be4e13d](https://github.com/Shreyansh2203/Scraping-Bot/commit/be4e13d531271a5cfaf5ed7320540ce9959e413c))
* **ci:** resolve POSIX pathlib mocking and test timing issues ([37d7b12](https://github.com/Shreyansh2203/Scraping-Bot/commit/37d7b12ba28c986f8fb4594cbcc909888aa4af0b))
* **config:** fail fast on a malformed BOT_TOKEN ([76ae131](https://github.com/Shreyansh2203/Scraping-Bot/commit/76ae1310611eb7de7a2899b30ec252606158819e))
* **config:** refuse to start without an explicit allow-list ([631e360](https://github.com/Shreyansh2203/Scraping-Bot/commit/631e360c7905903e55423c4ab22c41f0d937c237))
* correct release-please manifest key ([ec3d219](https://github.com/Shreyansh2203/Scraping-Bot/commit/ec3d219e2862e80ed87b0fd0d9939c88e2457a94))
* **docs:** repair the product-comparison cross-link ([b6d9833](https://github.com/Shreyansh2203/Scraping-Bot/commit/b6d9833856695d30ca365c26242b164b8e8fea0d))
* **downloader:** bound the transfer, shed load when saturated, and clean up on cancel ([123ba10](https://github.com/Shreyansh2203/Scraping-Bot/commit/123ba101e0bbdfd7b0aace0c73dde63bfe806b9c))
* **downloader:** return fallback files in a stable order instead of filesystem order ([81bd6a3](https://github.com/Shreyansh2203/Scraping-Bot/commit/81bd6a3e91d2f1fd0ff2aba919aff4cd417946a6))
* **downloader:** validate urls, isolate fallback output, kill process tree on timeout ([9f7d08d](https://github.com/Shreyansh2203/Scraping-Bot/commit/9f7d08d052d0be01f477a3cfa41658ed374506c1))
* **download:** escape html entities in url captions ([7fa0132](https://github.com/Shreyansh2203/Scraping-Bot/commit/7fa013260622f908e25c9d92a84ded11087161a6))
* **download:** escape html in failure captions and send single-item albums on their own ([349a365](https://github.com/Shreyansh2203/Scraping-Bot/commit/349a3659fe171194fe6b6f74cf6a7a7c36e8d4f4))
* **download:** initialize InputMedia with caption directly to support frozen models ([ec9f32f](https://github.com/Shreyansh2203/Scraping-Bot/commit/ec9f32f5548e3e21cbaaf0ae7a4380baad1ce7d4))
* expose health server for Render deployments ([9ab2976](https://github.com/Shreyansh2203/Scraping-Bot/commit/9ab2976f3b74cbbaa721878c98f956827843b9cd))
* force yt-dlp to use twitter syndication API to bypass datacenter IP restrictions ([440fdb1](https://github.com/Shreyansh2203/Scraping-Bot/commit/440fdb19bfd50a339dfaad90cc1366a1e4138565))
* **main:** route SIGTERM/SIGINT through the loop so the drain always runs ([e44441e](https://github.com/Shreyansh2203/Scraping-Bot/commit/e44441ecbd97683aaa95532fa6be9c23acd54ca0))
* **release:** map the style commit type so it is not dropped ([28e7f6b](https://github.com/Shreyansh2203/Scraping-Bot/commit/28e7f6bcc9777c303a9060fd569d822eecb159b5))
* resolve linting errors and deprecation warnings ([ff50d15](https://github.com/Shreyansh2203/Scraping-Bot/commit/ff50d158f1fa07ee1114ea4bc08b3dfcb3a7f7dc))
* run downloads in background task to avoid webhook timeout ([05aa27b](https://github.com/Shreyansh2203/Scraping-Bot/commit/05aa27bdfe923c3113f222ed1d2e0f6411901bc5))
* **security:** require a per-process secret on the webhook ([709ffc1](https://github.com/Shreyansh2203/Scraping-Bot/commit/709ffc166c24b4d24b4ba35a4fd577d0920c3498))
* **webhook:** preserve pending updates on startup so cold-start messages are delivered ([df1347c](https://github.com/Shreyansh2203/Scraping-Bot/commit/df1347ca6f6965c0c991607eac3eec7b7b33ff6b))
* yt-dlp format sorting on Render penalizes unknown codecs, use size-based sorting ([c36419a](https://github.com/Shreyansh2203/Scraping-Bot/commit/c36419a9cef173249b57fc0394b0765e4f152c0e))
* yt-dlp selecting lower bitrate video-only streams over higher bitrate pre-merged streams ([9b3b6c0](https://github.com/Shreyansh2203/Scraping-Bot/commit/9b3b6c038ff6dac5fdd69c69509c414a8b11c945))


### Documentation

* add problem and approach framing, align the license holder ([09dc4ae](https://github.com/Shreyansh2203/Scraping-Bot/commit/09dc4ae8e629526f824a0c02cce7a1a2b6789911))
* cross-link the portfolio ([d34d1fd](https://github.com/Shreyansh2203/Scraping-Bot/commit/d34d1fd5a420380f55f1b52b805512e1efd19a3f))
* document the mode and port variables that config actually reads ([cfaa8de](https://github.com/Shreyansh2203/Scraping-Bot/commit/cfaa8deb9facb98d2a417d361889527cc0862c48))
* hand CHANGELOG.md over to release-please ([61b52d5](https://github.com/Shreyansh2203/Scraping-Bot/commit/61b52d5a99d3c5ef8283a6910cab7ffe102640ee))
* reconcile the release, deploy and contributor contracts ([0d66f10](https://github.com/Shreyansh2203/Scraping-Bot/commit/0d66f106141abddc6d5be3d42ebb0dce98b68de7))
* **render:** correct the sync:false and missing-env-var comments ([3cb3343](https://github.com/Shreyansh2203/Scraping-Bot/commit/3cb334324ee68a6f3f5a82d31adffeaea393ee89))
* state the bot's scope and the operator's responsibility up front ([8e5a70b](https://github.com/Shreyansh2203/Scraping-Bot/commit/8e5a70b4eb8f281b0d87d709aae47cada1868c4a))


### Tests

* cover the downloader's remaining branches and raise the floor to 98 ([a0070a3](https://github.com/Shreyansh2203/Scraping-Bot/commit/a0070a394bc6901168d987338c3f7ac694b13b87))
* gate the render, release and documentation contracts ([7c502bf](https://github.com/Shreyansh2203/Scraping-Bot/commit/7c502bfba888383ae2de0814195a056f5958f45a))


### CI

* audit dependencies on every change and weekly ([9be33dd](https://github.com/Shreyansh2203/Scraping-Bot/commit/9be33dd6b534dace573102b07bdcbd98e2acb401))
* build the image in CI and prove it serves its health endpoints ([c23f3a6](https://github.com/Shreyansh2203/Scraping-Bot/commit/c23f3a608a5fc73ba4d1de5c747fca2cdfad4553))
* pin every action to a full commit SHA ([6028448](https://github.com/Shreyansh2203/Scraping-Bot/commit/6028448eae0ff30ff7b699368d5f50b5a97c8879))
* report failing tests as job annotations ([71aefff](https://github.com/Shreyansh2203/Scraping-Bot/commit/71aefffa10a50f120290a0b7653da0856e8e0394))
* setup enterprise github actions (ci, release, dependabot, trivy) ([8b54677](https://github.com/Shreyansh2203/Scraping-Bot/commit/8b54677d8b9db29ce90ce4db586567db716bb169))


### Maintenance

* adopt uv, drop black, and make the image match what the release pushes ([f8252a1](https://github.com/Shreyansh2203/Scraping-Bot/commit/f8252a1ef75ae369044c9f16c839e4bcdd1d9d63))
* close repo hygiene gaps in ignore rules, dev setup and deploy config ([99a0cb4](https://github.com/Shreyansh2203/Scraping-Bot/commit/99a0cb4ba35c11c38ce2aa0640afd4bfc94e0233))
* remove obsolete data files and legacy scripts ([3ef2d10](https://github.com/Shreyansh2203/Scraping-Bot/commit/3ef2d1035b1261e9a07996c6e7200a36e90b0793))
* remove the scratch commit-message file ([15074cb](https://github.com/Shreyansh2203/Scraping-Bot/commit/15074cba90e482a0aa557785b807fe65b9313cc1))
* trigger release pipeline ([6815889](https://github.com/Shreyansh2203/Scraping-Bot/commit/6815889b5c677341232ea4b156cd5416268cda27))


### Style

* fix import order and formatting for CI ([e8e739b](https://github.com/Shreyansh2203/Scraping-Bot/commit/e8e739b63501e19d839898eac489e7f0d6117bc1))
* run black formatter ([15fd1ca](https://github.com/Shreyansh2203/Scraping-Bot/commit/15fd1ca68b2d362b35f97f4a1ca5271405e8d0af))

## Changelog

This file is maintained by [release-please](https://github.com/googleapis/release-please),
which derives it from [Conventional Commits](https://www.conventionalcommits.org/) on every
merge to `main` and bumps `pyproject.toml` and `.release-please-manifest.json` from that same
history. Do not edit it by hand — release-please overwrites it when it opens a release PR.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the commit format the flow depends on.

The `0.1.0` baseline is not listed here. No release was ever cut, so there is no `v0.1.0` tag
to compare against, and the notes that used to be maintained here were a hand-written summary
that had already drifted from the commit history. What the baseline does is covered by the
feature list in [README.md](README.md); the commits behind it are in the
[history](https://github.com/Shreyansh2203/Scraping-Bot/commits/main).
