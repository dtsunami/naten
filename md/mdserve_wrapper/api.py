"""FastAPI hub to manage multiple mdserve instances and provide a tree-style UI.

Run with: python -m mdserve_wrapper.api or via entrypoint mdserve-hub
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
import uvicorn

from . import MarkdownServer
from .cli import find_markdown_files

BASE_PORT = int(os.environ.get("MD_HUB_BASE_PORT", "3100"))
HOST = os.environ.get("MD_HUB_HOST", "127.0.0.1")

app = FastAPI()

# Serve the simple tree UI
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@dataclass
class ServerInfo:
    id: str
    file: str
    port: int
    host: str
    theme: Optional[str]
    pid: int


class MdserveManager:
    def __init__(self, base_port: int = BASE_PORT, host: str = HOST):
        self.base_port = base_port
        self.host = host
        self._servers: Dict[str, ServerInfo] = {}
        self._processes: Dict[str, "asyncio.subprocess.Process|object"] = {}
        self._used_ports: set[int] = set()
        self._lock = asyncio.Lock()
        self._md = MarkdownServer()

    async def _next_port(self) -> int:
        port = self.base_port
        while port in self._used_ports:
            port += 1
        self._used_ports.add(port)
        return port

    async def list_files(self, directory: Optional[str] = None) -> List[str]:
        directory = Path(directory) if directory else None
        files = find_markdown_files(directory)
        return [str(p) for p in files]

    async def list_servers(self) -> List[Dict]:
        return [asdict(s) for s in self._servers.values()]

    async def start_server(self, file: str, port: Optional[int] = None, host: Optional[str] = None, theme: Optional[str] = None) -> Dict:
        async with self._lock:
            assigned = port or await self._next_port()
            host = host or self.host
            sid = str(uuid.uuid4())

            # Start process using MarkdownServer
            popen = self._md.serve(file, port=assigned, host=host, theme=theme)

            info = ServerInfo(id=sid, file=str(file), port=assigned, host=host, theme=theme, pid=popen.pid)
            self._servers[sid] = info
            self._processes[sid] = popen
            return asdict(info)

    async def stop_server(self, sid: str) -> bool:
        async with self._lock:
            if sid not in self._processes:
                raise KeyError(sid)
            proc = self._processes.pop(sid)
            try:
                proc.terminate()
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            # wait for process termination (non-blocking)
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            info = self._servers.pop(sid, None)
            if info:
                self._used_ports.discard(info.port)
            return True

    def get_server(self, sid: str) -> ServerInfo:
        return self._servers.get(sid)


manager = MdserveManager()


@app.get("/api/files")
async def api_files(dir: Optional[str] = None):
    files = await manager.list_files(dir)
    return JSONResponse(files)


@app.get("/api/servers")
async def api_servers():
    return JSONResponse(await manager.list_servers())


@app.post("/api/servers")
async def api_start(request: Request):
    body = await request.json()
    file = body.get("file")
    if not file:
        raise HTTPException(status_code=400, detail="'file' required")
    port = body.get("port")
    host = body.get("host")
    theme = body.get("theme")

    try:
        info = await manager.start_server(file=file, port=port, host=host, theme=theme)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse(info)


@app.delete("/api/servers/{sid}")
async def api_stop(sid: str):
    try:
        await manager.stop_server(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="server not found")
    return JSONResponse({"ok": True})


@app.get("/proxy/{sid}")
@app.get("/proxy/{sid}/{path:path}")
async def proxy_get(sid: str, path: Optional[str] = ""):
    info = manager.get_server(sid)
    if not info:
        raise HTTPException(status_code=404, detail="server not found")

    upstream = f"http://{info.host}:{info.port}/{path}"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(upstream, timeout=30)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=str(e))
    return JSONResponse(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))


@app.api_route("/proxy/{sid}/{path:path}", methods=["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_other(sid: str, request: Request, path: str):
    info = manager.get_server(sid)
    if not info:
        raise HTTPException(status_code=404, detail="server not found")

    upstream = f"http://{info.host}:{info.port}/{path}"
    data = await request.body()
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.request(request.method, upstream, content=data, headers=request.headers, timeout=30)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=str(e))
    return JSONResponse(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))


from fastapi.responses import FileResponse


@app.get("/")
async def index():
    # Serve the static UI index
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse({"ok": True})


def serve_cli():
    """CLI entrypoint for pyproject scripts. Only option: --port"""
    import argparse

    parser = argparse.ArgumentParser(description="Run mdserve hub (FastAPI dashboard for markdown files)")
    parser.add_argument("--port", "-p", type=int, default=int(os.environ.get("MD_HUB_PORT", "3000")), help="Port to bind the hub (default: 3000)")
    args = parser.parse_args()

    # Host is fixed by env MD_HUB_BIND or defaults to 0.0.0.0; CLI does not expose host to keep interface minimal
    host = os.environ.get("MD_HUB_BIND", "0.0.0.0")

    # Start uvicorn programmatically
    uvicorn.run(app, host=host, port=args.port, log_level="info")


if __name__ == "__main__":
    serve_cli()