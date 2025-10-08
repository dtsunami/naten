import json
import requests
from typing import Callable
from agno.tools import tool

import logging
logger = logging.getLogger(__name__)


def mcp2tool(server_url: str, tool_name: str = None) -> Callable:
    """Convert MCP server to single Agno tool representing all capabilities.

    Args:
        server_url: MCP server URL (e.g., "https://docs.agno.com/mcp")
        tool_name: Optional custom name for the tool. If None, generates from URL.

    Returns:
        Single Agno tool function that can call any MCP capability
    """
    try:
        logger.info(f"🔌 MCP: Connecting to {server_url}")

        # Get tools list via JSON-RPC
        list_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }

        response = requests.post(
            server_url.rstrip('/'),
            json=list_payload,
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json, text/event-stream',
                'User-Agent': 'da_code-mcp-client/1.0'
            },
            timeout=10
        )

        if response.status_code != 200:
            logger.error(f"❌ MCP: HTTP {response.status_code} from {server_url}")
            logger.error(f"❌ MCP: Response content: {response.text}")
            return None

        try:
            # Handle SSE format response
            response_text = response.text
            if response_text.startswith("event: message\ndata: "):
                # Extract JSON from SSE format
                json_str = response_text.split("data: ", 1)[1].strip()
                data = json.loads(json_str)
            else:
                data = response.json()
        except Exception as e:
            logger.error(f"❌ MCP: Failed to parse response: {e}")
            logger.error(f"❌ MCP: Raw response: {response.text}")
            return None
        if "error" in data:
            logger.error(f"❌ MCP: JSON-RPC error: {data['error']}")
            return None

        if "result" not in data or "tools" not in data["result"]:
            logger.error(f"❌ MCP: Invalid response format: {data}")
            return None

        tools_info = data["result"]["tools"]

        # Log the raw MCP server data for analysis
        logger.info(f"🔍 MCP: Raw server response:")
        logger.info(f"🔍 MCP: Full data: \n\n{json.dumps(data, indent=2)}\n\n")
        logger.info(f"🔍 MCP: Tools array: {json.dumps(tools_info, indent=2)}")

        # Log individual tool details
        for i, tool_info in enumerate(tools_info):
            logger.info(f"🔍 MCP: Tool {i+1} raw data:")
            logger.info(f"🔍 MCP:   name: {tool_info.get('name')}")
            logger.info(f"🔍 MCP:   description: {tool_info.get('description')}")
            logger.info(f"🔍 MCP:   inputSchema: {json.dumps(tool_info.get('inputSchema', {}), indent=2)}")

        # Generate tool name if not provided
        if tool_name is None:
            # Convert URL to safe tool name: https://docs.agno.com/mcp -> docs_agno_com
            from urllib.parse import urlparse
            parsed = urlparse(server_url)
            domain_parts = parsed.netloc.split('.')
            tool_name = '_'.join(domain_parts).replace('-', '_')

        # Build capability descriptions with schemas
        capabilities = []
        for tool_info in tools_info:
            name = tool_info.get('name', None)
            desc = tool_info.get('description', None)
            schema = tool_info.get('inputSchema', {})

            cap_entry = f"- {name}:\n\n  - Description : {desc}\n"
            if schema.get('properties'):
                params = list(schema['properties'].keys())
                required = schema.get('required', [])

                example_info = "  - Example \"{'tool': '" + name + "', 'args': {" #{{"param": "value"}}}}' → calls specific tool"
                for arg in params:
                    if arg in required:
                        example_info += f"'{arg}': '{schema['properties'][arg]['type']}', "
                example_info += '}}"\n'
                cap_entry += example_info.replace(", }}", "}}")

                optional_args = None

                cap_entry += "\n"
            capabilities.append(cap_entry)

        capabilities_text = "".join(capabilities)

        logger.info(f"🔧 MCP: capabilities_text\n\n{capabilities_text}\n\n")

        # Log tool creation details
        logger.info(f"🔧 MCP: Creating tool '{tool_name}' for {server_url}")
        logger.info(f"🔧 MCP: Found {len(tools_info)} capabilities:")
        for i, tool_info in enumerate(tools_info, 1):
            name = tool_info.get('name', 'unknown')
            desc = tool_info.get('description', 'no description')[:100]
            logger.info(f"🔧 MCP:   {i}. {name}: {desc}...")

        # Create single tool representing the MCP server
        @tool(
            name=f"{tool_name}_proxy",
            description=f"Tool proxy with {len(tools_info)} capabilities: {', '.join([t.get('name', 'unknown') for t in tools_info])}",
            instructions=f"""Tool Proxy : {', '.join([t.get('name', 'unknown') for t in tools_info])}
{capabilities_text}

USAGE: 
  **tool_input parameter expects a JSON string**
  - '{{"tool": "ToolName", "args": {{"param": "value"}}}}' → calls specific tool
  - '{{"tool": "ToolName"}}' → calls tool with no parameters

EXAMPLES:
  - '{{"tool": "SearchAgno", "args": {{"query": "agno examples"}}}}'

The tool_input is a JSON string that gets parsed and forwarded to the Tool instance.
Any tool arguments(query, command, search, ...) should be supplied in the args portion of the JSON!
"""
        )
        def mcp_server_tool(tool_input: str, url: str=server_url, capabilities: str=capabilities_text) -> str:
            """Single tool representing all MCP server capabilities."""
            try:
                # Parse input
                if isinstance(tool_input, str):
                    if tool_input.strip().lower() == "list":
                        return f"🔌 Tool proxy : {url}\n\nAvailable capabilities:\n{capabilities}"
                    try:
                        params = json.loads(tool_input)
                    except json.JSONDecodeError:
                        return f"Invalid input. Use JSON format string and any tool arguments in the 'args' json. Available tools:\n{capabilities}"
                else:
                    params = tool_input

                tool_name = params.get("tool")
                tool_args = params.get("args", {})

                if not tool_name:
                    return f"Missing 'tool' parameter. Available tools:\n{capabilities}"

                # Verify tool exists
                if not any(t.get("name") == tool_name for t in tools_info):
                    return f"Tool '{tool_name}' not found. Available tools:\n{capabilities}"

                # Call MCP tool via JSON-RPC
                call_payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": tool_args
                    }
                }

                response = requests.post(
                    server_url.rstrip('/'),
                    json=call_payload,
                    headers={
                        'Content-Type': 'application/json',
                        'Accept': 'application/json, text/event-stream',
                        'User-Agent': 'da_code-mcp-client/1.0'
                    },
                    timeout=30
                )

                if response.status_code == 200:
                    # Handle SSE format response
                    response_text = response.text
                    if response_text.startswith("event: message\ndata: "):
                        json_str = response_text.split("data: ", 1)[1].strip()
                        result_data = json.loads(json_str)
                    else:
                        result_data = response.json()

                    if "result" in result_data:
                        result = result_data["result"]
                        if isinstance(result, (dict, list)):
                            return json.dumps(result, indent=2)
                        else:
                            return str(result)
                    elif "error" in result_data:
                        return f"MCP error: {result_data['error']}"
                    else:
                        return f"Invalid MCP response: {result_data}"
                else:
                    return f"MCP HTTP error {response.status_code}: {response.text}"

            except Exception as e:
                return f"Error calling MCP server: {str(e)}"

        logger.info(f"✅ MCP: Successfully created tool '{tool_name}' with {len(tools_info)} capabilities")
        return mcp_server_tool

    except Exception as e:
        logger.error(f"❌ MCP: Failed to create tool for {server_url}: {e}")
        return None