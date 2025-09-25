# da_code - Agentic CLI Tool

An intelligent command-line interface that combines LangChain agents with Azure OpenAI to provide an interactive coding assistant. Execute commands safely with user confirmation, leverage MCP servers, and monitor your AI interactions.

## 🌟 Features

- **🤖 LangChain Agent**: Powered by Azure OpenAI (GPT-4/3.5-turbo)
- **🔒 Safe Command Execution**: All commands require user approval with risk assessment
- **📋 Project Context Awareness**: Loads project information from DA.md
- **🔧 MCP Server Integration**: Connect to Model Context Protocol servers
- **📊 AgentOps Monitoring**: Optional performance and cost tracking
- **💾 Session Management**: Persistent tracking of all interactions and commands
- **⚡ Interactive CLI**: Rich terminal interface with conversation memory

## 🚀 Quick Start

### Installation

```bash
# Clone or navigate to the da_code directory
cd da_code

# Install the package
pip install -e .

# Or install with optional dependencies
pip install -e ".[monitoring,dev]"
```

### Setup

1. **Create configuration files:**
   ```bash
   da_code setup
   ```

2. **Configure Azure OpenAI:**
   Edit `.env.da_code` with your credentials:
   ```bash
   AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
   AZURE_OPENAI_API_KEY=your_api_key_here
   AZURE_OPENAI_DEPLOYMENT=gpt-4
   ```

3. **Customize project context:**
   Edit `DA.md` with your project information

4. **Configure MCP servers:**
   Edit `DA.json` with your MCP server endpoints

5. **Start interactive session:**
   ```bash
   da_code
   ```

## 📖 Usage

### Interactive Commands

```bash
# Start interactive session
da_code

# Create configuration files
da_code setup

# Check configuration status
da_code status

# Start with specific working directory
da_code --working-dir /path/to/project

# Enable debug logging
da_code --log-level DEBUG
```

### Interactive Session

Once in the session, you can:

- **Ask questions**: "What files are in this directory?"
- **Request operations**: "Install the requests package"
- **Code analysis**: "Review the main.py file for potential issues"
- **System commands**: "Run the test suite"

### Special Commands

During interactive session:
- `help` or `h` - Show help information
- `status` or `info` - Show current session info
- `clear` or `cls` - Clear conversation memory
- `exit`, `quit`, or `q` - End session

## 🔧 Configuration

### Environment Variables

Create `.env.da_code` with:

```bash
# Required: Azure OpenAI Configuration
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your_api_key_here
AZURE_OPENAI_DEPLOYMENT=gpt-4
AZURE_OPENAI_API_VERSION=2023-12-01-preview

# Optional: Agent Behavior
DA_CODE_TEMPERATURE=0.7
DA_CODE_MAX_TOKENS=
DA_CODE_TIMEOUT=60
DA_CODE_MAX_RETRIES=2
DA_CODE_COMMAND_TIMEOUT=300
DA_CODE_REQUIRE_CONFIRMATION=true

# Optional: AgentOps Monitoring
AGENTOPS_API_KEY=your_agentops_key_here
DA_CODE_AGENTOPS_TAGS=da_code,azure,langchain

# Optional: Logging
LOG_LEVEL=INFO
```

### Project Context (DA.md)

```markdown
# My Project

Brief description of your project.

## Instructions

Instructions for the AI agent:
- Key guidelines for working with this project
- Important files and directories
- Coding standards and preferences
- Testing procedures

## Architecture

Description of project architecture and key components.
```

### MCP Servers (DA.json)

```json
{
  "mcp_servers": [
    {
      "name": "fileio",
      "url": "http://localhost:8080/fileio",
      "port": 8000,
      "description": "File operations MCP server",
      "tools": ["read_file", "write_file", "list_files"]
    }
  ],
  "default_working_directory": "/path/to/project",
  "agent_settings": {
    "model": "gpt-4",
    "temperature": 0.7,
    "require_confirmation": true
  }
}
```

## 🛡️ Safety Features

### Command Confirmation

Every command execution requires user approval:

```
🤖 Agent wants to execute a command:
════════════════════════════════════════════════════════════
Command: pip install requests
Directory: /current/directory
Purpose: Install the requests library for HTTP operations
════════════════════════════════════════════════════════════

Do you want to execute this command?
1. [Y]es - Execute the command
2. [N]o - Cancel execution
3. [M]odify - Edit the command
4. [E]xplain - Show more details

Your choice:
```

### Risk Assessment

Dangerous commands are highlighted:

- 🚨 **DESTRUCTIVE**: Commands that may delete files
- 🔒 **PRIVILEGED**: Commands requiring admin privileges
- 🌐 **NETWORK**: Commands accessing the internet
- ⚙️ **SYSTEM**: Commands affecting system services

## 📊 Monitoring with AgentOps

Enable comprehensive monitoring by setting `AGENTOPS_API_KEY`:

- **Performance Tracking**: Response times and token usage
- **Cost Monitoring**: Track Azure OpenAI API costs
- **Session Analytics**: Command success rates and patterns
- **Error Tracking**: Detailed error logs and contexts
- **Interactive Dashboard**: View real-time session metrics

## 🔌 MCP Server Integration

da_code integrates with Model Context Protocol servers for specialized operations:

```python
# Example MCP call through agent
"Use the fileio server to read the config.json file"
"Search for Python files using the search MCP server"
"Query the database using the mongodb MCP server"
```

Available MCP servers in this stack:
- **fileio**: File operations and directory management
- **python**: Interactive Python code execution
- **search**: Web search and content extraction
- **mongodb**: Database operations and queries

## 🧩 Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   User Input    │───▶│  LangChain Agent │───▶│  Azure OpenAI   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                        │                        │
         ▼                        ▼                        ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ User Approval   │    │ Command Executor │    │   MCP Servers   │
│   Workflow      │    │   with Safety    │    │   Integration   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                        │                        │
         ▼                        ▼                        ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ Session Tracking│    │   Shell Process  │    │ AgentOps Monitor│
│   & Persistence │    │   Management     │    │   & Analytics   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## 🔍 Example Session

```bash
$ da_code

🤖 da_code - Your AI Coding Assistant
════════════════════════════════════════════════════════════
📁 Project: My Web Application
📂 Working Directory: /home/user/myproject
🤖 Agent Model: gpt-4
🔧 MCP Servers: 4 available

💡 Available commands:
  - Ask questions about your project
  - Request code changes or analysis
  - Execute system commands (with confirmation)
  - Use MCP servers for specialized operations
════════════════════════════════════════════════════════════

🚀 Ready! How can I help you?

👤 You: What Python files are in this directory?

🤖 Assistant: I'll help you list the Python files in the current directory.

[Command execution with user approval...]

✅ Command executed successfully
Found 3 Python files:
- main.py (entry point)
- config.py (configuration)
- utils.py (utility functions)

👤 You: Install pytest for testing

🤖 Assistant: I'll install pytest for you. This will add the testing framework to your Python environment.

[Shows command confirmation dialog...]

✅ Command executed successfully
pytest installed successfully!

👤 You: exit

👋 Ending session...

📊 Session Summary:
  Duration: 124.5 seconds
  Commands: 2 executed
  Success rate: 100.0%
```

## 🛠️ Development

### Project Structure

```
da_code/
├── __init__.py          # Package initialization
├── models.py            # Pydantic2 data models
├── context.py           # Project context loading
├── config.py            # Configuration management
├── shell.py             # Command execution with approval
├── agent.py             # LangChain agent implementation
├── monitoring.py        # AgentOps integration
├── cli.py               # CLI entry point
├── pyproject.toml       # Project configuration
└── README.md           # This file
```

### Running Tests

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Code formatting
black da_code/

# Type checking
mypy da_code/

# Linting
ruff check da_code/
```

### Adding New Features

1. **New Tools**: Add to `agent.py` `_create_tools()` method
2. **New Commands**: Extend `cli.py` argument parser
3. **New Models**: Add to `models.py` with Pydantic2
4. **MCP Integration**: Extend `MCPTool` class in `agent.py`

## ❗ Troubleshooting

### Common Issues

**Configuration not found:**
```bash
da_code setup
# Edit .env.da_code with your Azure OpenAI credentials
```

**Azure OpenAI connection failed:**
- Verify endpoint URL format: `https://resource-name.openai.azure.com/`
- Check API key is valid and has proper permissions
- Ensure deployment name matches your Azure OpenAI deployment

**MCP servers not responding:**
- Check server URLs in DA.json
- Verify MCP servers are running: `docker compose ps`
- Test server health: `curl http://localhost:8080/fileio/health`

**Commands hanging:**
- Check timeout settings in configuration
- Verify working directory exists and is accessible
- Review command for interactive prompts that need input

### Debug Mode

Run with debug logging to see detailed information:

```bash
da_code --log-level DEBUG
```

### Configuration Check

Verify your setup:

```bash
da_code status
```

## 📄 License

MIT License - see LICENSE file for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Run the test suite
6. Submit a pull request

## 🆘 Support

- Check the troubleshooting section above
- Review configuration with `da_code status`
- Enable debug logging for detailed error information
- Check AgentOps dashboard for monitoring insights

---

**Built with ❤️ using LangChain, Azure OpenAI, and the power of human-AI collaboration.**