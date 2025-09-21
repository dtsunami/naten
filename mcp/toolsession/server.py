"""ToolSession MCP Server - Interactive tool session with DB persistence."""

import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from typing import Any, Dict, List, Optional, Union

# Add current directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from tools import ToolSession, ToolConfig
from ts_mongo import upsert_session

# Global state
session: Optional[ToolSession] = None
process: Optional[subprocess.Popen] = None
output_thread: Optional[threading.Thread] = None
output_queue: Queue = Queue()
prompt_detected: threading.Event = threading.Event()
session_active: bool = False
current_output_buffer: str = ""
last_input_id: Optional[str] = None
logger: Optional[logging.Logger] = None

# FastAPI app
app = FastAPI(
    title="ToolSession MCP Server",
    description="Interactive tool session with DB persistence",
    version="1.0.0",
)
from fastapi_mcp import FastApiMCP
mcp = FastApiMCP(app)
mcp.mount()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def save_session():
    """Save current session state to database."""
    if session:
        try:
            await upsert_session(session)
        except Exception as e:
            logger.error(f"Failed to save session to DB: {e}")


def create_response(request_id: Union[str, int, None], result: Dict[str, Any]) -> Dict[str, Any]:
    """Create a successful MCP response."""
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def create_error_response(request_id: Union[str, int, None], code: int, message: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
    """Create an MCP error response."""
    error = {"code": code, "message": message}
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def monitor_output():
    """Monitor process output and detect prompts."""
    global current_output_buffer, last_input_id, session_active

    try:
        output_file = Path(session.output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w') as f:
            current_line = ""

            while process and process.poll() is None:
                char = process.stdout.read(1)
                if not char:
                    break

                # Write to file
                f.write(char)
                f.flush()

                # Add to output buffer
                current_output_buffer += char

                # Build current line
                if char == '\n':
                    output_queue.put(current_line)
                    current_line = ""
                else:
                    current_line += char

                # Check for prompt
                if current_line.strip().endswith(session.tool_config.prompt_string.strip()):
                    logger.debug(f"Prompt detected: {current_line.strip()}")

                    # Save output between prompts to session
                    if current_output_buffer.strip():
                        session.add_output(current_output_buffer.strip(), last_input_id)
                        current_output_buffer = ""

                    prompt_detected.set()

    except Exception as e:
        logger.error(f"Output monitoring error: {e}")
        if session:
            session.add_error("output_monitoring", str(e))


def wait_for_prompt(timeout: int = 30) -> bool:
    """Wait for prompt to appear."""
    prompt_detected.clear()
    return prompt_detected.wait(timeout)


def cleanup():
    """Clean up session resources."""
    global session_active, process

    session_active = False
    if session:
        session.update_status("stopped")

    if process:
        try:
            process.terminate()
            process.wait(timeout=5)
        except:
            try:
                process.kill()
                process.wait(timeout=2)
            except:
                pass
        process = None

    logger.info("Session cleaned up")


@app.on_event("startup")
async def startup_event():
    """Initialize DB connection, start tool session automatically."""

    await save_session()

    # Automatically start the tool session
    await auto_start_session()


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up session and disconnect from DB."""
    if session_active:
        cleanup()


@app.post("/input", )
async def mcp_endpoint(request: Request):
    """Main MCP JSON-RPC endpoint."""
    try:
        body = await request.json()
        response = await handle_mcp_request(body)
        return JSONResponse(content=response)
    except json.JSONDecodeError:
        return create_error_response(None, -32700, "Parse error")
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return create_error_response(None, -32603, "Internal error")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "session_id": session.session_id if session else None,
        "session_status": session.status if session else None,
        "session_active": session_active,
        "tool_name": session.tool_config.name if session else None
    }


async def handle_mcp_request(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle incoming MCP JSON-RPC request."""
    # Validate JSON-RPC structure
    if not isinstance(request_data, dict):
        return create_error_response(None, -32600, "Invalid Request")

    jsonrpc = request_data.get("jsonrpc")
    if jsonrpc != "2.0":
        return create_error_response(None, -32600, "Invalid JSON-RPC version")

    request_id = request_data.get("id")
    method = request_data.get("method")
    params = request_data.get("params", {})

    if not method:
        return create_error_response(request_id, -32600, "Missing method")

    logger.info(f"MCP request: {method} with params: {params}")

    try:
        # Route to appropriate handler
        if method == "initialize":
            result = await handle_initialize(params)
        elif method == "tools/list":
            result = await handle_tools_list(params)
        elif method == "tools/call":
            result = await handle_tools_call(params)
        else:
            return create_error_response(request_id, -32601, f"Method not found: {method}")

        return create_response(request_id, result)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error handling {method}: {error_msg}", exc_info=True)
        return create_error_response(request_id, -32603, error_msg)


async def handle_initialize(params: Dict[str, Any]) -> Dict[str, Any]:
    """Handle MCP initialize request."""
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {"listChanged": True}},
        "serverInfo": {"name": f"toolsession-{session.tool_config.name}", "version": "1.0.0"},
    }


async def handle_tools_list(params: Dict[str, Any]) -> Dict[str, Any]:
    """Handle tools/list request."""
    tools = [
        {
            "name": "input",
            "description": "Send input to the active session",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to send"}
                },
                "required": ["command"]
            }
        },
        {
            "name": "output",
            "description": "Get output from the session",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "lines": {"type": "integer", "description": "Number of recent lines"}
                }
            }
        },
        {
            "name": "script",
            "description": "Execute a script in the session",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Script content"},
                    "command": {"type": "string", "description": "Command to execute script"}
                },
                "required": ["text", "command"]
            }
        },
        {
            "name": "status",
            "description": "Get current session status",
            "inputSchema": {"type": "object", "properties": {}}
        }
    ]
    return {"tools": tools}


async def handle_tools_call(params: Dict[str, Any]) -> Dict[str, Any]:
    """Handle tools/call request."""
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    if not tool_name:
        raise ValueError("Tool name is required")

    logger.info(f"Executing tool: {tool_name} with args: {arguments}")

    # Route to appropriate handler
    if tool_name == "input":
        result = await input_tool(arguments)
    elif tool_name == "output":
        result = await output_tool(arguments)
    elif tool_name == "script":
        result = await script_tool(arguments)
    elif tool_name == "status":
        result = await status_tool(arguments)
    else:
        raise ValueError(f"Unknown tool: {tool_name}")

    return {"content": [{"type": "text", "text": result}], "isError": False}


async def auto_start_session():
    """Automatically start the tool session on server startup."""
    global session_active, process, output_thread, last_input_id

    if session_active:
        logger.info("Session already active")
        return

    try:
        session.update_status("starting")
        await save_session()

        # Change to working directory
        os.chdir(session.tool_config.working_directory)

        # Prepare command
        if session.tool_config.environment_command:
            command = f"{session.tool_config.environment_command} && {session.tool_config.launch_command}"
        else:
            command = session.tool_config.launch_command

        logger.info(f"Starting session with command: {command}")

        # Start process
        process = subprocess.Popen(
            command,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        # Update session with PID
        session.pid = process.pid

        # Start output monitoring thread
        output_thread = threading.Thread(target=monitor_output, daemon=True)
        output_thread.start()

        # Wait for initial prompt
        if not wait_for_prompt(timeout=30):
            error_msg = "Failed to detect initial prompt"
            session.add_error("startup", error_msg, {"timeout": 30})
            await save_session()
            raise RuntimeError(error_msg)

        session_active = True
        session.update_status("active")
        await save_session()

        logger.info(f"Session started successfully (PID: {process.pid})")

    except Exception as e:
        logger.error(f"Failed to start session: {e}")
        session.add_error("startup", str(e))
        await save_session()
        cleanup()
        raise RuntimeError(f"Session startup failed: {e}")


async def input_tool(args: Dict[str, Any]) -> str:
    """Send input to session."""
    global last_input_id

    if not session_active or not process:
        raise ValueError("Session not active")

    command = args.get("command")
    if not command:
        raise ValueError("Command is required")

    try:
        logger.info(f"Sending command: {command}")

        # Track input in session
        input_id = session.add_input(command, "command")
        last_input_id = input_id
        await save_session()

        # Send command
        process.stdin.write(command + '\n')
        process.stdin.flush()

        # Wait for prompt
        if not wait_for_prompt(timeout=session.tool_config.timeout):
            error_msg = f"Timeout waiting for prompt after command: {command}"
            session.add_error("timeout", error_msg, {
                "command": command,
                "timeout": session.tool_config.timeout
            })
            await save_session()
            raise RuntimeError(error_msg)

        await save_session()
        return f"Command executed successfully: {command}"

    except Exception as e:
        logger.error(f"Failed to execute command: {e}")
        session.add_error("command_execution", str(e), {"command": command})
        await save_session()
        raise ValueError(f"Failed to execute command: {e}")


async def output_tool(args: Dict[str, Any]) -> str:
    """Get session output."""
    lines = args.get("lines")

    if lines:
        # Get from session model
        recent_outputs = session.get_recent_outputs(lines)
        return "\n".join([output.text for output in recent_outputs])
    else:
        # Get from file
        output_file = Path(session.output_file)
        if not output_file.exists():
            return "No output available"

        try:
            with open(output_file, 'r') as f:
                return f.read()
        except Exception as e:
            return f"Error reading output: {e}"


async def script_tool(args: Dict[str, Any]) -> str:
    """Execute script in session."""
    global last_input_id

    if not session_active:
        raise ValueError("Session not active")

    script_text = args.get("text")
    command = args.get("command")

    if not script_text or not command:
        raise ValueError("Both 'text' and 'command' are required")

    try:
        # Create temporary script file
        script_file = Path(session.tool_config.working_directory) / f"temp_script_{int(time.time())}.tcl"

        with open(script_file, 'w') as f:
            f.write(script_text)

        # Execute the command
        full_command = command.replace("{script}", str(script_file))

        # Track script in session
        session.add_script(script_text, command, str(script_file), full_command)

        # Track input as script type
        input_id = session.add_input(full_command, "script", str(script_file))
        last_input_id = input_id
        await save_session()

        # Send command
        process.stdin.write(full_command + '\n')
        process.stdin.flush()

        # Wait for prompt
        if not wait_for_prompt(timeout=session.tool_config.timeout):
            error_msg = f"Timeout waiting for prompt after script execution"
            session.add_error("script_timeout", error_msg, {
                "script_content": script_text,
                "command_template": command
            })
            await save_session()
            raise RuntimeError(error_msg)

        # Clean up script file
        try:
            script_file.unlink()
        except:
            pass

        await save_session()
        return f"Script executed successfully"

    except Exception as e:
        logger.error(f"Script execution failed: {e}")
        session.add_error("script_execution", str(e), {
            "script_content": script_text,
            "command_template": command
        })
        await save_session()
        raise ValueError(f"Failed to execute script: {e}")


async def status_tool(args: Dict[str, Any]) -> str:
    """Get session status."""
    status = session.get_session_summary()
    status.update({
        "active": session_active,
        "process_running": process is not None and process.poll() is None,
        "output_file": session.output_file
    })
    return json.dumps(status, indent=2)


async def main():
    """Main entry point."""
    global session, logger

    import argparse

    parser = argparse.ArgumentParser(description="ToolSession MCP Server")
    parser.add_argument("--tool-name", required=True, help="Tool name from config")
    parser.add_argument("--config", default="config.json", help="Path to configuration file")
    parser.add_argument("--port", type=int, default=8002, help="Server port")
    parser.add_argument("--mongo-uri", help="MongoDB URI (or use MONGO_URI env var)")

    args = parser.parse_args()

    # Setup logging
    log_file = f"/tmp/{args.tool_name}_session.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger(f"toolsession.{args.tool_name}")

    # Load configuration
    try:
        with open(args.config, 'r') as f:
            config = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return

    # Get tool configuration
    tool_config_dict = config.get("tools", {}).get(args.tool_name)
    if not tool_config_dict:
        logger.error(f"Tool '{args.tool_name}' not found in config")
        return

    # Create tool config model
    tool_config = ToolConfig(
        name=args.tool_name,
        environment_command=tool_config_dict.get("environment_command"),
        launch_command=tool_config_dict.get("launch_command", "bash"),
        prompt_string=tool_config_dict.get("prompt_string", "$ "),
        working_directory=tool_config_dict.get("working_directory", "/tmp"),
        timeout=tool_config_dict.get("timeout", 300)
    )

    # Create output file path
    output_file = f"/tmp/{args.tool_name}_output.log"

    # Initialize global state
    session = ToolSession(tool_config=tool_config, output_file=output_file)


    logger.info(f"Starting ToolSession MCP Server for {args.tool_name}")
    logger.info(f"Session ID: {session.session_id}")
    logger.info(f"Server running on http://0.0.0.0:{args.port}")

    try:
        config = uvicorn.Config(app, host="0.0.0.0", port=args.port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        raise
    finally:
        if session_active:
            cleanup()
        logger.info("ToolSession MCP Server shutdown")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())