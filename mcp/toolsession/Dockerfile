FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy pyproject.toml first for better caching
COPY pyproject.toml .

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Copy application code
COPY . .

# Create directories for logs and sessions
RUN mkdir -p /app/logs

# Create non-root user for security
RUN useradd -m -u 1000 toolsession && \
    chown -R toolsession:toolsession /app

USER toolsession

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8002/health || exit 1

# Expose port
EXPOSE 8002

# Default command - launch Python ToolSession server
CMD ["python", "launch_python_server.py", "--port", "8002"]