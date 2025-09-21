# FileIO MCP Server Dockerfile
FROM python:3.11-slim

LABEL maintainer="n8n Stack"
LABEL description="FileIO MCP Server for n8n workflow file operations"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r mcpuser && useradd -r -g mcpuser mcpuser

# Create necessary directories
RUN mkdir -p /app/logs /app/config && \
    chown -R mcpuser:mcpuser /app

# Copy package definition first for better layer caching
COPY pyproject.toml .

# Install dependencies only (without source code)
RUN pip install --no-cache-dir .

# Copy source code (all in root directory)
COPY *.py .
COPY *.json .

# Install the package in development mode (editable)
RUN pip install -e .

# Create logs directory and set permissions
RUN mkdir -p /app/logs && chown -R mcpuser:mcpuser /app

# Switch to non-root user
USER mcpuser

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from config import FileIOConfig; FileIOConfig.load()" || exit 1

# Default command
CMD ["python", "mcp_server.py"]