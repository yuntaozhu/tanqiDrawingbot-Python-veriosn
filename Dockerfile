# ==========================================
# Production Dockerfile for TanQi Drawing Bot
# ==========================================
FROM python:3.13-slim

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=3000

# Install system dependencies required by OpenCV and other packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Create application user for security
RUN groupadd -g 1000 appgroup && \
    useradd -r -u 1000 -g appgroup -s /sbin/nologin appuser

# Create and setup virtual environment
RUN python3 -m venv /app/venv

# Copy requirements and install dependencies
COPY requirements.txt .
RUN /app/venv/bin/pip install --upgrade pip && \
    /app/venv/bin/pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=appuser:appgroup . .

# Ensure venv binaries are executable
RUN chmod -R 755 /app/venv

# Set permissions for app directory
RUN chown -R appuser:appgroup /app && chmod -R 755 /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD /app/venv/bin/python -c "import requests; requests.get('http://localhost:${PORT}/health')" || exit 1

# Run the application - explicitly use venv python
CMD ["/app/venv/bin/python", "app.py"]

