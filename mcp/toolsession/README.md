# ToolSession MCP Server

Interactive tool session management for EDA tools and command-line interfaces.

## Features

- **Stateless Server Design**: No persistent sessions stored in server
- **Interactive Shell Management**: Spawn tools, detect prompts, execute commands
- **Multi-tool Support**: EDA tools (Fusion Compiler, Innovus, Genus) and general tools (bash, python)
- **Real-time Output**: Monitor tool output with prompt detection
- **Script Execution**: Execute scripts with temporary file handling

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   MCP Client    │◄──►│  ToolSession    │◄──►│   EDA Tool      │
│   (Claude)      │    │   MCP Server    │    │  (Interactive)  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │
                              ▼
                       ┌─────────────────┐
                       │  Output Monitor │
                       │    (Thread)     │
                       └─────────────────┘
```

## MCP Tools

| Tool | Description | Arguments |
|------|-------------|-----------|
| `start_session` | Start interactive tool session | `tool` (string) |
| `input` | Send command to active session | `command` (string) |
| `output` | Get session output | `lines` (int, optional) |
| `script` | Execute script in session | `text` (string), `command` (string) |
| `session_status` | Get current session info | none |
| `stop_session` | Stop active session | none |

## Usage Examples

### 1. Start EDA Tool Session

```python
# Start Fusion Compiler
result = await mcp_call("start_session", {"tool": "fusion_compiler"})

# Start Innovus
result = await mcp_call("start_session", {"tool": "innovus"})
```

### 2. Execute Commands

```python
# Load design library
await mcp_call("input", {"command": "read_lib /path/to/library.lib"})

# Check status
await mcp_call("input", {"command": "current_design"})

# Get output
output = await mcp_call("output", {"lines": 10})
```

### 3. Execute Scripts

```python
# TCL script for synthesis
script_content = '''
read_verilog /path/to/design.v
elaborate my_design
compile
write_verilog /path/to/output.v
'''

await mcp_call("script", {
    "text": script_content,
    "command": "source {script}"
})
```

## Configuration

Edit `config.json` to add/modify tools:

```json
{
  "tools": {
    "my_tool": {
      "environment_command": "source /path/to/setup.sh",
      "launch_command": "my_tool -interactive",
      "prompt_string": "mytool> ",
      "working_directory": "/project/work",
      "timeout": 300
    }
  }
}
```

### Configuration Fields

- **environment_command**: Optional setup command (e.g., sourcing environment)
- **launch_command**: Command to start the tool
- **prompt_string**: String that indicates tool is ready for input
- **working_directory**: Directory to run tool from
- **timeout**: Maximum seconds to wait for prompt

## Installation

```bash
cd mcp/toolsession
pip install -r requirements.txt
python toolsession_server.py --config config.json
```

## Server Endpoints

- **MCP**: `http://localhost:8002/mcp` (JSON-RPC)
- **Health**: `http://localhost:8002/health`

## Example Workflow

```python
# 1. Start session
await start_session(tool="fusion_compiler")

# 2. Load libraries and design
await input(command="read_lib /libs/tech.lib")
await input(command="read_design /designs/cpu.v")

# 3. Execute synthesis script
script = "synthesize -effort high"
await script(text=script, command="source {script}")

# 4. Get results
output = await output(lines=50)

# 5. Clean up
await stop_session()
```

## Error Handling

The server provides detailed error messages for:

- **Session Errors**: Failed to start tool, environment issues
- **Command Errors**: Invalid commands, timeout waiting for prompt
- **Script Errors**: File creation issues, script execution failures
- **Configuration Errors**: Missing tools, invalid settings

## Integration with n8n Stack

The ToolSession server integrates with the existing MCP architecture:

```
mcp/
├── fileio/              # File operations
├── toolsession/         # Interactive tool sessions ←
├── gateway/             # HTTP gateway
└── docker-compose.yml   # Container orchestration
```

Add to `docker-compose.yml`:

```yaml
toolsession-mcp:
  build: ./toolsession
  ports:
    - "8002:8002"
  volumes:
    - ../work:/project/work
    - ./logs:/app/logs
```