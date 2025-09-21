"""MCP JSON-RPC Server implementation for FileIO operations."""

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import uvicorn
from bson import ObjectId
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, ConfigDict, Field, field_serializer

from config import FileIOConfig
from directory_ops import DirectoryOperations
from file_ops import FileOperations


# MCP Protocol Models
@dataclass
class MCPRequest:
    jsonrpc: str
    id: Union[str, int, None]
    method: str
    params: Optional[Dict[str, Any]] = None


@dataclass
class MCPResponse:
    jsonrpc: str
    id: Union[str, int, None]
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


@dataclass
class MCPError:
    code: int
    message: str
    data: Optional[Dict[str, Any]] = None


# MongoDB Models for logging
class PyObjectId(ObjectId):
    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        from pydantic_core import core_schema

        return core_schema.no_info_plain_validator_function(cls.validate)

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if isinstance(v, str) and ObjectId.is_valid(v):
            return ObjectId(v)
        raise ValueError("Invalid ObjectId")


class MCPExecution(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    method: str
    params: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    execution_time: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    client_info: Optional[Dict[str, Any]] = None

    @field_serializer("id")
    def serialize_object_id(self, value: Optional[PyObjectId]) -> Optional[str]:
        """Serialize ObjectId to string for JSON output."""
        if value is None:
            return None
        return str(value)


class MCPFileIOServer:
    """MCP JSON-RPC Server for FileIO operations."""

    def __init__(self, config_path: str = "config.json"):
        self.config = FileIOConfig.load(config_path)
        self.logger = None
        self.mongodb_client = None
        self.database = None
        self.file_ops = None
        self.dir_ops = None
        self.initialized = False
        self.client_capabilities = {}

        # MCP Protocol version
        self.protocol_version = "2024-11-05"

        # Setup FastAPI app
        self.app = FastAPI(
            title="FileIO MCP Server",
            description="MCP JSON-RPC server for file operations",
            version="1.0.0",
        )

        # Add CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Setup routes
        self.setup_routes()

        # Setup components
        self.setup_logging()
        self.setup_operations()

    def setup_logging(self):
        """Setup logging configuration."""
        log_path = Path(self.config.logging.file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        logging.basicConfig(
            level=getattr(logging, self.config.logging.level),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(self.config.logging.file),
                logging.StreamHandler(),
            ],
        )
        self.logger = logging.getLogger("fileio-mcp")

    def setup_operations(self):
        """Setup file and directory operations."""
        self.file_ops = FileOperations(self.config)
        self.dir_ops = DirectoryOperations(self.config)

    def setup_routes(self):
        """Setup FastAPI routes."""

        @self.app.on_event("startup")
        async def startup_event():
            """Initialize MongoDB connection on startup."""
            await self.connect_mongodb()

        @self.app.on_event("shutdown")
        async def shutdown_event():
            """Close MongoDB connection on shutdown."""
            if self.mongodb_client:
                self.mongodb_client.close()

        @self.app.post("/mcp")
        async def mcp_endpoint(request: Request):
            """Main MCP JSON-RPC endpoint."""
            try:
                body = await request.json()
                response = await self.handle_mcp_request(body)
                return JSONResponse(content=response)
            except json.JSONDecodeError:
                return self.create_error_response(None, -32700, "Parse error")
            except Exception as e:
                self.logger.error(f"Unexpected error: {e}", exc_info=True)
                return self.create_error_response(None, -32603, "Internal error")

        @self.app.get("/health")
        async def health_check():
            """Health check endpoint."""
            return {
                "status": "healthy",
                "protocol_version": self.protocol_version,
                "initialized": self.initialized,
                "mongodb_connected": self.database is not None,
                "base_path_exists": self.config.base_path.exists(),
                "allowed_directories": [
                    {"name": d, "exists": (self.config.base_path / d).exists()}
                    for d in self.config.allowed_directories
                ],
            }

    async def connect_mongodb(self):
        """Connect to MongoDB."""
        try:
            mongo_url = os.getenv("MONGO_URI")
            if mongo_url is None:
                raise ValueError("MONGO_URI environment variable not set")

            self.mongodb_client = AsyncIOMotorClient(mongo_url)
            self.database = self.mongodb_client.orenco_pydantic

            # Test the connection
            await self.database.command("ping")
            self.logger.info("Successfully connected to MongoDB")
            return True
        except Exception as e:
            self.logger.error(f"Failed to connect to MongoDB: {e}")
            return False

    async def log_execution(
        self,
        method: str,
        params: Dict[str, Any],
        result: Dict[str, Any] = None,
        error: Dict[str, Any] = None,
        execution_time: float = 0.0,
        client_info: Dict[str, Any] = None,
    ):
        """Log MCP execution to MongoDB."""
        if self.database is None:
            return

        try:
            execution = MCPExecution(
                method=method,
                params=params,
                result=result,
                error=error,
                execution_time=execution_time,
                client_info=client_info,
            )

            await self.database.mcp_executions.insert_one(execution.dict(by_alias=True))
        except Exception as e:
            self.logger.error(f"Failed to log execution: {e}")

    def create_response(
        self, request_id: Union[str, int, None], result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a successful MCP response."""
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def create_error_response(
        self,
        request_id: Union[str, int, None],
        code: int,
        message: str,
        data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """Create an MCP error response."""
        error = {"code": code, "message": message}
        if data:
            error["data"] = data

        return {"jsonrpc": "2.0", "id": request_id, "error": error}

    async def handle_mcp_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle incoming MCP JSON-RPC request."""
        import time

        start_time = time.time()

        # Validate JSON-RPC structure
        if not isinstance(request_data, dict):
            return self.create_error_response(None, -32600, "Invalid Request")

        jsonrpc = request_data.get("jsonrpc")
        if jsonrpc != "2.0":
            return self.create_error_response(None, -32600, "Invalid JSON-RPC version")

        request_id = request_data.get("id")
        method = request_data.get("method")
        params = request_data.get("params", {})

        if not method:
            return self.create_error_response(request_id, -32600, "Missing method")

        self.logger.info(f"MCP request: {method} with params: {params}")

        try:
            # Route to appropriate handler
            if method == "initialize":
                result = await self.handle_initialize(params)
            elif method == "tools/list":
                result = await self.handle_tools_list(params)
            elif method == "tools/call":
                result = await self.handle_tools_call(params)
            else:
                return self.create_error_response(
                    request_id, -32601, f"Method not found: {method}"
                )

            execution_time = time.time() - start_time

            # Log successful execution
            await self.log_execution(method, params, result, None, execution_time)

            return self.create_response(request_id, result)

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = str(e)
            self.logger.error(f"Error handling {method}: {error_msg}", exc_info=True)

            # Log failed execution
            error_data = {"code": -32603, "message": error_msg}
            await self.log_execution(method, params, None, error_data, execution_time)

            return self.create_error_response(request_id, -32603, error_msg)

    async def handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP initialize request."""
        protocol_version = params.get("protocolVersion", "2024-11-05")
        client_capabilities = params.get("capabilities", {})
        client_info = params.get("clientInfo", {})

        # Store client info
        self.client_capabilities = client_capabilities

        # Mark as initialized
        self.initialized = True

        self.logger.info(f"Initialized MCP server for client: {client_info}")

        return {
            "protocolVersion": self.protocol_version,
            "capabilities": {"tools": {"listChanged": True}, "logging": {}},
            "serverInfo": {"name": "fileio-mcp", "version": "1.0.0"},
        }

    async def handle_tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/list request."""
        tools = []

        # Get tools from file operations
        for tool in self.file_ops.get_tools():
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema,
                }
            )

        # Get tools from directory operations
        for tool in self.dir_ops.get_tools():
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema,
                }
            )

        return {"tools": tools}

    async def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            raise ValueError("Tool name is required")

        self.logger.info(f"Executing tool: {tool_name} with args: {arguments}")

        # Route to appropriate handler
        file_tool_names = [tool.name for tool in self.file_ops.get_tools()]
        dir_tool_names = [tool.name for tool in self.dir_ops.get_tools()]

        if tool_name in file_tool_names:
            result = await self.file_ops.execute(tool_name, arguments)
        elif tool_name in dir_tool_names:
            result = await self.dir_ops.execute(tool_name, arguments)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

        # Convert MCP TextContent to proper format
        content = []
        for item in result:
            content.append({"type": item.type, "text": item.text})

        return {"content": content, "isError": False}

    def run(self):
        """Run the MCP server."""
        self.logger.info(f"Starting FileIO MCP Server v1.0.0")
        self.logger.info(f"Protocol version: {self.protocol_version}")
        self.logger.info(f"Monitoring directories: {self.config.allowed_directories}")
        self.logger.info(f"Base path: {self.config.base_path}")

        try:
            self.logger.info(
                f"MCP Server running on http://{self.config.server.host}:{self.config.server.port}"
            )
            self.logger.info(
                f"MCP endpoint: http://{self.config.server.host}:{self.config.server.port}/mcp"
            )

            # Run the FastAPI server
            uvicorn.run(
                self.app,
                host=self.config.server.host,
                port=self.config.server.port,
                log_level="info",
            )
        except KeyboardInterrupt:
            self.logger.info("Server stopped by user")
        except Exception as e:
            self.logger.error(f"Server error: {e}", exc_info=True)
            raise
        finally:
            self.logger.info("FileIO MCP Server shutdown")


def main():
    """Main entry point for the MCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="FileIO MCP JSON-RPC Server")
    parser.add_argument(
        "--config", default="config.json", help="Path to configuration file"
    )

    args = parser.parse_args()

    # Run the server
    server = MCPFileIOServer(args.config)
    server.run()


if __name__ == "__main__":
    main()
