FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r botuser && useradd -r -g botuser -d /app botuser

WORKDIR /app

# Copy dependency definition first for optimal layer caching
COPY pyproject.toml README.md ./
RUN mkdir -p bot core && touch bot/__init__.py core/__init__.py \
    && pip install --no-cache-dir . \
    && rm -rf bot core

# Copy actual application code
COPY bot ./bot
COPY core ./core
COPY . .

# Re-install project package to bind real code
RUN pip install --no-cache-dir --no-deps .

# Create downloads directory and set permissions
RUN mkdir -p downloads && chown -R botuser:botuser /app

# Switch to non-root user
USER botuser

ENV HEALTH_BIND=0.0.0.0

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f "http://127.0.0.1:${PORT:-${HEALTH_PORT:-8080}}/health" || exit 1

CMD ["python", "-m", "bot.main"]
