#!/usr/bin/env python3
"""Search MCP Server - Web search, news, and content extraction."""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse, quote

import httpx
import feedparser
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv("../../.env")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/app/logs/search_mcp.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("search_mcp")

app = FastAPI(
    title="Search MCP Server",
    description="Web search, news, and content extraction MCP server",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models for MCP requests
class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    method: str
    params: Optional[Dict[str, Any]] = None

class MCPResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

# Search result models
class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    source: str
    published_date: Optional[str] = None

class ContentExtraction(BaseModel):
    title: str
    content: str
    url: str
    word_count: int
    extracted_at: str

class SearchEngine:
    """Handle different search engines and APIs."""

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; SearchMCP/1.0)"
            }
        )

    async def duckduckgo_search(self, query: str, num_results: int = 10, time_filter: str = None) -> List[SearchResult]:
        """Search using DuckDuckGo API."""
        try:
            # DuckDuckGo Instant Answer API
            encoded_query = quote(query)
            url = f"https://api.duckduckgo.com/?q={encoded_query}&format=json&no_html=1&skip_disambig=1"

            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()

            results = []

            # Process instant answers
            if data.get("Answer"):
                results.append(SearchResult(
                    title=f"Instant Answer: {query}",
                    url=data.get("AnswerURL", ""),
                    snippet=data["Answer"],
                    source="DuckDuckGo Instant Answer"
                ))

            # Process related topics
            for topic in data.get("RelatedTopics", [])[:num_results]:
                if isinstance(topic, dict) and "Text" in topic:
                    results.append(SearchResult(
                        title=topic.get("FirstURL", "").split("/")[-1].replace("_", " "),
                        url=topic.get("FirstURL", ""),
                        snippet=topic["Text"],
                        source="DuckDuckGo"
                    ))

            # If we don't have enough results, try web search
            if len(results) < 3:
                web_results = await self._duckduckgo_web_search(query, num_results)
                results.extend(web_results)

            return results[:num_results]

        except Exception as e:
            logger.error(f"DuckDuckGo search error: {e}")
            return []

    async def _duckduckgo_web_search(self, query: str, num_results: int) -> List[SearchResult]:
        """Fallback web search using DuckDuckGo HTML."""
        try:
            encoded_query = quote(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

            response = await self.client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            results = []

            for result_div in soup.find_all('div', class_='result')[:num_results]:
                title_elem = result_div.find('a', class_='result__a')
                snippet_elem = result_div.find('a', class_='result__snippet')

                if title_elem and snippet_elem:
                    results.append(SearchResult(
                        title=title_elem.get_text(strip=True),
                        url=title_elem.get('href', ''),
                        snippet=snippet_elem.get_text(strip=True),
                        source="DuckDuckGo Web"
                    ))

            return results

        except Exception as e:
            logger.error(f"DuckDuckGo web search error: {e}")
            return []

    async def google_news_search(self, query: str, hours_back: int = 24, language: str = "en") -> List[SearchResult]:
        """Search Google News RSS for recent articles."""
        try:
            encoded_query = quote(query)
            # Google News RSS feed
            url = f"https://news.google.com/rss/search?q={encoded_query}&hl={language}&gl=US&ceid=US:{language}"

            response = await self.client.get(url)
            response.raise_for_status()

            feed = feedparser.parse(response.text)
            results = []

            cutoff_time = datetime.now() - timedelta(hours=hours_back)

            for entry in feed.entries:
                # Parse published date
                published_date = None
                try:
                    if hasattr(entry, 'published_parsed'):
                        published_date = datetime(*entry.published_parsed[:6])
                except:
                    published_date = datetime.now()  # Fallback to current time

                # Filter by time if specified
                if published_date and published_date < cutoff_time:
                    continue

                # Clean title (remove source prefix)
                title = entry.title
                if " - " in title:
                    title = title.split(" - ")[0]

                results.append(SearchResult(
                    title=title,
                    url=entry.link,
                    snippet=entry.get('summary', '')[:200],
                    source=entry.get('source', {}).get('title', 'Google News'),
                    published_date=published_date.isoformat() if published_date else None
                ))

            return results

        except Exception as e:
            logger.error(f"Google News search error: {e}")
            return []

    async def extract_url_content(self, url: str, extract_type: str = "text") -> ContentExtraction:
        """Extract content from a URL."""
        try:
            response = await self.client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()

            # Extract title
            title = "Unknown Title"
            if soup.title:
                title = soup.title.string.strip()
            elif soup.find('h1'):
                title = soup.find('h1').get_text(strip=True)

            # Extract content based on type
            if extract_type == "text":
                # Extract main content
                content_elements = soup.find_all(['p', 'article', 'main', 'div'])
                content_parts = []

                for elem in content_elements:
                    text = elem.get_text(strip=True)
                    if len(text) > 50:  # Filter out short elements
                        content_parts.append(text)

                content = "\n\n".join(content_parts[:10])  # Limit to first 10 paragraphs

            elif extract_type == "title":
                content = title

            elif extract_type == "summary":
                # Extract first few paragraphs
                paragraphs = soup.find_all('p')
                summary_parts = []
                for p in paragraphs[:3]:
                    text = p.get_text(strip=True)
                    if len(text) > 30:
                        summary_parts.append(text)
                content = "\n\n".join(summary_parts)

            else:
                content = soup.get_text(strip=True)

            return ContentExtraction(
                title=title,
                content=content[:2000],  # Limit content length
                url=url,
                word_count=len(content.split()),
                extracted_at=datetime.now().isoformat()
            )

        except Exception as e:
            logger.error(f"Content extraction error for {url}: {e}")
            raise HTTPException(status_code=400, detail=f"Failed to extract content: {str(e)}")

# Initialize search engine
search_engine = SearchEngine()

# MCP Server endpoints
@app.post("/mcp")
async def mcp_handler(request: MCPRequest):
    """Main MCP endpoint handler."""
    try:
        method = request.method
        params = request.params or {}

        if method == "tools/list":
            return MCPResponse(
                id=request.id,
                result={
                    "tools": [
                        {
                            "name": "web_search",
                            "description": "Search the web for current information",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string", "description": "Search query"},
                                    "num_results": {"type": "integer", "default": 10, "description": "Number of results"},
                                    "time_filter": {"type": "string", "enum": ["day", "week", "month", "year"], "description": "Time filter"}
                                },
                                "required": ["query"]
                            }
                        },
                        {
                            "name": "news_search",
                            "description": "Search recent news articles",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string", "description": "News search query"},
                                    "hours_back": {"type": "integer", "default": 24, "description": "Hours back to search"},
                                    "language": {"type": "string", "default": "en", "description": "Language code"}
                                },
                                "required": ["query"]
                            }
                        },
                        {
                            "name": "url_content",
                            "description": "Extract text content from a URL",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "url": {"type": "string", "description": "URL to extract content from"},
                                    "extract_type": {"type": "string", "enum": ["text", "title", "summary"], "default": "text", "description": "Type of extraction"}
                                },
                                "required": ["url"]
                            }
                        }
                    ]
                }
            )

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if tool_name == "web_search":
                results = await search_engine.duckduckgo_search(
                    query=arguments["query"],
                    num_results=arguments.get("num_results", 10),
                    time_filter=arguments.get("time_filter")
                )
                return MCPResponse(
                    id=request.id,
                    result={
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps([result.dict() for result in results], indent=2)
                            }
                        ],
                        "isError": False
                    }
                )

            elif tool_name == "news_search":
                results = await search_engine.google_news_search(
                    query=arguments["query"],
                    hours_back=arguments.get("hours_back", 24),
                    language=arguments.get("language", "en")
                )
                return MCPResponse(
                    id=request.id,
                    result={
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps([result.dict() for result in results], indent=2)
                            }
                        ],
                        "isError": False
                    }
                )

            elif tool_name == "url_content":
                content = await search_engine.extract_url_content(
                    url=arguments["url"],
                    extract_type=arguments.get("extract_type", "text")
                )
                return MCPResponse(
                    id=request.id,
                    result={
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(content.dict(), indent=2)
                            }
                        ],
                        "isError": False
                    }
                )

            else:
                return MCPResponse(
                    id=request.id,
                    error={"code": -32601, "message": f"Unknown tool: {tool_name}"}
                )

        else:
            return MCPResponse(
                id=request.id,
                error={"code": -32601, "message": f"Unknown method: {method}"}
            )

    except Exception as e:
        logger.error(f"MCP handler error: {e}")
        return MCPResponse(
            id=request.id,
            error={"code": -32603, "message": f"Internal error: {str(e)}"}
        )

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "server": "search_mcp",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/")
async def root():
    """Root endpoint with API documentation."""
    return {
        "message": "Search MCP Server",
        "version": "1.0.0",
        "endpoints": {
            "mcp": "/mcp",
            "health": "/health",
            "docs": "/docs"
        },
        "tools": ["web_search", "news_search", "url_content"]
    }

if __name__ == "__main__":
    port = int(os.getenv("SEARCH_PORT", "8003"))
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        access_log=True
    )