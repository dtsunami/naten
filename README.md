# Orenco n8n Docker Stack

A complete containerized setup for n8n workflow automation with integrated databases and MCP servers.

**Repository**: https://github.com/dtsunami/naten

## Overview

This project provides a multi-database environment supporting workflow automation, vector operations, chat memory, document storage, and Model Context Protocol (MCP) services.

## Architecture

### Core Services
- **n8n**: Workflow automation platform running in queue execution mode with Redis
- **Redis**: Message queue and caching layer for n8n workflows
- **PostgreSQL (3 instances)**:
  - Main DB: n8n execution history and workflow data
  - Vector DB: pgvector extension for vector operations
  - Chat DB: Chat memory and conversation storage
- **MongoDB**: Document storage for Pydantic models

### MCP Servers
- **FileIO MCP**: File operations for n8n workflows (port 8000)
- **Python MCP**: Interactive Python tool sessions (port 8002)
- **Search MCP**: Web search and content extraction (port 8003)
- **MongoDB MCP**: Database operations for MongoDB (port 8004)
- **MCP Gateway**: Nginx proxy for all MCP services (port 8080)

### Management
- **Orenco Dashboard**: Service health monitoring (port 8090)

## Quick Start

1. Clone the repository:
   ```bash
   git clone https://github.com/dtsunami/naten.git
   cd naten
   ```

2. Run setup script to create required directories:
   ```bash
   ./setup.sh
   ```

3. Copy environment template:
   ```bash
   cp .env.example .env
   ```

4. Start all services:
   ```bash
   docker-compose up -d
   ```

5. Access n8n UI at http://localhost:5678 (admin/admin123)

## Service Access Points

- **n8n UI**: http://localhost:5678 (admin/admin123)
- **Orenco Dashboard**: http://localhost:8090
- **MCP Gateway**: http://localhost:8080

### Database Endpoints
- **PostgreSQL Main**: localhost:5432
- **PostgreSQL Vector**: localhost:5433
- **PostgreSQL Chat**: localhost:5434
- **Redis**: localhost:6379
- **MongoDB**: localhost:27017

### MCP Server Endpoints
- **FileIO MCP**: http://localhost:8000 or http://localhost:8080/fileio/
- **Python MCP**: http://localhost:8002 or http://localhost:8080/python/
- **Search MCP**: http://localhost:8003 or http://localhost:8080/search/
- **MongoDB MCP**: http://localhost:8004 or http://localhost:8080/mongo/

## File Processing Workflow

The system follows a standardized workflow pattern:
1. **Ingest**: Place data in `work/ingress/`
2. **Process**: Move to `work/wip/` during active processing
3. **Complete**: Archive results in `work/completed/`

## Management Commands

### Docker Operations
```bash
# View service status
docker-compose ps

# View logs for specific service
docker-compose logs -f [service_name]

# Restart a service
docker-compose restart [service_name]

# Stop all services
docker-compose down
```

### Database Access
```bash
# PostgreSQL main database
docker-compose exec pgn8n psql -U lostboy -d orenco_workflows

# PostgreSQL vector database
docker-compose exec pgvect psql -U lostboy -d orenco_vectors

# PostgreSQL chat database
docker-compose exec pgchat psql -U lostboy -d orenco_chatmemory

# Redis CLI access
docker-compose exec redisn8n redis-cli

# MongoDB shell
docker-compose exec mongo mongosh -u lostboy -p ... --authenticationDatabase admin
```

## Data Persistence

All data persists through Docker volumes:
- `./naten/n8ngui/`: n8n GUI workflows and settings
- `./naten/n8nwork/`: n8n Worker configuration
- `./naten/pgn8n/`: PostgreSQL main database storage
- `./naten/pgvect/`: PostgreSQL vector database storage
- `./naten/pgchat/`: PostgreSQL chat database storage
- `./naten/redisn8n/`: Redis queue and cache data
- `./mongo/`: MongoDB document storage
- `./work/`: Workflow processing directories

## Development

See [CLAUDE.md](CLAUDE.md) for detailed development guidelines and commands.