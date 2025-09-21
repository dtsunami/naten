#!/bin/bash

# Orenco n8n Docker Stack Setup Script
# Creates required directories that are ignored by git

echo "Creating required directories for Orenco n8n stack..."

# Create main data directories
mkdir -p naten/n8ngui
mkdir -p naten/n8nwork
mkdir -p naten/pgn8n
mkdir -p naten/pgvect
mkdir -p naten/pgchat
mkdir -p naten/redisn8n
mkdir -p mongo
mkdir -p work/ingress
mkdir -p work/wip
mkdir -p work/completed
mkdir -p workflows
mkdir -p mcp/logs
mkdir -p credentials

echo "Created directories:"
echo "  - naten/ (n8n and database volumes)"
echo "  - mongo/ (MongoDB data)"
echo "  - work/ (workflow processing)"
echo "  - workflows/ (n8n workflow files)"
echo "  - logs/ (application logs)"
echo "  - mcp/logs/ (MCP server logs)"
echo "  - credentials/ (sensitive files)"

# Set appropriate permissions
chmod 755 naten
chmod 755 mongo
chmod 755 work
chmod 755 workflows
chmod 755 logs
chmod 700 credentials

echo ""
echo "Setup complete! You can now run:"
echo "  cp .env.example .env"
echo "  docker-compose up -d"