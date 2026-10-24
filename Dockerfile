# Multi-stage production container for Agent Assurance Laboratory (Doc 2 §3)
FROM python:3.13-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Install security updates and curl for health probes
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application
COPY backend /app/backend

# Copy frontend static files
COPY frontend /app/frontend

# Create non-root runtime user for security (Doc 2 §4)
RUN groupadd -r assurance && useradd -r -g assurance -d /app assurance \
    && chown -R assurance:assurance /app

USER assurance

EXPOSE 8000

# Health check probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run API server
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
