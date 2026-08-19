# ==============================================================================
# Multi-Stage Dockerfile for Google Cloud Run (Frontend + FastAPI + Node Microservice)
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
# Stage 2: Unified Python + Node.js Runtime
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8080

WORKDIR /app

# Install system libraries needed by OpenCV, Canvas, Node.js, and Networking
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    libgl1 \
    libglib2.0-0 \
    build-essential \
    libcairo2-dev \
    libpango1.0-dev \
    libjpeg-dev \
    libgif-dev \
    librsvg2-dev \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# 1. Install Python Backend Dependencies
COPY cloud/requirements.txt ./cloud/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r cloud/requirements.txt

# 2. Install Node.js Mapping Microservice Dependencies
COPY mapping_and_notification/backend/package*.json ./mapping_and_notification/backend/
RUN cd mapping_and_notification/backend && npm ci --prefer-offline --no-audit

# 3. Copy Application Source Codes
COPY cloud/ ./cloud/
COPY mapping_and_notification/ ./mapping_and_notification/

# 4. Copy floorplan uploads into static uploads and private runtime storage
COPY mapping_and_notification/backend/uploads/ /app/cloud/dashboard/backend/app/static/uploads/
COPY mapping_and_notification/backend/uploads/ /app/runtime-data/private/floorplans/

# 5. Copy built frontend static bundle from frontend-builder stage
COPY --from=frontend-builder /app/cloud/dashboard/backend/app/static/vite /app/cloud/dashboard/backend/app/static/vite

# Expose Cloud Run default port
EXPOSE 8080

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/api/health || exit 1

# Start both Node.js Mapping microservice and FastAPI gateway via supervisor
CMD ["python", "/app/cloud/run_cloud_services.py"]
