# ============================================================
# Cloud Task Manager - Production Dockerfile
# Multi-stage build for smaller image size
# ============================================================
FROM python:3.11-slim AS base

# Security: don't run as root
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Install dependencies first (Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Set environment
ENV FLASK_APP=app.main:app
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 5000

# Health check for Kubernetes/ECS
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5000/health', timeout=3)" || exit 1

# Switch to non-root user
USER appuser

# Run with gunicorn (production WSGI server)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "120", "app.main:app"]
