# ==========================================
# Production-Grade Dockerfile for TanQi Drawing Bot
# ==========================================

# Use python:3.13-slim as the base image
FROM python:3.13-slim

# Set shell to bash with exit-on-error and prevent creating .pyc files
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PATH="/app/.venv/bin:$PATH" \
    PORT=3000

# ============ System Dependencies ============
# Install system libraries required by OpenCV, image processing, and networking
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ============ Application Setup ============
WORKDIR /app

# Create non-root user (uid 1000) for enhanced application security
RUN groupadd -g 1000 appgroup && \
    useradd -r -u 1000 -g appgroup -s /sbin/nologin appuser

# ============ Python Virtual Environment & Dependencies ============
# Create virtual environment in a way that ensures proper permissions
RUN python -m venv /app/.venv && \
    # Ensure all .venv binaries are executable
    chmod -R 755 /app/.venv/bin && \
    # Upgrade pip and setuptools for wheel building
    /app/.venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy and install Python dependencies
COPY requirements.txt .
RUN /app/.venv/bin/pip install --no-cache-dir -r requirements.txt

# ============ Application Code ============
# Copy application code with proper ownership
COPY --chown=appuser:appgroup . .

# Ensure critical binaries are executable
RUN chmod +x /app/.venv/bin/python && \
    chmod +x /app/.venv/bin/uvicorn && \
    chmod -R 755 /app/.venv/bin

# Make application directory accessible to appuser
RUN chown -R appuser:appgroup /app && \
    chmod -R 755 /app

# ============ Runtime Configuration ============
# Switch to non-root user for security
USER appuser

# Inform container hosts that the app listens on the assigned port
EXPOSE 3000

# Define Docker native healthcheck to monitor FastAPI application liveness
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Launch the application using the python interpreter from the virtual environment
# app.py itself will use uvicorn to run the FastAPI app
CMD ["/app/.venv/bin/python", "app.py"]

