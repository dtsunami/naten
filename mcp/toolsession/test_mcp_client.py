#!/usr/bin/env python3
"""Test MCP client to interact with the Python ToolSession server."""

import asyncio
import json
import aiohttp
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_client")


async def send_mcp_request(session: aiohttp.ClientSession, url: str, method: str, params: dict = None) -> dict:
    """Send an MCP JSON-RPC request."""
    request_data = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {}
    }

    async with session.post(url, json=request_data) as response:
        if response.status == 200:
            return await response.json()
        else:
            raise Exception(f"HTTP {response.status}: {await response.text()}")


async def test_mcp_server(server_url: str = "http://localhost:8002/mcp"):
    """Test the MCP server with various operations."""

    async with aiohttp.ClientSession() as session:
        try:
            # Initialize MCP connection
            logger.info("🔌 Initializing MCP connection...")
            init_response = await send_mcp_request(session, server_url, "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"}
            })
            logger.info(f"✅ Initialized: {init_response.get('result', {}).get('serverInfo', {})}")

            # List available tools
            logger.info("📋 Listing available tools...")
            tools_response = await send_mcp_request(session, server_url, "tools/list")
            tools = tools_response.get("result", {}).get("tools", [])
            logger.info(f"✅ Available tools: {[tool['name'] for tool in tools]}")

            # Test basic Python commands
            logger.info("🐍 Testing Python commands...")

            # Test simple print command
            logger.info("   Executing: print('Hello from MCP!')")
            cmd_response = await send_mcp_request(session, server_url, "tools/call", {
                "name": "input",
                "arguments": {"command": "print('Hello from MCP!')"}
            })
            logger.info(f"   Result: {cmd_response.get('result', {})}")

            # Test math operation
            logger.info("   Executing: 2 + 2")
            cmd_response = await send_mcp_request(session, server_url, "tools/call", {
                "name": "input",
                "arguments": {"command": "2 + 2"}
            })
            logger.info(f"   Result: {cmd_response.get('result', {})}")

            # Test import and usage
            logger.info("   Executing: import math")
            await send_mcp_request(session, server_url, "tools/call", {
                "name": "input",
                "arguments": {"command": "import math"}
            })

            logger.info("   Executing: math.sqrt(16)")
            cmd_response = await send_mcp_request(session, server_url, "tools/call", {
                "name": "input",
                "arguments": {"command": "math.sqrt(16)"}
            })
            logger.info(f"   Result: {cmd_response.get('result', {})}")

            # Test script execution
            logger.info("📜 Testing script execution...")
            script_content = """
# Test script for calculating fibonacci numbers
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)

# Calculate first 10 fibonacci numbers
fib_numbers = [fibonacci(i) for i in range(10)]
print(f"First 10 Fibonacci numbers: {fib_numbers}")
"""

            script_response = await send_mcp_request(session, server_url, "tools/call", {
                "name": "script",
                "arguments": {
                    "text": script_content,
                    "command": "exec(open('{script}').read())"
                }
            })
            logger.info(f"   Script result: {script_response.get('result', {})}")

            # Get session output
            logger.info("📄 Getting session output...")
            output_response = await send_mcp_request(session, server_url, "tools/call", {
                "name": "output",
                "arguments": {"lines": 20}
            })
            output_content = output_response.get('result', {}).get('content', [{}])[0].get('text', '')
            logger.info(f"   Recent output:\n{output_content}")

            # Get session status
            logger.info("📊 Getting session status...")
            status_response = await send_mcp_request(session, server_url, "tools/call", {
                "name": "status",
                "arguments": {}
            })
            status_content = status_response.get('result', {}).get('content', [{}])[0].get('text', '')
            logger.info(f"   Session status:\n{status_content}")

            logger.info("✅ All tests completed successfully!")

        except Exception as e:
            logger.error(f"❌ Test failed: {e}", exc_info=True)


async def test_health_endpoint(server_url: str = "http://localhost:8002/health"):
    """Test the health endpoint."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(server_url) as response:
                if response.status == 200:
                    health_data = await response.json()
                    logger.info(f"🏥 Health check: {health_data}")
                    return health_data
                else:
                    logger.error(f"Health check failed: HTTP {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Health check error: {e}")
            return None


async def main():
    """Main test function."""
    import argparse

    parser = argparse.ArgumentParser(description="Test MCP ToolSession Server")
    parser.add_argument("--port", type=int, default=8002, help="Server port")
    parser.add_argument("--host", default="localhost", help="Server host")

    args = parser.parse_args()

    server_base = f"http://{args.host}:{args.port}"

    logger.info(f"🧪 Testing MCP ToolSession server at {server_base}")

    # Test health endpoint first
    health_data = await test_health_endpoint(f"{server_base}/health")
    if not health_data:
        logger.error("❌ Server health check failed. Is the server running?")
        return

    # Test MCP functionality
    await test_mcp_server(f"{server_base}/mcp")


if __name__ == "__main__":
    # Install aiohttp if not available
    try:
        import aiohttp
    except ImportError:
        logger.error("aiohttp not installed. Install with: pip install aiohttp")
        exit(1)

    asyncio.run(main())