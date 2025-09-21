# Dashboard FastAPI App Dockerfile
FROM python:3.11-slim

LABEL maintainer="n8n Stack"
LABEL description="Health Dashboard for n8n Stack Services"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and add to docker group
RUN groupadd -r dashboard && useradd -r -g dashboard dashboard \
    && groupadd -g 988 docker \
    && usermod -aG docker dashboard

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app.py .
COPY templates/ templates/
COPY static/ static/

# Create logs directory and set permissions
RUN mkdir -p /app/logs && chown -R dashboard:dashboard /app

# Switch to non-root user
USER dashboard

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/api/health || exit 1

# Expose port
EXPOSE 8080

# Default command
CMD ["python", "app.py"]