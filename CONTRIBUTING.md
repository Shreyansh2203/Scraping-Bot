# Contributing

Thank you for your interest in contributing to Scraping-Bot! Bug fixes, new features,
documentation improvements, and tests are all welcome.

Before you start: this bot fetches media on behalf of a Telegram user, so read
[the scope section in the README](README.md#scope-and-responsible-use) and
[SECURITY.md](SECURITY.md). A change that makes it easier to pull someone else's media is
not going to be merged.

## Development Setup

1. Fork and clone the repository.
2. Install development dependencies:
   ```bash
   make dev
   ```
   `make` is a convenience wrapper. Without it, the same thing is
   `pip install -e ".[dev]"`.
3. Set up your `.env` file from `.env.example`. The only value you need to run the tests is
   a syntactically valid throwaway `BOT_TOKEN`; the suite never contacts Telegram.

## Running the gates

Run these before opening a pull request. CI runs exactly this set on Python 3.11 and 3.12,
plus the container job and the dependency audit.

```bash
make format   # black, rewrites files
make lint     # black --check, ruff, mypy
make test     # pytest with the coverage gate
```

Or the underlying commands, which is what CI executes:

```bash
black .
black --check .
ruff check .
mypy --strict bot/ core/
pytest
```

`pytest` enforces `fail_under` from `[tool.coverage.report]` in `pyproject.toml`, so a
change that drops coverage below the floor fails the run. Do not lower the floor, add a
`# pragma: no cover`, or add an entry to `exclude_lines` to get a green build — add the
test.

### Dependency scanning

`pip-audit` is in the dev extras and checks the dependencies declared in `pyproject.toml`
against the PyPA advisory database:

```bash
pip-audit --progress-spinner off .
```

CI runs that command on every push and pull request, and
[`.github/workflows/dependency-audit.yml`](.github/workflows/dependency-audit.yml) re-runs
it against `main` every Monday to catch advisories published after a branch was cut. Pull
requests also go through a dependency review, which fails when a vulnerable or badly
licensed package arrives in the diff. Dependabot opens the upgrade pull requests for the
Python dependencies, the GitHub Actions, and the Docker base image.

## Adding support for another platform

The extraction is deliberately narrow: one link in, one post's media out. A platform
addition is small, and there are three places to touch.

1. **`_URL_RE` in `bot/handlers/download.py`.** The regex decides whether a message is
   treated as a download request at all, and it is also the single gate in front of
   `yt-dlp`. Extend the scheme/host alternation and add a group for the new path
   (`reel`, `p`, `status`, ...). Note that `_is_safe_url` in
   `core/downloader_wrapper.py` re-checks the scheme and host independently, so a platform
   still cannot smuggle a flag in through the URL.
2. **`DownloaderWrapper._build_command` in `core/downloader_wrapper.py`.** Only if the
   platform needs its own `--extractor-args` or a different format selector. Prefer the
   existing `bestvideo*[ext=mp4]+bestaudio[ext=m4a]` selector; the `ffmpeg`-missing
   fallback to `best` is already handled for you.
3. **`DownloaderWrapper._find_output_file`.** Only if the platform's output filenames
   cannot be matched by the existing heuristics (the `[<digits>]` marker that `yt-dlp`
   leaves in the name, or the id at the end of the URL path). Getting this wrong does not
   fail the download, it returns the wrong file, so cover it with a test that writes a
   realistic filename to a temporary directory.

Do not add `--max-filesize` to the `yt-dlp` command. A size rejection inside `yt-dlp` costs
three retry attempts and a `gallery-dl` fallback before the user sees one clear message.
`MAX_FILE_SIZE_MB` is enforced after the download, and that is deliberate.

If the platform cannot be handled by `yt-dlp` and needs `gallery-dl` as a first-class
path rather than a fallback, add the method next to `_run_gallery_dl` and branch in
`download_url`; keep the yt-dlp-first ordering, because it produces better quality for the
platforms that already work.

## Testing

Every test in `tests/` mocks the subprocess layer. The suite never runs `yt-dlp`,
`gallery-dl`, or `ffmpeg`, never contacts Instagram, X, or Telegram, and never needs
`ffmpeg` installed. The real integration is covered once, in CI, by the `container` job
that builds the image and asserts its health endpoints.

The rules that keep it that way:

- **Patch `asyncio.create_subprocess_exec`, not the tools.** `DownloaderWrapper` is the only
  thing that spawns anything, so patching the call is enough to make a test hermetic. Patch
  `shutil.which` as well when the test depends on whether `ffmpeg` is installed, because
  `_build_command` branches on it and CI runners do have `ffmpeg`.
- **Assert on argv when the command is the subject.** `test_build_command` checks the flags
  and the format selector, because a wrong flag is invisible in a test that only checks
  whether a download "succeeded".
- **Write files through the `cwd` the real call passes.** Stub the subprocess with a
  `side_effect` that creates its output under `kwargs["cwd"]`. That keeps the per-job
  directory isolation honest, and it is what lets you assert that a failed attempt leaves
  nothing behind.
- **Patch `asyncio.sleep` in anything that retries.** The retry path backs off; without the
  patch the suite pays real seconds.
- **Mock both branches of a platform check.** `sys.platform` is monkeypatched in the
  process-group tests so the POSIX and Windows paths are both exercised on any host.
- **No wall-clock assertions.** Assert on the values the code returns, not on how long it
  took.

## Pull Request Process

1. Create a descriptive branch name.
2. Add or update tests for any new functionality.
3. Ensure the gates above pass locally.
4. Submit a pull request against `main` and let CI run.

## Releases

Releases are automated. [release-please](https://github.com/googleapis/release-please) runs on
every merge to `main` and opens a release pull request that bumps the version in
`pyproject.toml` and `.release-please-manifest.json` and writes [CHANGELOG.md](CHANGELOG.md).
The changelog is generated, not hand-edited, so a commit only reaches the release notes if
it uses [Conventional Commits](https://www.conventionalcommits.org/).

### Commit format

```
<type>(optional scope): <imperative summary under 72 characters>
```

The subject line is what ends up in the changelog. Write it for someone reading release
notes, not for someone reading `git log`.

| Type | Section in the changelog | Use it for |
|---|---|---|
| `feat` | Added | A capability a user can now do. |
| `fix` | Fixed | A bug a user could hit. |
| `refactor` | Changed | Behaviour-preserving restructuring. |
| `perf` | Performance | A change made for speed or resource use. |
| `docs` | Documentation | README, CONTRIBUTING, SECURITY. |
| `chore(deps)` | Dependencies | A dependency bump. |
| `test` | Tests | Tests and test infrastructure. |
| `ci` | CI | Workflows, actions, release automation. |
| `build` | Build | The Dockerfile, packaging, build config. |
| `chore` | Maintenance | Everything else that is not user-visible. |

Scopes are optional and are not part of the type, so `fix(downloader): ...` files under
Fixed. Mark a breaking change with `!` after the scope, or with a `BREAKING CHANGE:` footer
in the commit body:

```
feat(handler)!: reject non-http download URLs
```

A commit type that is not in the table above, or a commit with no type at all, is skipped
by release-please and will be missing from the release notes.
`tests/test_repo_config.py` checks that the table above and the `changelog-sections` in
`.release-please-config.json` stay in step.
