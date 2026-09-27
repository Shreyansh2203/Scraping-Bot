# Security Policy

## Reporting a vulnerability

We take the security of Scraping-Bot seriously. If you believe you have found a security
vulnerability, please follow responsible disclosure:

1. **Do not create a public GitHub issue.**
2. Report the vulnerability privately via
   [GitHub Security Advisories](https://github.com/Shreyansh2203/Scraping-Bot/security/advisories/new)
   or by emailing `security@shreyansh.dev`.
3. Include steps to reproduce, a proof of concept, and the environment you tested on.
4. You will get an initial response within **48 hours**, and updates until it is resolved.
5. Once resolved we will publish a security advisory and credit the reporter.

## Threat model

The bot is an internet-facing service that takes a URL from an untrusted Telegram user and
hands it to a media extraction pipeline. Two properties drive everything below.

**It shells out to third-party parsers on untrusted input.** `DownloaderWrapper` runs
`yt-dlp` and `gallery-dl` as subprocesses, `ffmpeg` for stream merging, and `ffprobe` to
read resolution metadata. Their stdout and stderr are parsed and their exit status is
interpreted, and the media they produce comes from servers the bot does not control. A
parsing bug in any of those tools is a remote code execution bug in this bot. The
project treats the subprocess boundary as the main attack surface: URLs are validated as
`http(s)` with a host before they ever reach `execve` (no shell, no user-controlled
flags), each download runs in its own process group so a timeout kills the whole tree
rather than leaking an `ffmpeg`, and the job directory is unique per request.

**Anyone can talk to it unless you stop them.** `ALLOWED_USERS` is an allow-list of
Telegram user IDs. When it is empty the bot is public: any account that finds it can
trigger downloads. Set it before exposing the bot.

## Running it safely

Sandboxed execution is advisable, and the image is built to make that easy:

- The container already runs as the unprivileged `botuser`, not root.
- Run with a read-only root filesystem and a tmpfs for the download directory; the bot only
  writes under `DOWNLOAD_DIR`.
- Cap CPU, memory, and disk. `CONCURRENT_DOWNLOADS`, `MAX_FILE_SIZE_MB`, and
  `SUBPROCESS_TIMEOUT` bound the work per request, but not the total.
- Restrict egress to the hosts the bot actually needs — the Telegram Bot API and the
  platforms being extracted from. A compromised parser should not be able to reach
  anything else on your network.
- Do not mount host directories into the container, and do not run it with Docker socket
  access or extra capabilities.
- Keep `yt-dlp`, `gallery-dl`, and the base image current. These are exactly the
  dependencies where a new release is usually a security fix.

## Out of scope

Using the bot to download media you do not own or have permission to download is not a
vulnerability in this project, and reports framed that way will be closed. See
[the scope section in the README](README.md#scope-and-responsible-use) for what the tool
does and does not do.

## Supported versions

We actively support the latest release with security updates and critical patches.

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1.0 | :x:                |
