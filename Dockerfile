# ==============================================================================
# Multi-Stage Dockerfile for Google Cloud Run (Unified React + FastAPI Runtime)
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build React Dashboard Frontend
# ------------------------------------------------------------------------------
FROM node:20-alpine AS frontend-builder
WORKDIR /app/cloud/dashboard/frontend

COPY cloud/dashboard/frontend/package*.json ./
RUN npm ci --prefer-offline --no-audit

COPY cloud/dashboard/frontend/ ./

RUN mkdir -p /app/cloud/dashboard/backend/app/static/vite && \
    npm run build

# ------------------------------------------------------------------------------
# Stage 2: Pure Python FastAPI Runtime (No Node.js Microservice Required)
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8080

WORKDIR /app

# Install system libraries needed by OpenCV and Networking
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 1. Install Python Backend Dependencies
COPY cloud/requirements.txt ./cloud/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r cloud/requirements.txt

# 2. Copy Application Source Code (Central Cloud + In-Process AI Services)
COPY cloud/ ./cloud/
COPY mapping_and_notification/ai-services/ ./mapping_and_notification/ai-services/

# 3. Seed floorplan images into private runtime storage
COPY mapping_and_notification/backend/uploads/ /app/runtime-data/private/floorplans/

# 4. Copy built frontend static bundle from frontend-builder stage
COPY --from=frontend-builder /app/cloud/dashboard/backend/app/static/vite /app/cloud/dashboard/backend/app/static/vite

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/api/health || exit 1

CMD ["python", "/app/cloud/run_cloud_services.py"]
