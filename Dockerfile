# syntax = docker/dockerfile:1.7
# Build stage: resolve and install dependencies with uv
# python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d
FROM python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d AS builder

ENV UV_VERSION=0.12.14
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

RUN pip install --no-cache-dir "uv==${UV_VERSION}"

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY bot ./bot
COPY core ./core

RUN uv sync --locked --no-dev --python 3.13


# Runtime stage: minimal image with only the application and its dependencies
# python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d
FROM python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HEALTH_BIND=0.0.0.0 \
    DOWNLOAD_DIR=/app/downloads

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1000 botuser && \
    useradd --system --uid 1000 --gid 1000 --home-dir /app --shell /usr/sbin/nologin botuser && \
    mkdir -p /app/downloads && \
    chown -R botuser:botuser /app

WORKDIR /app

COPY --from=builder --chown=botuser:botuser /app/.venv .venv
COPY --from=builder --chown=botuser:botuser /app/bot ./bot
COPY --from=builder --chown=botuser:botuser /app/core ./core

USER botuser

ENV PATH="/app/.venv/bin:${PATH}"

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).read()" || exit 1

EXPOSE 8080

CMD ["python", "-m", "bot.main"]