# 🚀 Orenco n8n Docker Stack

[![Docker](https://img.shields.io/badge/docker-supported-blue.svg)](https://docker.com)

[![n8n](https://img.shields.io/badge/n8n-automation-orange.svg)](https://n8n.io)

[![MCP](https://img.shields.io/badge/MCP-protocol-green.svg)](https://github.com/anthropics/mcp)

[![PostgreSQL](https://img.shields.io/badge/postgresql-15-blue.svg)](https://postgresql.org)

[![Status](https://img.shields.io/badge/status-production-green.svg)](http://192.168.1.77:8090)

> **A complete containerized ecosystem for n8n workflow automation with integrated databases and Model Context Protocol (MCP) servers.**

## 🎯 Overview

The Orenco n8n Docker Stack provides a production-ready environment for workflow automation, featuring:

- **🔄 n8n Workflow Engine**: Queue-based execution with Redis

- **🗄️ Multi-Database Support**: PostgreSQL (3 instances) + MongoDB + Redis

- **🤖 AI Integration**: MCP servers for enhanced AI agent capabilities

- **📊 Real-time Monitoring**: Health dashboard and service metrics

- **🔐 Security-First**: Sandboxed operations and credential management

- **⚡ High Performance**: Optimized for production workloads

## 🏗️ Architecture

```

┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐

│   Web Layer     │    │  Processing     │    │  Data Storage   │

│                 │    │                 │    │                 │

│ n8n GUI  :5678  │◄──►│ n8n Worker      │◄──►│ PostgreSQL Main │

│ Dashboard:8090  │    │ Redis Queue     │    │ PostgreSQL Vect │

│ MCP Gate :8080  │    │                 │    │ PostgreSQL Chat │

└─────────────────┘    └─────────────────┘    │ MongoDB         │

          │                                   └─────────────────┘

          ▼

┌─────────────────┐

│  MCP Services   │

│                 │

│ FileIO   :8000  │

│ Python   :8002  │

│ Search   :8003  │

│ MongoDB  :8004  │

└─────────────────┘

```

## ⚡ Quick Start

### Prerequisites

- Docker & Docker Compose

- 8GB+ RAM recommended

- 20GB+ free disk space

### 1. Clone & Configure

```bash

git clone <repository-url> orenco-stack

cd orenco-stack

cp .env.example .env

# Edit .env with your configuration

```

### 2. Launch Stack

```bash

# Start all services

docker-compose up -d

# Check service health

docker-compose ps

# View logs

docker-compose logs -f

```

### 3. Access Services

- **n8n GUI**: http://localhost:5678

- **Dashboard**: http://localhost:8090 (or http://192.168.1.77:8090)

- **MCP Gateway**: http://localhost:8080

## 🔧 Services Overview

### Core Automation Platform

| Service | Description | Port | Status |

|---------|-------------|------|---------|

| **n8n GUI** | Workflow designer interface | 5678 | ✅ Running |

| **n8n Worker** | Background workflow execution | - | ✅ Running |

| **Dashboard** | Health monitoring & metrics | 8090 | ✅ Running |

### Data Layer

| Service | Description | Port | Database |

|---------|-------------|------|----------|

| **PostgreSQL Main** | Workflow data & history | 5432 | `orenco_workflows` |

| **PostgreSQL Vector** | Vector embeddings (pgvector) | 5433 | `orenco_vectors` |

| **PostgreSQL Chat** | Conversation memory | 5434 | `orenco_chatmemory` |

| **MongoDB** | Document storage | 27017 | `orenco_documents` |

| **Redis** | Message queue & cache | 6379 | - |

### AI Integration (MCP Servers)

| Service | Description | Port | Image Tag |

|---------|-------------|------|-----------|

| **FileIO MCP** | File operations for workflows | 8000 | `fileio:v2` |

| **Python MCP** | Interactive Python sessions | 8002 | `toolsession:v2` |

| **Search MCP** | Web search & content extraction | 8003 | `search:v2` |

| **MongoDB MCP** | Database operations | 8004 | `mongodb:v2` |

| **MCP Gateway** | HTTP proxy for MCP services | 8080 | `nginx:alpine` |

## 🛠️ Development

### Building MCP Services

```bash

# Rebuild all MCP services with new version tag

docker-compose build --no-cache fileio python search mcpmongo

# Update image tags in docker-compose.yml

# Then restart services

docker-compose up -d

```

### Database Operations

```bash

# PostgreSQL main database

docker-compose exec pgn8n psql -U orenco -d orenco_workflows

# PostgreSQL vector database

docker-compose exec pgvect psql -U orenco -d orenco_vectors

# PostgreSQL chat database

docker-compose exec pgchat psql -U orenco -d orenco_chatmemory

# MongoDB shell

docker-compose exec mongo mongosh -u orenco --authenticationDatabase admin

# Redis CLI

docker-compose exec redisn8n redis-cli

```

### Monitoring & Logs

```bash

# View all service statuses

curl -s http://localhost:8090/api/health | jq

# Service-specific logs

docker-compose logs -f fileio

docker-compose logs -f python

docker-compose logs -f n8ngui

# System resources

docker stats

```

## 📊 Features

### Workflow Automation

- ✅ **Visual Workflow Designer**: Drag-and-drop interface

- ✅ **400+ Integrations**: APIs, databases, cloud services

- ✅ **Queue-Based Execution**: Scalable background processing

- ✅ **Error Handling**: Retry logic and error workflows

- ✅ **Scheduled Execution**: Cron-based triggers

### AI & Machine Learning

- ✅ **Vector Database**: pgvector for embeddings

- ✅ **Chat Memory**: Persistent conversation context

- ✅ **MCP Integration**: AI agent file & database access

- ✅ **Python Sessions**: Interactive code execution

- ✅ **Web Search**: Content extraction and analysis

### Security & Operations

- ✅ **Multi-Database Architecture**: Isolated data layers

- ✅ **Health Monitoring**: Real-time service status

- ✅ **Audit Logging**: Complete operation history

- ✅ **Sandboxed Execution**: Secure file operations

- ✅ **Credential Management**: Encrypted secret storage

## 📁 Directory Structure

```

orenco-stack/

├── mcp/                    # MCP servers and shared modules

│   ├── basemcp/           # Shared foundation (BaseMCPServer)

│   ├── fileio/            # File operations MCP server

│   ├── toolsession/       # Python session MCP server

│   ├── search/            # Web search MCP server

│   ├── mongodb/           # MongoDB operations MCP server

│   └── gateway/           # Nginx proxy configuration

├── dashboard/             # Health monitoring service

├── work/                  # Workflow data directories

│   ├── ingress/          # Input files

│   ├── wip/              # Work in progress

│   └── completed/        # Finished workflows

├── naten/                 # n8n persistent data

├── docker-compose.yml     # Service orchestration

├── .env.example          # Configuration template

└── CLAUDE.md             # Development guidelines

```

## 🔌 API Access

### MCP Server Health Checks

```bash

# FileIO MCP

curl http://localhost:8000/health

# Python MCP

curl http://localhost:8002/health

# Search MCP

curl http://localhost:8003/health

# MongoDB MCP

curl http://localhost:8004/health

```

### Dashboard API

```bash

# Overall system health

curl http://localhost:8090/api/health

# Service metrics

curl http://localhost:8090/api/metrics

# Database status

curl http://localhost:8090/api/databases

```

## 🚨 Troubleshooting

### Service Won't Start

```bash

# Check logs

docker-compose logs [service-name]

# Restart service

docker-compose restart [service-name]

# Rebuild if needed

docker-compose build --no-cache [service-name]

```

### Database Connection Issues

```bash

# Complete stack restart (clears stale connections)

docker-compose down

docker-compose up -d

# Check database health

curl http://localhost:8090/api/health | jq '.services[] | select(.type=="database")'

```

### MCP Import Errors

- All MCP servers use: `from basemcp.server import BaseMCPServer`

- Build context: `./mcp` (shared root directory)

- PYTHONPATH: `/app` (set in Dockerfiles)

## 📈 Performance

### Resource Requirements

- **Minimum**: 4GB RAM, 2 CPU cores, 10GB disk

- **Recommended**: 8GB RAM, 4 CPU cores, 20GB disk

- **Production**: 16GB RAM, 8 CPU cores, 50GB disk

### Scaling

- **Horizontal**: Add n8n worker instances

- **Database**: PostgreSQL read replicas

- **Queue**: Redis cluster for high throughput

- **MCP**: Load balance through gateway

## 🤝 Contributing

1. Fork the repository

2. Create feature branch: `git checkout -b feature/amazing-feature`

3. Follow CLAUDE.md development guidelines

4. Test with full stack: `docker-compose up -d`

5. Update documentation as needed

6. Submit pull request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

- **Issues**: [GitHub Issues](../../issues)

- **Documentation**: See individual service README files

- **Dashboard**: http://localhost:8090 for real-time status

- **Logs**: `docker-compose logs -f [service]`

---

**Status**: ✅ Production Ready | **Last Updated**: 2025-09-25 | **Version**: v2.0