# MCP Servers for n8n Stack

Model Context Protocol (MCP) servers providing AI agents with access to n8n workflow data and operations.

## Overview

This directory contains containerized MCP servers that extend AI capabilities with:
- **File Operations**: Access to n8n workflow directories (ingress, wip, completed)
- **Database Operations**: Direct queries to PostgreSQL and MongoDB instances
- **Workflow Control**: n8n workflow management and monitoring
- **System Monitoring**: Health checks and performance metrics

## Architecture

```
mcp/
├── fileio/              # File operations MCP server
├── n8n-control/         # n8n workflow management (future)
├── database/            # Database operations (future)
├── monitoring/          # System monitoring (future)
├── gateway/             # Nginx gateway for HTTP access
├── logs/                # Shared logging directory
└── docker-compose.yml   # Container orchestration
```

## Quick Start

### 1. Start MCP Services

```bash
cd mcp
docker compose up -d
```

### 2. Check Service Status

```bash
docker compose ps
```

### 3. View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f fileio-mcp
```

## Services

### FileIO MCP Server

**Purpose**: Provides AI agents with secure file operations for n8n workflow directories.

**Capabilities**:
- Read files from ingress, wip, completed directories
- Write files to workflow directories (configurable)
- List directory contents with filtering
- Search files by name or content
- Get file metadata and statistics
- Directory tree visualization

**Access**:
- **Container**: `fileio-mcp:8000`
- **Gateway**: `http://localhost:8080/fileio/`
- **Direct**: `http://localhost:8001`

**Configuration**: `fileio/config/fileio_config.json`

### MCP Gateway

**Purpose**: HTTP gateway providing unified access to all MCP servers.

**Features**:
- Load balancing across MCP servers
- Health monitoring
- Request routing
- Centralized logging

**Access**: `http://localhost:8080`

## Configuration

### FileIO Configuration

Edit `fileio/config/fileio_config.json`:

```json
{
  "name": "fileio",
  "base_path": "/mnt/blk/lostboy/work",
  "allowed_directories": ["ingress", "wip", "completed"],
  "max_file_size": 10485760,
  "allowed_extensions": [".txt", ".json", ".csv", ".md", ".log"],
  "security": {
    "enable_write": true,
    "enable_delete": false,
    "sandbox_mode": true
  }
}
```

**Key Settings**:
- `base_path`: Root directory for file operations
- `allowed_directories`: Permitted subdirectories
- `max_file_size`: Maximum file size for read operations (bytes)
- `allowed_extensions`: Permitted file types for write operations
- `security.enable_write`: Allow file write operations
- `security.sandbox_mode`: Restrict access to allowed directories only

## Usage with AI Agents

### Claude Desktop Integration

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "fileio": {
      "command": "docker",
      "args": [
        "exec", "-i", "fileio_mcp",
        "python", "-m", "fileio_mcp.server"
      ]
    }
  }
}
```

### Direct HTTP Access

```bash
# List available tools
curl http://localhost:8080/fileio/tools

# Execute file operation
curl -X POST http://localhost:8080/fileio/execute \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "list_files",
    "arguments": {
      "directory": "ingress",
      "pattern": "*.json"
    }
  }'
```

### Example Operations

**Read a workflow file**:
```json
{
  "tool": "read_file",
  "arguments": {
    "directory": "completed",
    "path": "2024-01-15/processed_data.json"
  }
}
```

**Search for specific content**:
```json
{
  "tool": "search_files",
  "arguments": {
    "directory": "wip",
    "content_pattern": "error",
    "case_sensitive": false
  }
}
```

**Get directory statistics**:
```json
{
  "tool": "get_directory_stats",
  "arguments": {
    "directory": "completed",
    "recursive": true
  }
}
```

## Security

### File Access Control

- **Sandboxed**: Access restricted to configured directories only
- **Extension Filtering**: Write operations limited to safe file types
- **Size Limits**: Large file protection
- **Path Validation**: Prevents directory traversal attacks

### Container Security

- **Non-root User**: Services run as unprivileged user
- **Read-only Volumes**: n8n data mounted read-only where possible
- **Network Isolation**: Services isolated in dedicated Docker network
- **Resource Limits**: CPU and memory constraints

### Logging and Monitoring

- **Comprehensive Logging**: All operations logged with timestamps
- **Health Checks**: Automated service health monitoring
- **Audit Trail**: File operations tracked for security review

## Development

### Adding New MCP Servers

1. **Create Server Directory**:
   ```bash
   mkdir mcp/new-server
   cd mcp/new-server
   ```

2. **Follow FileIO Structure**:
   ```
   new-server/
   ├── src/new_server_mcp/
   ├── config/
   ├── Dockerfile
   ├── requirements.txt
   └── pyproject.toml
   ```

3. **Update Docker Compose**:
   Add service definition to `docker-compose.yml`

4. **Update Gateway**:
   Add routing rules to `gateway/nginx.conf`

### Testing

```bash
# Validate configuration
docker exec fileio_mcp python -m fileio_mcp.server --validate-only

# Run tests
docker exec fileio_mcp python -m pytest

# Check logs
docker compose logs fileio-mcp | tail -100
```

## Troubleshooting

### Common Issues

**Permission Errors**:
```bash
# Fix volume permissions
sudo chown -R 1000:1000 ../work/
```

**Configuration Errors**:
```bash
# Validate config
docker exec fileio_mcp python -c "from fileio_mcp.config import FileIOConfig; FileIOConfig.load().validate()"
```

**Connection Issues**:
```bash
# Check network connectivity
docker exec fileio_mcp ping n8ngui
```

### Log Analysis

```bash
# View real-time logs
docker compose logs -f fileio-mcp

# Check error logs
grep -i error logs/fileio.log

# Monitor file operations
grep "Tool called" logs/fileio.log | tail -20
```

## Roadmap

### Planned MCP Servers

- **n8n-control**: Workflow management and execution control
- **database**: Direct database queries for chat memory and vectors
- **monitoring**: System health and performance metrics
- **analytics**: Usage analytics and workflow optimization

### Future Enhancements

- **Authentication**: JWT-based authentication for HTTP access
- **Rate Limiting**: Request throttling and quota management
- **Caching**: Response caching for improved performance
- **Webhooks**: Event-driven notifications for file changes

## Support

### Logs Location
- **Container Logs**: `docker compose logs [service]`
- **Application Logs**: `logs/fileio.log`
- **Gateway Logs**: `logs/nginx/access.log`, `logs/nginx/error.log`

### Configuration Files
- **FileIO**: `fileio/config/fileio_config.json`
- **Gateway**: `gateway/nginx.conf`
- **Docker**: `docker-compose.yml`

### Health Checks
- **FileIO**: `http://localhost:8001/health`
- **Gateway**: `http://localhost:8080/health`
- **All Services**: `docker compose ps`