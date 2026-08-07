# ==========================================
# Production-Grade Dockerfile for TanQi Drawing Bot
# ==========================================

# Stage 1: Build virtual environment and compile native extensions
FROM python:3.13-slim AS builder

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Install build-essential and required libraries for compiling wheels (e.g. OpenCV / pillow)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Initialize virtual environment securely
RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY requirements.txt .

# Upgrade pip and install all Python package dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Light final runtime image
FROM python:3.13-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PORT=3000

# Install runtime system libraries required by OpenCV (libsm6, libxext6, libxrender, glib, glx) and healthcheck dependencies (curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create non-root user (uid 1000) for enhanced application security
RUN groupadd -g 1000 appgroup && \
    useradd -r -u 1000 -g appgroup -s /sbin/nologin appuser

# Copy fully built virtual environment and application workspace
COPY --from=builder /app/.venv /app/.venv
COPY . .

# Ensure explicit execution privileges for python, uvicorn and other binaries inside .venv
RUN chmod -R +rx /app/.venv/bin && \
    chown -R appuser:appgroup /app

# Switch context to the non-root appuser
USER appuser

# Inform container hosts that the app listens on the assigned port
EXPOSE 3000

# Define Docker native healthcheck to monitor FastAPI application liveness
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Launch the application using the secure virtual environment's python interpreter
CMD ["python", "app.py"]
