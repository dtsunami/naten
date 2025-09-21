#!/bin/bash

# Claude Code Ubuntu Installation Script
# This script installs Claude Code and its dependencies on Ubuntu

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Claude Code Ubuntu Installation Script${NC}"
echo "======================================"

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo -e "${RED}Please do not run this script as root${NC}"
    exit 1
fi

# Update package lists
echo -e "${YELLOW}Updating package lists...${NC}"
sudo apt update

# Install Node.js and npm
echo -e "${YELLOW}Installing Node.js and npm...${NC}"
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt-get install -y nodejs

# Verify Node.js installation
NODE_VERSION=$(node --version)
NPM_VERSION=$(npm --version)
echo -e "${GREEN}Node.js version: $NODE_VERSION${NC}"
echo -e "${GREEN}npm version: $NPM_VERSION${NC}"

# Install Claude Code globally
echo -e "${YELLOW}Installing Claude Code...${NC}"
#sudo npm install -g @anthropic/claude
sudo npm install -g @anthropic-ai/claude

# Verify Claude Code installation
if command -v claude &> /dev/null; then
    CLAUDE_VERSION=$(claude --version)
    echo -e "${GREEN}Claude Code installed successfully!${NC}"
    echo -e "${GREEN}Version: $CLAUDE_VERSION${NC}"
fi

#else
#    echo -e "${RED}Claude Code installation failed${NC}"
#    exit 1
#fi

# Install optional dependencies
echo -e "${YELLOW}Installing optional dependencies...${NC}"

# Install Python and pip (for Python workflows)
sudo apt-get install -y python3 python3-pip

# Install Docker (for containerized workflows)
echo -e "${YELLOW}Installing Docker...${NC}"
sudo apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
#echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Add user to docker group
sudo usermod -aG docker $USER

# Install Git (if not already installed)
sudo apt-get install -y git

# Install ripgrep (for better search performance)
sudo apt-get install -y ripgrep

# Install additional useful tools
echo -e "${YELLOW}Installing additional development tools...${NC}"
sudo apt-get install -y curl wget unzip zip tree jq

echo ""
echo -e "${GREEN}Installation completed successfully!${NC}"
echo ""
echo "Next steps:"
echo "1. Log out and log back in (or run 'newgrp docker') to use Docker without sudo"
echo "2. Run 'claude --help' to see available commands"
echo "3. Run 'claude auth' to authenticate with your Anthropic API key"
echo ""
echo -e "${YELLOW}Note: You may need to restart your terminal for all changes to take effect${NC}"