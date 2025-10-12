#!/usr/bin/env python3
"""
ToolSession MCP Server - Persistent interactive tool sessions
Lightweight MCP server for managing persistent CLI tool sessions

Usage:
    toolsession [--config config.json]

On startup, copies connection prompt to clipboard for pasting into da_code.
"""

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import tempfile
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from models import ToolSessionConfig

try:
    import pyperclip
    CLIPBOARD_AVAILABLE = True
except ImportError:
    CLIPBOARD_AVAILABLE = False


class MCPRequest(BaseModel):
    """MCP tool call request."""
    arguments: Dict[str, Any] = {}


class ToolSessionOperations:
    """Tool session operations handler."""

    def __init__(self, config: ToolSessionConfig):
        self.config = config
        self.process = None
        self.session_active = False
        self.output_buffer = ""
        self.output_lock = threading.Lock()
        self.prompt_detected = threading.Event()

        # Configuration from config object
        self.working_dir = self.config.session.working_directory
        self.command = self.config.session.command
        self.prompt_string = self.config.session.prompt_string
        self.timeout = self.config.session.timeout

    def get_tools(self):
        """Get available tools."""
        return [
            {
                "name": "execute_command",
                "description": "Execute a command in the persistent session",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Command to execute"}
                    },
                    "required": ["command"],
                    "additionalProperties": False
                }
            },
            {
                "name": "get_output",
                "description": "Get output from the session",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "lines": {"type": "integer", "description": "Number of recent lines (0 = all)"}
                    },
                    "additionalProperties": False
                }
            },
            {
                "name": "execute_script",
                "description": "Execute a script in the session",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "script_content": {"type": "string", "description": "Script content"},
                        "language": {"type": "string", "description": "Script language (python, bash, etc.)"}
                    },
                    "required": ["script_content"],
                    "additionalProperties": False
                }
            },
            {
                "name": "get_status",
                "description": "Get current session status",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False
                }
            },
            {
                "name": "clear_output",
                "description": "Clear the output buffer",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False
                }
            }
        ]

    def monitor_output(self):
        """Monitor process output in a separate thread."""
        try:
            while self.process and self.process.poll() is None and self.session_active:
                if self.process.stdout:
                    char = self.process.stdout.read(1)
                    if not char:
                        break

                    with self.output_lock:
                        self.output_buffer += char

                    # Check for prompt detection
                    if self.output_buffer.endswith(self.prompt_string):
                        self.prompt_detected.set()

        except Exception as e:
            print(f"Output monitoring error: {e}")

    def wait_for_prompt(self, timeout: int = None) -> bool:
        """Wait for the prompt to appear."""
        if timeout is None:
            timeout = self.timeout
        self.prompt_detected.clear()
        return self.prompt_detected.wait(timeout)

    def start_session(self) -> bool:
        """Start the persistent session."""
        if self.session_active and self.process and self.process.poll() is None:
            return True

        try:
            # Ensure working directory exists
            os.makedirs(self.working_dir, exist_ok=True)

            # Start the process with cwd parameter
            self.process = subprocess.Popen(
                self.command,
                shell=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                cwd=self.working_dir
            )

            self.session_active = True
            self.output_buffer = ""

            # Start output monitoring thread
            monitor_thread = threading.Thread(target=self.monitor_output, daemon=True)
            monitor_thread.start()

            # Wait for initial prompt
            if self.wait_for_prompt(30):
                return True
            else:
                self.stop_session()
                print(f"⚠️  Timeout waiting for prompt: '{self.prompt_string}'")
                return False

        except Exception as e:
            self.session_active = False
            print(f"❌ Error starting session: {e}")
            return False

    def stop_session(self):
        """Stop the session."""
        self.session_active = False

        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
            except Exception:
                pass

            self.process = None

    def execute_command(self, command: str) -> str:
        """Execute a command in the persistent session."""
        if not self.session_active or not self.process:
            return "❌ Persistent session not available."

        if self.process.poll() is not None:
            # Try to restart the session
            if not self.start_session():
                return "❌ Session terminated and failed to restart."

        if not command:
            return "❌ Command is required"

        try:
            # Clear previous output buffer content after the last prompt
            with self.output_lock:
                if self.prompt_string in self.output_buffer:
                    last_prompt_idx = self.output_buffer.rfind(self.prompt_string)
                    if last_prompt_idx != -1:
                        self.output_buffer = self.output_buffer[last_prompt_idx + len(self.prompt_string):]

            # Send command
            self.process.stdin.write(command + '\n')
            self.process.stdin.flush()

            # Wait for prompt to return
            if self.wait_for_prompt():
                with self.output_lock:
                    result = self.output_buffer.strip()
                    # Remove the prompt from the end if present
                    if result.endswith(self.prompt_string):
                        result = result[:-len(self.prompt_string)].strip()
                    # Remove the echoed command from the beginning if present
                    if result.startswith(command):
                        result = result[len(command):].strip()

                if result:
                    return f"✅ **Command executed successfully**\n\n**Output:**\n```\n{result}\n```"
                else:
                    return "✅ Command executed successfully (no output)"
            else:
                return f"⏳ Command may still be running (timeout after {self.timeout}s). Use get_output() to check for results."

        except Exception as e:
            return f"❌ Failed to execute command: {e}"

    def get_output(self, lines: int = 0) -> str:
        """Get the current output buffer."""
        if not self.session_active:
            return "❌ No active session"

        with self.output_lock:
            content = self.output_buffer.strip()

            if lines > 0 and content:
                content_lines = content.split('\n')
                content = '\n'.join(content_lines[-lines:])

            if content:
                return f"📋 **Session Output:**\n```\n{content}\n```"
            else:
                return "📋 No output available"

    def execute_script(self, script_content: str, language: str = "python") -> str:
        """Execute a script in the persistent session."""
        if not self.session_active or not self.process:
            return "❌ Persistent session not available."

        if not script_content:
            return "❌ Script content is required"

        try:
            # Create temporary script file
            suffix = {
                "python": ".py",
                "bash": ".sh",
                "javascript": ".js",
                "r": ".r"
            }.get(language.lower(), ".txt")

            with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False) as f:
                f.write(script_content)
                script_path = f.name

            try:
                # Execute script based on language
                if language.lower() == "python":
                    command = f"exec(open('{script_path}').read())"
                elif language.lower() == "bash":
                    command = f"import subprocess; subprocess.run(['bash', '{script_path}'], capture_output=True, text=True)"
                else:
                    return f"❌ Script execution for language '{language}' not implemented"

                result = self.execute_command(command)
                return result

            finally:
                # Clean up script file
                try:
                    os.unlink(script_path)
                except:
                    pass

        except Exception as e:
            return f"❌ Failed to execute script: {e}"

    def get_status(self) -> str:
        """Get current session status."""
        if not self.session_active:
            return "❌ Persistent session not active"

        if self.process:
            if self.process.poll() is None:
                status = f"✅ Persistent session active (PID: {self.process.pid})"
            else:
                status = f"❌ Persistent session process terminated (exit code: {self.process.returncode})"
        else:
            status = "⚠️  Persistent session state unknown"

        return f"{status}\n📁 Working directory: {self.working_dir}\n🔧 Prompt string: {self.prompt_string}\n⚡ Command: {self.command}"

    def clear_output(self) -> str:
        """Clear the output buffer."""
        with self.output_lock:
            self.output_buffer = ""

        return "✅ Output buffer cleared"


class ToolSessionServer:
    """ToolSession MCP server."""

    def __init__(self, config: ToolSessionConfig):
        self.config = config
        self.port = config.server.port
        self.tool_ops = ToolSessionOperations(config)

        self.app = FastAPI(
            title="ToolSession MCP Server",
            description="Persistent interactive tool session management for da_code agents",
            version="1.0.0"
        )

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        self.setup_routes()

    def setup_routes(self):
        """Setup FastAPI routes for MCP JSON-RPC protocol."""

        @self.app.get("/")
        async def root():
            return {
                "name": "ToolSession MCP Server",
                "version": "1.0.0",
                "status": "running",
                "session_active": self.tool_ops.session_active,
                "session_pid": self.tool_ops.process.pid if self.tool_ops.process else None,
                "tools_available": len(self.tool_ops.get_tools()),
                "connection_prompt": self.generate_connection_prompt()
            }

        @self.app.post("/")
        async def handle_jsonrpc(request: dict):
            """Handle MCP JSON-RPC requests."""
            try:
                # Extract JSON-RPC fields
                jsonrpc = request.get("jsonrpc")
                method = request.get("method")
                params = request.get("params", {})
                request_id = request.get("id")

                if jsonrpc != "2.0":
                    return {
                        "jsonrpc": "2.0",
                        "error": {"code": -32600, "message": "Invalid Request"},
                        "id": request_id
                    }

                # Handle tools/list method
                if method == "tools/list":
                    return {
                        "jsonrpc": "2.0",
                        "result": {"tools": self.tool_ops.get_tools()},
                        "id": request_id
                    }

                # Handle tools/call method
                elif method == "tools/call":
                    tool_name = params.get("name")
                    arguments = params.get("arguments", {})

                    if not tool_name:
                        return {
                            "jsonrpc": "2.0",
                            "error": {"code": -32602, "message": "Missing tool name"},
                            "id": request_id
                        }

                    if tool_name not in [t["name"] for t in self.tool_ops.get_tools()]:
                        return {
                            "jsonrpc": "2.0",
                            "error": {"code": -32602, "message": f"Tool '{tool_name}' not found"},
                            "id": request_id
                        }

                    try:
                        # Execute the tool
                        if tool_name == "execute_command":
                            command = arguments.get("command")
                            result = self.tool_ops.execute_command(command)
                        elif tool_name == "get_output":
                            lines = arguments.get("lines", 0)
                            result = self.tool_ops.get_output(lines)
                        elif tool_name == "execute_script":
                            script_content = arguments.get("script_content")
                            language = arguments.get("language", "python")
                            result = self.tool_ops.execute_script(script_content, language)
                        elif tool_name == "get_status":
                            result = self.tool_ops.get_status()
                        elif tool_name == "clear_output":
                            result = self.tool_ops.clear_output()
                        else:
                            return {
                                "jsonrpc": "2.0",
                                "error": {"code": -32602, "message": f"Unknown tool: {tool_name}"},
                                "id": request_id
                            }

                        return {
                            "jsonrpc": "2.0",
                            "result": {"content": [{"type": "text", "text": result}]},
                            "id": request_id
                        }

                    except Exception as e:
                        return {
                            "jsonrpc": "2.0",
                            "error": {"code": -32000, "message": f"Tool execution error: {str(e)}"},
                            "id": request_id
                        }

                else:
                    return {
                        "jsonrpc": "2.0",
                        "error": {"code": -32601, "message": "Method not found"},
                        "id": request_id
                    }

            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": f"Parse error: {str(e)}"},
                    "id": None
                }

        @self.app.get("/mcp/connect")
        async def get_connection_prompt():
            """Get connection prompt for da_code."""
            return {"prompt": self.generate_connection_prompt()}

    def get_local_ip(self) -> str:
        """Get local network IP address."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "localhost"

    def generate_connection_prompt(self) -> str:
        """Generate compact command for da_code agent."""
        ip = self.get_local_ip()
        tool_names = [tool["name"] for tool in self.tool_ops.get_tools()]

        config = {
            "name": "toolsession",
            "url": f"http://{ip}:{self.port}",
            "port": self.port,
            "description": f"ToolSession MCP server - {self.tool_ops.command} at {ip}",
            "tools": tool_names
        }
        return f"add_mcp {json.dumps(config, separators=(',', ':'))}"

    def copy_connection_prompt_to_clipboard(self):
        """Copy complete add_mcp command to clipboard for easy pasting."""
        if not CLIPBOARD_AVAILABLE:
            print("⚠️  pyperclip not available - cannot copy to clipboard")
            command = self.generate_connection_prompt()
            print(f"\n{'='*80}")
            print(f"Connection command (manual copy):\n")
            print(f"   {command}")
            print(f"{'='*80}\n")
            return

        try:
            command = self.generate_connection_prompt()
            pyperclip.copy(command)
            print(f"\n{'='*80}")
            print(f"✅ Connection command copied to clipboard!")
            print(f"{'='*80}")
            print(f"Paste this into your da_code agent:\n")
            print(f"   {command}")
            print(f"{'='*80}\n")
        except Exception as e:
            print(f"⚠️  Could not copy to clipboard: {e}")
            command = self.generate_connection_prompt()
            print(f"\n{'='*80}")
            print(f"Connection command (manual copy):\n")
            print(f"   {command}")
            print(f"{'='*80}\n")

    async def start_server(self):
        """Start the ToolSession MCP server."""
        # Display startup info
        print(f"\n{'='*80}")
        print(f"🔧 ToolSession MCP Server v1.0.0")
        print(f"{'='*80}")
        print(f"📋 Local access: http://localhost:{self.port}")
        print(f"🌐 Network access: http://{self.get_local_ip()}:{self.port}")
        print(f"{'='*80}")

        # Start the persistent session immediately
        print(f"⚡ Starting persistent session: {self.tool_ops.command}")

        if self.tool_ops.start_session():
            print(f"✅ Persistent session started (PID: {self.tool_ops.process.pid})")
            print(f"📁 Working directory: {self.tool_ops.working_dir}")
            print(f"🔧 Tools available: {', '.join([t['name'] for t in self.tool_ops.get_tools()])}")

            # Copy connection command to clipboard
            self.copy_connection_prompt_to_clipboard()

            print(f"⏹️  Press Ctrl+C to stop the server\n")
        else:
            print(f"❌ Failed to start persistent session")
            print(f"{'='*80}\n")
            return

        config = uvicorn.Config(
            self.app,
            host=self.config.server.host,
            port=self.port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()

    def shutdown(self):
        """Shutdown the server."""
        if self.tool_ops.session_active:
            self.tool_ops.stop_session()
            print("\n👋 ToolSession stopped")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="ToolSession MCP Server")
    parser.add_argument("--config", help="Path to configuration file", default="config.json")
    args = parser.parse_args()

    # Load configuration
    config = ToolSessionConfig.load(args.config)

    # Create and run server
    server = ToolSessionServer(config)

    try:
        asyncio.run(server.start_server())
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()