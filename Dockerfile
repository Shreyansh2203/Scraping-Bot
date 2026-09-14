FROM python:3.14-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r botuser && useradd -r -g botuser -d /app botuser

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories and set ownership
RUN mkdir -p downloads state && chown -R botuser:botuser /app

# Switch to non-root user
USER botuser

# Make the health server reachable outside the container.
ENV HEALTH_BIND=0.0.0.0

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f "http://127.0.0.1:${PORT:-${HEALTH_PORT:-8080}}/health" || exit 1

# Run the bot
CMD ["python", "-m", "bot.main"]
