"""Rancher-like Services Health Dashboard - FastAPI app with Docker integration."""

import asyncio
import httpx
import docker
import psycopg2
import redis
from pymongo import MongoClient
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
import os

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

app = FastAPI(title="Orenco", version="1.0.0")

# Setup templates and static files
templates = Jinja2Templates(directory="templates")

try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except:
    # Create static directory if it doesn't exist
    from pathlib import Path
    Path("static").mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Initialize Docker client
try:
    docker_client = docker.from_env()
except Exception as e:
    print(f"Warning: Could not connect to Docker: {e}")
    docker_client = None

# Service configuration with container mapping
SERVICES = {
    "n8ngui": {
        "name": "n8n GUI",
        "container_name": "n8ngui",
        "health_url": "http://n8ngui:5678/healthz",
        "external_url": f"http://localhost:{os.getenv('N8N_PORT', '5678')}",
        "type": "webapp",
        "description": "n8n workflow automation GUI"
    },
    "n8nwork": {
        "name": "n8n Worker",
        "container_name": "n8nwork",
        "health_url": None,
        "type": "worker",
        "description": "n8n workflow execution worker"
    },
    "fileio_mcp": {
        "name": "FileIO MCP",
        "container_name": "fileio_mcp",
        "health_url": "http://fileio_mcp:8000/health",
        "external_url": f"http://localhost:{os.getenv('FILEIO_PORT', '3456')}",
        "type": "mcp",
        "description": "File operations MCP server"
    },
    "python_mcp": {
        "name": "Python MCP",
        "container_name": "python_mcp",
        "health_url": "http://python_mcp:8002/health",
        "external_url": f"http://localhost:{os.getenv('TOOLSESSION_PORT', '8002')}",
        "type": "mcp",
        "description": "Interactive Python tool sessions MCP server"
    },
    "search_mcp": {
        "name": "Search MCP",
        "container_name": "search_mcp",
        "health_url": "http://search_mcp:8003/health",
        "external_url": f"http://localhost:{os.getenv('SEARCH_PORT', '8003')}",
        "type": "mcp",
        "description": "Web search and content extraction MCP server"
    },
    "mongo_mcp": {
        "name": "MongoDB MCP",
        "container_name": "mongo_mcp",
        "health_url": "http://mongo_mcp:8004/health",
        "external_url": f"http://localhost:{os.getenv('MONGO_MCP_PORT', '8004')}",
        "type": "mcp",
        "description": "MongoDB database operations MCP server"
    },
    "mcp_gateway": {
        "name": "MCP Gateway",
        "container_name": "mcp_gateway",
        "health_url": "http://mcp_gateway:80",
        "external_url": f"http://localhost:{os.getenv('GATEWAY_PORT', '8080')}",
        "type": "proxy",
        "description": "MCP services proxy"
    },
    "pgn8n": {
        "name": "PostgreSQL Main",
        "container_name": "pgn8n",
        "health_url": None,
        "type": "database",
        "description": "Main PostgreSQL database",
        "db_check": {
            "host": "pgn8n",
            "port": 5432,
            "database": os.getenv("DB_POSTGRESDB_DATABASE", "orenco_workflows"),
            "user": os.getenv("DB_POSTGRESDB_USER", "lostboy"),
            "password": os.getenv("DB_POSTGRESDB_PASSWORD", "")
        }
    },
    "pgvect": {
        "name": "PostgreSQL Vector",
        "container_name": "pgvect",
        "health_url": None,
        "type": "database",
        "description": "Vector database with pgvector",
        "db_check": {
            "host": "pgvect",
            "port": 5432,
            "database": os.getenv("VECTOR_DB_DATABASE", "orenco_vectors"),
            "user": os.getenv("VECTOR_DB_USER", "lostboy"),
            "password": os.getenv("VECTOR_DB_PASSWORD", "")
        }
    },
    "pgchat": {
        "name": "PostgreSQL Chat",
        "container_name": "pgchat",
        "health_url": None,
        "type": "database",
        "description": "Chat memory database",
        "db_check": {
            "host": "pgchat",
            "port": 5432,
            "database": os.getenv("CHAT_DB_DATABASE", "orenco_chatmemory"),
            "user": os.getenv("CHAT_DB_USER", "lostboy"),
            "password": os.getenv("CHAT_DB_PASSWORD", "")
        }
    },
    "redisn8n": {
        "name": "Redis Queue",
        "container_name": "redisn8n",
        "health_url": None,
        "type": "cache",
        "description": "Redis message queue",
        "redis_check": {
            "host": "redisn8n",
            "port": 6379
        }
    },
    "mongo": {
        "name": "MongoDB",
        "container_name": "mongo",
        "health_url": None,
        "type": "database",
        "description": "MongoDB document store",
        "mongo_check": {
            "host": "mongo",
            "port": 27017,
            "username": os.getenv("MONGO_USER", "lostboy"),
            "password": os.getenv("MONGO_PASSWORD", ""),
            "database": os.getenv("MONGO_DATABASE", "orenco_pydantic")
        }
    },
    # Dashboard should not check itself - removed to avoid circular health checks
}


def get_docker_hub_url(image: str) -> Optional[str]:
    """Generate Docker Hub URL for official images."""
    if not image or image == "unknown":
        return None

    # List of known local/custom images to skip
    local_images = {"fileio", "toolsession", "dashboard"}

    if ":" in image:
        image_name, tag = image.split(":", 1)

        # Skip known local images
        if image_name in local_images:
            return None

        if "/" not in image_name:
            # Official Docker images like "postgres:15", "redis:7-alpine", "mongo:7"
            return f"https://hub.docker.com/_/{image_name}"
        elif image_name.count("/") == 1 and not image_name.startswith("localhost"):
            # Organization images like "n8nio/n8n", "pgvector/pgvector"
            return f"https://hub.docker.com/r/{image_name}"

    return None


def get_container_info(container_name: str) -> Dict[str, Any]:
    """Get Docker container information."""
    container_info = {
        "state": "unknown",
        "status": "unknown",
        "uptime": "unknown",
        "image": "unknown",
        "created": "unknown"
    }

    if not docker_client:
        return container_info

    try:
        container = docker_client.containers.get(container_name)

        container_info["state"] = container.status
        container_info["status"] = container.attrs.get('State', {}).get('Status', 'unknown')

        # Calculate uptime
        if container.attrs.get('State', {}).get('StartedAt'):
            started_at = datetime.fromisoformat(
                container.attrs['State']['StartedAt'].replace('Z', '+00:00')
            )
            uptime = datetime.now(timezone.utc) - started_at
            container_info["uptime"] = format_uptime(uptime)

        # Get image info
        image_info = container.image
        container_info["image"] = f"{image_info.tags[0] if image_info.tags else 'unknown'}"

        # Created time
        if container.attrs.get('Created'):
            created = datetime.fromisoformat(
                container.attrs['Created'].replace('Z', '+00:00')
            )
            container_info["created"] = created.strftime('%Y-%m-%d %H:%M:%S')

    except Exception as e:
        container_info["error"] = str(e)

    return container_info


def format_uptime(uptime: timedelta) -> str:
    """Format uptime duration."""
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


async def check_postgres_db(db_config: Dict[str, Any]) -> Dict[str, Any]:
    """Check PostgreSQL database connectivity."""
    try:
        conn = psycopg2.connect(
            host=db_config["host"],
            port=db_config["port"],
            database=db_config["database"],
            user=db_config["user"],
            password=db_config["password"],
            connect_timeout=5
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT version()")
            version = cursor.fetchone()[0]
        conn.close()
        return {"status": "healthy", "version": version.split()[1]}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


async def check_redis(redis_config: Dict[str, Any]) -> Dict[str, Any]:
    """Check Redis connectivity."""
    try:
        r = redis.Redis(
            host=redis_config["host"],
            port=redis_config["port"],
            socket_connect_timeout=5
        )
        info = r.info()
        return {
            "status": "healthy",
            "version": info.get("redis_version"),
            "uptime": f"{info.get('uptime_in_seconds', 0) // 86400}d"
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


async def check_mongodb(mongo_config: Dict[str, Any]) -> Dict[str, Any]:
    """Check MongoDB connectivity."""
    try:
        client = MongoClient(
            host=mongo_config["host"],
            port=mongo_config["port"],
            username=mongo_config["username"],
            password=mongo_config["password"],
            authSource="admin",
            serverSelectionTimeoutMS=5000
        )
        info = client.admin.command("serverStatus")
        client.close()
        return {
            "status": "healthy",
            "version": info.get("version"),
            "uptime": f"{info.get('uptime', 0) // 86400}d"
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


async def check_http_service(service_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Check HTTP-based service health."""
    http_status = {"status": "unknown", "response_time": None}

    if config.get("health_url"):
        try:
            start_time = datetime.now()
            timeout = httpx.Timeout(5.0)

            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(config["health_url"], follow_redirects=True)

                end_time = datetime.now()
                http_status["response_time"] = int((end_time - start_time).total_seconds() * 1000)

                if response.status_code == 200:
                    http_status["status"] = "healthy"
                elif response.status_code < 500:
                    http_status["status"] = "degraded"
                    http_status["error"] = f"HTTP {response.status_code}"
                else:
                    http_status["status"] = "unhealthy"
                    http_status["error"] = f"HTTP {response.status_code}"

        except Exception as e:
            http_status["status"] = "unhealthy"
            http_status["error"] = str(e)

    return http_status


async def check_service(service_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Check individual service health with Docker info."""
    result = {
        "id": service_id,
        "name": config["name"],
        "type": config["type"],
        "description": config["description"],
        "status": "unknown",
        "response_time": None,
        "external_url": config.get("external_url"),
        "last_checked": datetime.now(timezone.utc).isoformat()
    }

    # Get Docker container info
    container_info = get_container_info(config["container_name"])
    result.update(container_info)

    # Add Docker Hub URL if applicable
    image = container_info.get("image")
    docker_url = get_docker_hub_url(image)

    # Test: Force some known URLs for testing
    if image == "n8nio/n8n:latest":
        docker_url = "https://hub.docker.com/r/n8nio/n8n"
    elif image == "postgres:15":
        docker_url = "https://hub.docker.com/_/postgres"
    elif image == "redis:7-alpine":
        docker_url = "https://hub.docker.com/_/redis"

    result["docker_hub_url"] = docker_url

    # Determine overall health based on container state
    if container_info["state"] == "running":
        # Check service-specific health
        if config.get("db_check"):
            db_result = await check_postgres_db(config["db_check"])
            result["db_status"] = db_result["status"]
            if db_result["status"] == "healthy":
                result["status"] = "healthy"
                result["db_version"] = db_result.get("version")
            else:
                result["status"] = "unhealthy"
                result["error"] = db_result.get("error")
        elif config.get("redis_check"):
            redis_result = await check_redis(config["redis_check"])
            result["redis_status"] = redis_result["status"]
            if redis_result["status"] == "healthy":
                result["status"] = "healthy"
                result["redis_version"] = redis_result.get("version")
            else:
                result["status"] = "unhealthy"
                result["error"] = redis_result.get("error")
        elif config.get("mongo_check"):
            mongo_result = await check_mongodb(config["mongo_check"])
            result["mongo_status"] = mongo_result["status"]
            if mongo_result["status"] == "healthy":
                result["status"] = "healthy"
                result["mongo_version"] = mongo_result.get("version")
            else:
                result["status"] = "unhealthy"
                result["error"] = mongo_result.get("error")
        elif config.get("health_url"):
            http_result = await check_http_service(service_id, config)
            result["status"] = http_result["status"]
            result["response_time"] = http_result["response_time"]
            if "error" in http_result:
                result["error"] = http_result["error"]
        else:
            # No specific health check, assume healthy if running
            result["status"] = "healthy"
    else:
        result["status"] = "unhealthy"
        result["error"] = f"Container not running: {container_info['state']}"

    return result


async def check_all_services() -> List[Dict[str, Any]]:
    """Check health of all services."""
    tasks = []

    for service_id, config in SERVICES.items():
        task = check_service(service_id, config)
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Handle any exceptions
    final_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            service_id = list(SERVICES.keys())[i]
            config = SERVICES[service_id]
            final_results.append({
                "id": service_id,
                "name": config["name"],
                "type": config["type"],
                "description": config["description"],
                "status": "error",
                "error": str(result),
                "last_checked": datetime.now(timezone.utc).isoformat()
            })
        else:
            final_results.append(result)

    return final_results


def get_container_logs(container_name: str, lines: int = 50) -> str:
    """Get recent container logs."""
    if not docker_client:
        return "Docker client not available"

    try:
        container = docker_client.containers.get(container_name)
        logs = container.logs(tail=lines, timestamps=True).decode('utf-8')
        return logs
    except Exception as e:
        return f"Error getting logs: {str(e)}"


def restart_container(container_name: str) -> Dict[str, Any]:
    """Restart a Docker container."""
    if not docker_client:
        return {"success": False, "error": "Docker client not available"}

    try:
        container = docker_client.containers.get(container_name)
        container.restart()
        return {"success": True, "message": f"Container {container_name} restarted successfully"}
    except Exception as e:
        return {"success": False, "error": f"Error restarting container: {str(e)}"}


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Rancher-like dashboard page."""
    services = await check_all_services()

    # Calculate overall health
    total_services = len(services)
    healthy_services = sum(1 for s in services if s["status"] == "healthy")
    degraded_services = sum(1 for s in services if s["status"] == "degraded")
    unhealthy_services = total_services - healthy_services - degraded_services

    overall_status = "healthy"
    if unhealthy_services > 0:
        overall_status = "unhealthy"
    elif degraded_services > 0:
        overall_status = "degraded"

    context = {
        "request": request,
        "services": services,
        "total_services": total_services,
        "healthy_services": healthy_services,
        "degraded_services": degraded_services,
        "unhealthy_services": unhealthy_services,
        "overall_status": overall_status,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "page_title": "Orenco"
    }

    return templates.TemplateResponse("rancher_dashboard.html", context)


@app.get("/api/health")
async def api_health():
    """API endpoint for health data."""
    services = await check_all_services()

    total_services = len(services)
    healthy_services = sum(1 for s in services if s["status"] == "healthy")
    degraded_services = sum(1 for s in services if s["status"] == "degraded")
    unhealthy_services = total_services - healthy_services - degraded_services

    overall_status = "healthy"
    if unhealthy_services > 0:
        overall_status = "unhealthy"
    elif degraded_services > 0:
        overall_status = "degraded"

    return {
        "overall_status": overall_status,
        "summary": {
            "total": total_services,
            "healthy": healthy_services,
            "degraded": degraded_services,
            "unhealthy": unhealthy_services
        },
        "services": services,
        "last_updated": datetime.now(timezone.utc).isoformat()
    }


@app.get("/api/services/{service_id}")
async def api_service_detail(service_id: str):
    """Get detailed information about a specific service."""
    if service_id not in SERVICES:
        return JSONResponse({"error": "Service not found"}, status_code=404)

    config = SERVICES[service_id]
    result = await check_service(service_id, config)
    return result


@app.get("/api/logs/{service_id}")
async def api_service_logs(service_id: str, lines: int = Query(50, ge=1, le=1000)):
    """Get recent logs for a service."""
    if service_id not in SERVICES:
        return JSONResponse({"error": "Service not found"}, status_code=404)

    config = SERVICES[service_id]
    logs = get_container_logs(config["container_name"], lines)

    return {
        "service_id": service_id,
        "container_name": config["container_name"],
        "lines_requested": lines,
        "logs": logs,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/logs/{service_id}", response_class=HTMLResponse)
async def logs_page(request: Request, service_id: str, lines: int = Query(100, ge=1, le=1000)):
    """Logs viewer page for a service."""
    if service_id not in SERVICES:
        return JSONResponse({"error": "Service not found"}, status_code=404)

    config = SERVICES[service_id]
    logs = get_container_logs(config["container_name"], lines)

    context = {
        "request": request,
        "service_id": service_id,
        "service_name": config["name"],
        "container_name": config["container_name"],
        "logs": logs,
        "lines": lines,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    return templates.TemplateResponse("logs.html", context)


@app.post("/api/restart/{service_id}")
async def api_restart_service(service_id: str):
    """Restart a service container."""
    if service_id not in SERVICES:
        return JSONResponse({"error": "Service not found"}, status_code=404)

    config = SERVICES[service_id]
    result = restart_container(config["container_name"])

    if result["success"]:
        return result
    else:
        return JSONResponse(result, status_code=500)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)