# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the Orenco n8n Docker Stack - a complete containerized setup for n8n workflow automation with integrated databases and MCP servers. The project provides a multi-database environment supporting workflow automation, vector operations, chat memory, document storage, and Model Context Protocol (MCP) services.

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

## Standing Orders for Development

### 1. Docker Image Management
- **ALWAYS use new tag with docker image updates**
- Never reuse existing tags when modifying services
- Use descriptive tags like `dashboard:v1`, `dashboard:orenco`, `mongo-mcp:fixed`
- Update docker-compose.yml with new tag before restarting services

### 2. Python Code Standards
- **Never use extra classes in Python code**
- Keep code simple and functional
- Use direct function calls and data structures
- Avoid unnecessary object-oriented complexity

### 3. Technology Stack
- **Python backend and JavaScript frontend**
- Backend: FastAPI, asyncio, pydantic models
- Frontend: Vanilla JavaScript, HTML, CSS
- No React, Vue, or other frontend frameworks
- Keep frontend lightweight and responsive

### Directory Structure
- `work/`: Workflow data processing directory
  - `ingress/`: Entry point for new data and workflow inputs
  - `wip/`: Active processing area for workflows in progress
  - `completed/`: Final destination for processed data and outputs
- `naten/`: n8n instance directory with services and configurations
- `*.json`: n8n workflow definitions and configurations
- `.env.example`: Template for environment configuration

## Development Commands

### Docker Operations
```bash
# Start all services
docker-compose up -d

# Stop all services
docker-compose down

# View logs for specific service
docker-compose logs -f [service_name]

# Check service health status
docker-compose ps

# Restart a service
docker-compose restart [service_name]
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
docker-compose exec mongo mongosh -u lostboy -p OrencoMongo2024* --authenticationDatabase admin
```

### MCP Server Management
```bash
# Build and restart an MCP server
docker build -t server:new_tag ./mcp/server_name
docker-compose restart server_name

# Test MCP server health
curl http://localhost:PORT/health

# Test MCP tools
curl -X POST http://localhost:PORT/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
```

## Service Access Points

- **n8n UI**: http://localhost:5678 (admin/admin123)
- **Orenco Dashboard**: http://localhost:8090
- **MCP Gateway**: http://localhost:8080
- **PostgreSQL Main**: localhost:5432
- **PostgreSQL Vector**: localhost:5433
- **PostgreSQL Chat**: localhost:5434
- **Redis**: localhost:6379
- **MongoDB**: localhost:27017

### MCP Server Endpoints
- **FileIO MCP**: http://localhost:8000 (direct) or http://localhost:8080/fileio/ (via gateway)
- **Python MCP**: http://localhost:8002 (direct) or http://localhost:8080/python/ (via gateway)
- **Search MCP**: http://localhost:8003 (direct) or http://localhost:8080/search/ (via gateway)
- **MongoDB MCP**: http://localhost:8004 (direct) or http://localhost:8080/mongo/ (via gateway)

## Configuration

Environment variables are configured in `.env` file with current Orenco credentials. All services use the credentials defined in the environment file:
- All databases use `lostboy` as the primary user

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

## File Processing Workflow

The system follows a standardized workflow pattern:
1. **Ingest**: Place data in `work/ingress/`
2. **Process**: Move to `work/wip/` during active processing
3. **Complete**: Archive results in `work/completed/`

Use timestamped subdirectories and implement retention policies for efficient file management.