# ==========================================
# Production-Grade Single-Stage Dockerfile for TanQi Drawing Bot
# ==========================================
FROM python:3.13-slim

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PORT=3000 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies including OpenCV runtime libraries, build-essential, and curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create non-root user (uid 1000) for security
RUN groupadd -g 1000 appgroup && \
    useradd -r -u 1000 -g appgroup -d /app -s /sbin/nologin appuser && \
    chown -R appuser:appgroup /app

# Switch to non-root user for virtual environment creation and dependency installation
USER appuser

# Create virtual environment and install dependencies
RUN python -m venv /app/.venv && \
    /app/.venv/bin/pip install --no-cache-dir --upgrade pip

COPY --chown=appuser:appgroup requirements.txt .
RUN /app/.venv/bin/pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY --chown=appuser:appgroup . .

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

CMD ["/app/.venv/bin/python", "app.py"]
