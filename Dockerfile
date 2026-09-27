# Digest-pinned rather than tag-pinned: a tag is a mutable pointer, and an unpinned
# base means the bytes behind a released image digest are not reproducible.
FROM python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    HEALTH_BIND=0.0.0.0

WORKDIR /app

# ffmpeg is what lets yt-dlp merge separate audio and video streams; without it
# DownloaderWrapper._build_command silently drops to the pre-merged 'best' selector.
# curl is the healthcheck's client. Both are kept deliberately narrow.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 botgroup \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin botuser

# uv by digest, so the resolver that builds the image is pinned as tightly as the base.
COPY --from=ghcr.io/astral-sh/uv:0.12.14@sha256:1946145b8706ad9e5c0e79a513f9e324b58d5e38126bb2c8b7dbfca61febeb45 /uv /uvx /bin/

# Dependencies first, from uv.lock and without the project itself, so this layer is
# reused whenever only application source has changed.
COPY pyproject.toml README.md uv.lock ./
RUN uv sync --locked --no-cache --no-dev --no-install-project
ENV PATH="/opt/venv/bin:/usr/local/bin:${PATH}"

# The application source, left root-owned and read-only to the runtime user. These
# replace the old `COPY bot ./bot` + `COPY core ./core` + `COPY . .` trio: the blanket
# COPY re-sent bot/ and core/ over the two explicit ones and made them pointless, and
# it dragged the test suite and .git into the image.
COPY bot ./bot
COPY core ./core

# Now the project itself, still from the same locked resolution.
#
# /app itself is group-owned by botgroup and setgid rather than chown -R'd to the
# runtime user. bot.main resolves its log file to Path("bot.log") against the working
# directory, so the runtime user has to be able to create /app/bot.log; nothing else in
# /app has to be writable, and the old `chown -R botuser /app` made the whole tree so.
RUN uv sync --locked --no-cache --no-dev \
    && rm -rf /app/*.egg-info \
    && install -d -o 10001 -g 10001 /app/downloads \
    && chgrp botgroup /app \
    && chmod 2775 /app

USER 10001:10001
EXPOSE 8080
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f "http://127.0.0.1:${PORT:-${HEALTH_PORT:-8080}}/health" || exit 1

CMD ["python", "-m", "bot.main"]
