"""MongoDB MCP Server - Database operations for MongoDB."""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import uvicorn
from fastapi import FastAPI, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError, DuplicateKeyError, OperationFailure
from bson import ObjectId, json_util
from bson.errors import InvalidId

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv("../../.env")
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mongo_mcp")

# Global MongoDB connection
client: Optional[AsyncIOMotorClient] = None
database: Optional[AsyncIOMotorDatabase] = None

# Pydantic models for MCP
class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Union[int, str]
    method: str
    params: Optional[Dict[str, Any]] = None

class MCPResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Union[int, str]
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None

class MCPError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None

# Tool parameter models
class FindParams(BaseModel):
    collection: str
    filter: Dict[str, Any] = Field(default_factory=dict)
    projection: Optional[Dict[str, Any]] = None
    sort: Optional[List[List[Union[str, int]]]] = None
    limit: Optional[int] = None
    skip: Optional[int] = None

class InsertOneParams(BaseModel):
    collection: str
    document: Dict[str, Any]

class InsertManyParams(BaseModel):
    collection: str
    documents: List[Dict[str, Any]]
    ordered: bool = True

class UpdateParams(BaseModel):
    collection: str
    filter: Dict[str, Any]
    update: Dict[str, Any]
    upsert: bool = False

class DeleteParams(BaseModel):
    collection: str
    filter: Dict[str, Any]

class AggregateParams(BaseModel):
    collection: str
    pipeline: List[Dict[str, Any]]
    allow_disk_use: bool = False

class CountParams(BaseModel):
    collection: str
    filter: Dict[str, Any] = Field(default_factory=dict)

class IndexParams(BaseModel):
    collection: str
    keys: Dict[str, int]
    unique: bool = False
    name: Optional[str] = None

# FastAPI app
app = FastAPI(
    title="MongoDB MCP Server",
    description="Model Context Protocol server for MongoDB operations",
    version="1.0.0"
)

def serialize_mongo_doc(doc: Any) -> Any:
    """Convert MongoDB document to JSON serializable format."""
    return json.loads(json_util.dumps(doc))

def parse_object_id(value: Any) -> Any:
    """Parse ObjectId strings in filters and documents."""
    if isinstance(value, str):
        # Try to parse as ObjectId if it looks like one
        if len(value) == 24:
            try:
                return ObjectId(value)
            except InvalidId:
                pass
    elif isinstance(value, dict):
        return {k: parse_object_id(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [parse_object_id(item) for item in value]
    return value

async def connect_to_mongo():
    """Connect to MongoDB using environment variables."""
    global client, database

    try:
        # Use MONGO_URI if available
        mongo_uri = os.getenv("MONGO_URI")

        if mongo_uri:
            # Extract database name from URI
            mongo_database = mongo_uri.split('/')[-1].split('?')[0]
        else:
            # Fallback to individual environment variables
            mongo_host = os.getenv("MONGO_HOST", "localhost")
            mongo_port = int(os.getenv("MONGO_PORT", "27017"))
            mongo_user = os.getenv("MONGO_USER")
            mongo_password = os.getenv("MONGO_PASSWORD")
            mongo_database = os.getenv("MONGO_DATABASE", "mongo_mcp")

            # Build connection URI
            if mongo_user and mongo_password:
                mongo_uri = f"mongodb://{mongo_user}:{mongo_password}@{mongo_host}:{mongo_port}/{mongo_database}?authSource=admin"
            else:
                mongo_uri = f"mongodb://{mongo_host}:{mongo_port}/{mongo_database}"

        client = AsyncIOMotorClient(mongo_uri)
        database = client[mongo_database]

        # Test the connection
        await database.command("ping")
        logger.info(f"Successfully connected to MongoDB: {mongo_database}")
        return True

    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        return False

# MCP Tool implementations
async def mongo_find(params: FindParams) -> Dict[str, Any]:
    """Find documents in a collection."""
    try:
        collection = database[params.collection]

        # Parse ObjectIds in filter
        filter_doc = parse_object_id(params.filter)

        # Build query
        cursor = collection.find(filter_doc, params.projection)

        if params.sort:
            cursor = cursor.sort(params.sort)
        if params.skip:
            cursor = cursor.skip(params.skip)
        if params.limit:
            cursor = cursor.limit(params.limit)

        # Execute query
        documents = []
        async for doc in cursor:
            documents.append(serialize_mongo_doc(doc))

        return {
            "collection": params.collection,
            "count": len(documents),
            "documents": documents
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Find operation failed: {str(e)}")

async def mongo_insert_one(params: InsertOneParams) -> Dict[str, Any]:
    """Insert a single document."""
    try:
        collection = database[params.collection]

        # Parse ObjectIds in document
        document = parse_object_id(params.document)

        result = await collection.insert_one(document)

        return {
            "collection": params.collection,
            "inserted_id": str(result.inserted_id),
            "acknowledged": result.acknowledged
        }

    except DuplicateKeyError as e:
        raise HTTPException(status_code=409, detail=f"Duplicate key error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Insert operation failed: {str(e)}")

async def mongo_insert_many(params: InsertManyParams) -> Dict[str, Any]:
    """Insert multiple documents."""
    try:
        collection = database[params.collection]

        # Parse ObjectIds in documents
        documents = [parse_object_id(doc) for doc in params.documents]

        result = await collection.insert_many(documents, ordered=params.ordered)

        return {
            "collection": params.collection,
            "inserted_count": len(result.inserted_ids),
            "inserted_ids": [str(id) for id in result.inserted_ids],
            "acknowledged": result.acknowledged
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Insert many operation failed: {str(e)}")

async def mongo_update_one(params: UpdateParams) -> Dict[str, Any]:
    """Update a single document."""
    try:
        collection = database[params.collection]

        # Parse ObjectIds
        filter_doc = parse_object_id(params.filter)
        update_doc = parse_object_id(params.update)

        result = await collection.update_one(filter_doc, update_doc, upsert=params.upsert)

        return {
            "collection": params.collection,
            "matched_count": result.matched_count,
            "modified_count": result.modified_count,
            "upserted_id": str(result.upserted_id) if result.upserted_id else None,
            "acknowledged": result.acknowledged
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update operation failed: {str(e)}")

async def mongo_update_many(params: UpdateParams) -> Dict[str, Any]:
    """Update multiple documents."""
    try:
        collection = database[params.collection]

        # Parse ObjectIds
        filter_doc = parse_object_id(params.filter)
        update_doc = parse_object_id(params.update)

        result = await collection.update_many(filter_doc, update_doc, upsert=params.upsert)

        return {
            "collection": params.collection,
            "matched_count": result.matched_count,
            "modified_count": result.modified_count,
            "upserted_id": str(result.upserted_id) if result.upserted_id else None,
            "acknowledged": result.acknowledged
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update many operation failed: {str(e)}")

async def mongo_delete_one(params: DeleteParams) -> Dict[str, Any]:
    """Delete a single document."""
    try:
        collection = database[params.collection]

        # Parse ObjectIds in filter
        filter_doc = parse_object_id(params.filter)

        result = await collection.delete_one(filter_doc)

        return {
            "collection": params.collection,
            "deleted_count": result.deleted_count,
            "acknowledged": result.acknowledged
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete operation failed: {str(e)}")

async def mongo_delete_many(params: DeleteParams) -> Dict[str, Any]:
    """Delete multiple documents."""
    try:
        collection = database[params.collection]

        # Parse ObjectIds in filter
        filter_doc = parse_object_id(params.filter)

        result = await collection.delete_many(filter_doc)

        return {
            "collection": params.collection,
            "deleted_count": result.deleted_count,
            "acknowledged": result.acknowledged
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete many operation failed: {str(e)}")

async def mongo_aggregate(params: AggregateParams) -> Dict[str, Any]:
    """Run aggregation pipeline."""
    try:
        collection = database[params.collection]

        # Parse ObjectIds in pipeline
        pipeline = [parse_object_id(stage) for stage in params.pipeline]

        cursor = collection.aggregate(pipeline, allowDiskUse=params.allow_disk_use)

        results = []
        async for doc in cursor:
            results.append(serialize_mongo_doc(doc))

        return {
            "collection": params.collection,
            "count": len(results),
            "results": results
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Aggregation failed: {str(e)}")

async def mongo_count(params: CountParams) -> Dict[str, Any]:
    """Count documents in a collection."""
    try:
        collection = database[params.collection]

        # Parse ObjectIds in filter
        filter_doc = parse_object_id(params.filter)

        count = await collection.count_documents(filter_doc)

        return {
            "collection": params.collection,
            "count": count
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Count operation failed: {str(e)}")

async def mongo_list_collections() -> Dict[str, Any]:
    """List all collections in the database."""
    try:
        collections = await database.list_collection_names()

        return {
            "database": database.name,
            "collections": collections
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"List collections failed: {str(e)}")

async def mongo_create_index(params: IndexParams) -> Dict[str, Any]:
    """Create an index on a collection."""
    try:
        collection = database[params.collection]

        index_name = await collection.create_index(
            list(params.keys.items()),
            unique=params.unique,
            name=params.name
        )

        return {
            "collection": params.collection,
            "index_name": index_name,
            "created": True
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Create index failed: {str(e)}")

# MCP Tools registry
MCP_TOOLS = {
    "mongo_find": {
        "description": "Find documents in a MongoDB collection with optional filtering, sorting, and pagination",
        "parameters": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "description": "Collection name"},
                "filter": {"type": "object", "description": "Query filter (default: {})"},
                "projection": {"type": "object", "description": "Field projection"},
                "sort": {"type": "array", "description": "Sort specification"},
                "limit": {"type": "integer", "description": "Maximum number of documents"},
                "skip": {"type": "integer", "description": "Number of documents to skip"}
            },
            "required": ["collection"]
        },
        "handler": mongo_find,
        "params_class": FindParams
    },
    "mongo_insert_one": {
        "description": "Insert a single document into a MongoDB collection",
        "parameters": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "description": "Collection name"},
                "document": {"type": "object", "description": "Document to insert"}
            },
            "required": ["collection", "document"]
        },
        "handler": mongo_insert_one,
        "params_class": InsertOneParams
    },
    "mongo_insert_many": {
        "description": "Insert multiple documents into a MongoDB collection",
        "parameters": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "description": "Collection name"},
                "documents": {"type": "array", "description": "Array of documents to insert"},
                "ordered": {"type": "boolean", "description": "Ordered insertion (default: true)"}
            },
            "required": ["collection", "documents"]
        },
        "handler": mongo_insert_many,
        "params_class": InsertManyParams
    },
    "mongo_update_one": {
        "description": "Update a single document in a MongoDB collection",
        "parameters": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "description": "Collection name"},
                "filter": {"type": "object", "description": "Query filter"},
                "update": {"type": "object", "description": "Update operations"},
                "upsert": {"type": "boolean", "description": "Create if not exists (default: false)"}
            },
            "required": ["collection", "filter", "update"]
        },
        "handler": mongo_update_one,
        "params_class": UpdateParams
    },
    "mongo_update_many": {
        "description": "Update multiple documents in a MongoDB collection",
        "parameters": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "description": "Collection name"},
                "filter": {"type": "object", "description": "Query filter"},
                "update": {"type": "object", "description": "Update operations"},
                "upsert": {"type": "boolean", "description": "Create if not exists (default: false)"}
            },
            "required": ["collection", "filter", "update"]
        },
        "handler": mongo_update_many,
        "params_class": UpdateParams
    },
    "mongo_delete_one": {
        "description": "Delete a single document from a MongoDB collection",
        "parameters": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "description": "Collection name"},
                "filter": {"type": "object", "description": "Query filter"}
            },
            "required": ["collection", "filter"]
        },
        "handler": mongo_delete_one,
        "params_class": DeleteParams
    },
    "mongo_delete_many": {
        "description": "Delete multiple documents from a MongoDB collection",
        "parameters": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "description": "Collection name"},
                "filter": {"type": "object", "description": "Query filter"}
            },
            "required": ["collection", "filter"]
        },
        "handler": mongo_delete_many,
        "params_class": DeleteParams
    },
    "mongo_aggregate": {
        "description": "Run aggregation pipeline on a MongoDB collection",
        "parameters": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "description": "Collection name"},
                "pipeline": {"type": "array", "description": "Aggregation pipeline stages"},
                "allow_disk_use": {"type": "boolean", "description": "Allow disk usage for large datasets"}
            },
            "required": ["collection", "pipeline"]
        },
        "handler": mongo_aggregate,
        "params_class": AggregateParams
    },
    "mongo_count": {
        "description": "Count documents in a MongoDB collection",
        "parameters": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "description": "Collection name"},
                "filter": {"type": "object", "description": "Query filter (default: {})"}
            },
            "required": ["collection"]
        },
        "handler": mongo_count,
        "params_class": CountParams
    },
    "mongo_list_collections": {
        "description": "List all collections in the MongoDB database",
        "parameters": {
            "type": "object",
            "properties": {}
        },
        "handler": mongo_list_collections,
        "params_class": None
    },
    "mongo_create_index": {
        "description": "Create an index on a MongoDB collection",
        "parameters": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "description": "Collection name"},
                "keys": {"type": "object", "description": "Index keys specification"},
                "unique": {"type": "boolean", "description": "Unique index (default: false)"},
                "name": {"type": "string", "description": "Index name"}
            },
            "required": ["collection", "keys"]
        },
        "handler": mongo_create_index,
        "params_class": IndexParams
    }
}

# MCP Protocol endpoints
@app.post("/mcp")
async def handle_mcp_request(request: MCPRequest) -> MCPResponse:
    """Handle MCP protocol requests."""
    try:
        if request.method == "tools/list":
            # Return available tools
            tools = []
            for name, tool_info in MCP_TOOLS.items():
                tools.append({
                    "name": name,
                    "description": tool_info["description"],
                    "inputSchema": tool_info["parameters"]
                })

            return MCPResponse(
                id=request.id,
                result={"tools": tools}
            )

        elif request.method == "tools/call":
            # Call a specific tool
            if not request.params:
                raise HTTPException(status_code=400, detail="Missing parameters")

            tool_name = request.params.get("name")
            arguments = request.params.get("arguments", {})

            if tool_name not in MCP_TOOLS:
                raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

            tool_info = MCP_TOOLS[tool_name]
            handler = tool_info["handler"]
            params_class = tool_info["params_class"]

            # Parse and validate parameters
            if params_class:
                try:
                    params = params_class(**arguments)
                    result = await handler(params)
                except Exception as e:
                    return MCPResponse(
                        id=request.id,
                        error=MCPError(
                            code=-32603,
                            message=f"Tool execution failed: {str(e)}"
                        ).dict()
                    )
            else:
                result = await handler()

            return MCPResponse(
                id=request.id,
                result={
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2)
                        }
                    ]
                }
            )

        else:
            return MCPResponse(
                id=request.id,
                error=MCPError(
                    code=-32601,
                    message=f"Method '{request.method}' not found"
                ).dict()
            )

    except Exception as e:
        logger.error(f"MCP request failed: {e}")
        return MCPResponse(
            id=request.id,
            error=MCPError(
                code=-32603,
                message=f"Internal error: {str(e)}"
            ).dict()
        )

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        if database is not None:
            await database.command("ping")
            return {
                "status": "healthy",
                "server": "mongo_mcp",
                "version": "1.0.0",
                "database": database.name,
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            return {
                "status": "unhealthy",
                "server": "mongo_mcp",
                "error": "Not connected to MongoDB",
                "timestamp": datetime.utcnow().isoformat()
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "server": "mongo_mcp",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize MongoDB connection on startup."""
    await connect_to_mongo()

# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """Close MongoDB connection on shutdown."""
    if client:
        client.close()
        logger.info("MongoDB connection closed")

if __name__ == "__main__":
    # Get configuration from environment
    host = os.getenv("MONGO_MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MONGO_MCP_PORT", "8004"))

    logger.info(f"Starting MongoDB MCP server on {host}:{port}")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )