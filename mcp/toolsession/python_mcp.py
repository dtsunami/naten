#!/usr/bin/env python3
"""Launch a Python kernel ToolSession MCP server."""

import os
import sys
import asyncio
import logging
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from tools import ToolSession, ToolConfig
from ts_mongo import mongo_connect, tool_mongo, upsert_config, upsert_session

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/tmp/python_toolsession.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("python_toolsession")


async def setup_python_session():
    """Setup and initialize Python tool session in database."""

    try:
        # Connect to MongoDB
        logger.info("Connecting to MongoDB...")
        connected = await mongo_connect()
        if not connected:
            raise RuntimeError("Failed to connect to MongoDB")

        # Create Python tool configuration
        logger.info("Setting up Python tool configuration...")
        python_config = ToolConfig(
            name="python",
            launch_command="python -i -u",  # -u for unbuffered output
            prompt_string=">>> ",
            working_directory=".",
            timeout=int(os.getenv("TOOLSESSION_TIMEOUT", "120"))
        )

        # Save config to database
        logger.info("Saving tool config to database...")
        await upsert_config(python_config)

        # Create tool session
        logger.info("Creating Python tool session...")
        output_file = "/tmp/python_session_output.log"

        session = ToolSession(
            tool_config=python_config,
            output_file=output_file
        )

        # Save initial session to database
        logger.info("Saving initial session to database...")
        await upsert_session(session)

        logger.info(f"Python session initialized: {session.session_id}")
        return session, python_config

    except Exception as e:
        logger.error(f"Setup failed: {e}")
        raise


async def launch_mcp_server(tool_config: ToolConfig, port: int = 8002):
    """Launch the MCP server with the Python tool configuration."""

    # Import the server module
    from server import main as server_main

    # Set up arguments for the server
    sys.argv = [
        "server.py",
        "--tool-name", tool_config.name,
        "--port", str(port)
    ]

    # Create a simple config file for the server
    config_data = {
        "tools": {
            tool_config.name: {
                "launch_command": tool_config.launch_command,
                "prompt_string": tool_config.prompt_string,
                "working_directory": tool_config.working_directory,
                "timeout": tool_config.timeout
            }
        }
    }

    config_file = Path("python_config.json")
    with open(config_file, 'w') as f:
        import json
        json.dump(config_data, f, indent=2)

    # Update sys.argv to use our config file
    sys.argv.extend(["--config", str(config_file)])

    logger.info(f"Launching MCP server on port {port}...")
    logger.info(f"Config: {config_data}")

    # Launch the server
    try:
        await server_main()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Launch Python ToolSession MCP Server")
    parser.add_argument("--port", type=int, default=8002, help="Server port")
    parser.add_argument("--setup-only", action="store_true", help="Only setup session, don't launch server")

    args = parser.parse_args()

    logger.info("Setting up Python ToolSession...")

    # Setup session in database
    session, tool_config = await setup_python_session()

    logger.info(f"✅ Python session setup complete!")
    logger.info(f"   Session ID: {session.session_id}")
    logger.info(f"   Tool: {tool_config.name}")
    logger.info(f"   Command: {tool_config.launch_command}")
    logger.info(f"   Working Dir: {tool_config.working_directory}")
    logger.info(f"   Prompt: '{tool_config.prompt_string}'")

    if args.setup_only:
        logger.info("Setup complete. Use --setup-only=false to launch server.")
        return

    logger.info(f"🚀 Launching MCP server on port {args.port}...")
    logger.info(f"   Server will be available at: http://localhost:{args.port}")
    logger.info(f"   Health check: http://localhost:{args.port}/health")
    logger.info(f"   MCP endpoint: http://localhost:{args.port}/mcp")

    # Launch the MCP server
    await launch_mcp_server(tool_config, args.port)


if __name__ == "__main__":
    asyncio.run(main())