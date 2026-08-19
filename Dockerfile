# ==============================================================================
# Multi-Stage Dockerfile for Google Cloud Run (Frontend + Backend)
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build React Dashboard Frontend
# ------------------------------------------------------------------------------
FROM node:20-alpine AS frontend-builder
WORKDIR /app/cloud/dashboard/frontend

# Copy frontend dependencies and build configuration
COPY cloud/dashboard/frontend/package*.json ./
RUN npm ci --prefer-offline --no-audit

# Copy frontend source files
COPY cloud/dashboard/frontend/ ./

# Create static destination folder and build
RUN mkdir -p /app/cloud/dashboard/backend/app/static/vite && \
    npm run build

# ------------------------------------------------------------------------------
# Stage 2: Python Backend Runtime
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8080

WORKDIR /app

# Install system libraries needed by OpenCV and network diagnostics
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements
COPY cloud/requirements.txt ./cloud/requirements.txt

# Install CPU-optimized PyTorch and Python requirements
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r cloud/requirements.txt

# Copy cloud backend code
COPY cloud/ ./cloud/

# Copy built frontend static bundle from frontend-builder stage
COPY --from=frontend-builder /app/cloud/dashboard/backend/app/static/vite /app/cloud/dashboard/backend/app/static/vite

# Expose default Cloud Run port
EXPOSE 8080

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/api/health || exit 1

# Start the application server on Cloud Run's dynamic $PORT
CMD exec uvicorn cloud.dashboard.backend.app.main:app --host 0.0.0.0 --port ${PORT:-8080}
