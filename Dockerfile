# =============================================================================
# ASRI — Multi-stage Dockerfile
# =============================================================================
# Stage 1: Build frontend assets
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --silent

COPY frontend/ ./
RUN npm run build

# Stage 2: Build Python runtime
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies
COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy application code
COPY backend/ backend/
COPY config/ config/
COPY manage.py .
COPY start.sh setup.sh ./

# Copy built frontend assets from stage 1
COPY --from=frontend-builder /app/static/ static/

# Create log directory
RUN mkdir -p /root/logs/asri

# Expose port
EXPOSE 8000

# Run migrations, seed data, and start server
CMD ["bash", "-c", "cd backend && python manage.py migrate --noinput && python manage.py seed_data && daphne -b 0.0.0.0 -p 8000 config.asgi:application"]
