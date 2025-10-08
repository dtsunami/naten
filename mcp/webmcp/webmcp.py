#!/usr/bin/env python3
"""
Browser Automation MCP Server for da_code
Leverages local browser credentials and sessions with Playwright integration
"""

import asyncio
import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from pydantic import BaseModel, Field

from basemcp.server import BaseMCPServer, tool


class BrowserConfig(BaseModel):
    """Browser automation configuration."""
    browser_type: str = Field("chromium", description="Browser type: chromium, firefox, webkit")
    headless: bool = Field(False, description="Run browser in headless mode")
    user_data_dir: Optional[str] = Field(None, description="Path to user data directory")
    timeout: int = Field(30000, description="Default timeout in milliseconds")
    viewport_width: int = Field(1280, description="Viewport width")
    viewport_height: int = Field(720, description="Viewport height")

class NavigateParams(BaseModel):
    """Parameters for page navigation."""
    url: str = Field(..., description="URL to navigate to")
    wait_until: str = Field("domcontentloaded", description="Wait condition: load, domcontentloaded, networkidle")
    timeout: Optional[int] = Field(None, description="Navigation timeout in milliseconds")

class ClickParams(BaseModel):
    """Parameters for clicking elements."""
    selector: str = Field(..., description="CSS selector or accessibility name")
    timeout: Optional[int] = Field(None, description="Click timeout in milliseconds")
    force: bool = Field(False, description="Force click even if element not actionable")
    button: str = Field("left", description="Mouse button: left, right, middle")

class FillParams(BaseModel):
    """Parameters for filling form fields."""
    selector: str = Field(..., description="CSS selector for input field")
    value: str = Field(..., description="Text value to fill")
    timeout: Optional[int] = Field(None, description="Fill timeout in milliseconds")
    clear: bool = Field(True, description="Clear field before filling")

class ScreenshotParams(BaseModel):
    """Parameters for taking screenshots."""
    full_page: bool = Field(False, description="Capture full page or just viewport")
    path: Optional[str] = Field(None, description="Path to save screenshot")
    format: str = Field("png", description="Image format: png, jpeg")
    quality: Optional[int] = Field(None, description="JPEG quality 0-100")

class EvaluateParams(BaseModel):
    """Parameters for JavaScript evaluation."""
    script: str = Field(..., description="JavaScript code to execute")
    args: List[Any] = Field(default_factory=list, description="Arguments to pass to script")

class WaitParams(BaseModel):
    """Parameters for waiting operations."""
    selector: Optional[str] = Field(None, description="CSS selector to wait for")
    text: Optional[str] = Field(None, description="Text content to wait for")
    timeout: Optional[int] = Field(None, description="Wait timeout in milliseconds")
    state: str = Field("visible", description="Element state: visible, hidden, attached, detached")


class BrowserMCPServer(BaseMCPServer):
    """Browser automation MCP server using Playwright with local credential support."""

    def __init__(self):
        super().__init__(
            name="browser",
            description="Browser automation with Playwright - navigate, interact, and scrape web pages",
            version="1.0.0"
        )

        self.config = BrowserConfig()
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.pages: Dict[str, Page] = {}
        self.active_page_id: Optional[str] = None

    async def startup(self):
        """Initialize Playwright and browser."""
        try:
            self.playwright = await async_playwright().start()
            await self._launch_browser()

            # Auto-copy connection command to clipboard
            await self._copy_connection_command()

            self.logger.info("🌐 Browser MCP server started successfully")
            self.logger.info(f"🔧 Browser: {self.config.browser_type}")
            self.logger.info(f"👁️ Headless: {self.config.headless}")
            if self.config.user_data_dir:
                self.logger.info(f"📁 User data: {self.config.user_data_dir}")

        except Exception as e:
            self.logger.error(f"Failed to start browser: {e}")
            raise

    async def cleanup(self):
        """Clean up browser resources."""
        try:
            if self.pages:
                for page in self.pages.values():
                    await page.close()
                self.pages.clear()

            if self.context:
                await self.context.close()

            if self.browser:
                await self.browser.close()

            if self.playwright:
                await self.playwright.stop()

            self.logger.info("🌐 Browser MCP server stopped")

        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")

    async def _launch_browser(self):
        """Launch browser with configuration."""
        browser_args = []

        # Auto-detect user data directory for credential reuse
        if not self.config.user_data_dir:
            self.config.user_data_dir = self._detect_user_data_dir()

        launch_options = {
            "headless": self.config.headless,
            "args": browser_args
        }

        # Add user data directory if available (for credential reuse)
        if self.config.user_data_dir and os.path.exists(self.config.user_data_dir):
            launch_options["user_data_dir"] = self.config.user_data_dir
            self.logger.info(f"📁 Using existing browser profile: {self.config.user_data_dir}")

        # Launch browser
        if self.config.browser_type == "chromium":
            self.browser = await self.playwright.chromium.launch(**launch_options)
        elif self.config.browser_type == "firefox":
            self.browser = await self.playwright.firefox.launch(**launch_options)
        elif self.config.browser_type == "webkit":
            self.browser = await self.playwright.webkit.launch(**launch_options)
        else:
            raise ValueError(f"Unsupported browser type: {self.config.browser_type}")

        # Create context
        self.context = await self.browser.new_context(
            viewport={"width": self.config.viewport_width, "height": self.config.viewport_height}
        )

        # Create initial page
        page = await self.context.new_page()
        page_id = "main"
        self.pages[page_id] = page
        self.active_page_id = page_id

    def _detect_user_data_dir(self) -> Optional[str]:
        """Auto-detect browser user data directory for credential reuse."""
        import platform

        system = platform.system()
        home = Path.home()

        # Chrome/Chromium user data directories by OS
        if self.config.browser_type == "chromium":
            if system == "Windows":
                paths = [
                    home / "AppData/Local/Google/Chrome/User Data",
                    home / "AppData/Local/Chromium/User Data"
                ]
            elif system == "Darwin":  # macOS
                paths = [
                    home / "Library/Application Support/Google/Chrome",
                    home / "Library/Application Support/Chromium"
                ]
            else:  # Linux
                paths = [
                    home / ".config/google-chrome",
                    home / ".config/chromium"
                ]

            for path in paths:
                if path.exists():
                    return str(path)

        return None

    async def _copy_connection_command(self):
        """Generate and copy MCP connection command to clipboard."""
        try:
            import socket

            # Get local IP
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)

            connection_config = {
                "name": "browser",
                "url": f"http://{local_ip}:{self.port}",
                "description": f"Browser automation from {hostname}",
                "tools": [
                    "browser_navigate", "browser_click", "browser_fill",
                    "browser_screenshot", "browser_evaluate", "browser_wait",
                    "browser_get_content", "browser_new_tab", "browser_close_tab"
                ]
            }

            connection_json = json.dumps(connection_config, indent=2)

            # Try to copy to clipboard
            try:
                import pyperclip
                pyperclip.copy(connection_json)
                print(f"✅ Connection command copied to clipboard!")
            except ImportError:
                pass

            print(f"📋 Browser MCP Connection Config:")
            print(connection_json)

        except Exception as e:
            self.logger.warning(f"Could not generate connection command: {e}")

    @tool("browser_navigate")
    async def navigate(self, params: NavigateParams) -> Dict[str, Any]:
        """Navigate to a URL."""
        try:
            page = self._get_active_page()

            timeout = params.timeout or self.config.timeout

            response = await page.goto(
                params.url,
                wait_until=params.wait_until,
                timeout=timeout
            )

            # Get basic page info
            title = await page.title()
            url = page.url

            return {
                "success": True,
                "url": url,
                "title": title,
                "status": response.status if response else None,
                "message": f"Successfully navigated to {url}"
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to navigate to {params.url}"
            }

    @tool("browser_click")
    async def click(self, params: ClickParams) -> Dict[str, Any]:
        """Click an element on the page."""
        try:
            page = self._get_active_page()

            timeout = params.timeout or self.config.timeout

            await page.click(
                params.selector,
                timeout=timeout,
                force=params.force,
                button=params.button
            )

            return {
                "success": True,
                "message": f"Successfully clicked element: {params.selector}"
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to click element: {params.selector}"
            }

    @tool("browser_fill")
    async def fill(self, params: FillParams) -> Dict[str, Any]:
        """Fill a form field."""
        try:
            page = self._get_active_page()

            timeout = params.timeout or self.config.timeout

            if params.clear:
                await page.fill(params.selector, "", timeout=timeout)

            await page.fill(params.selector, params.value, timeout=timeout)

            return {
                "success": True,
                "message": f"Successfully filled field: {params.selector}"
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to fill field: {params.selector}"
            }

    @tool("browser_screenshot")
    async def screenshot(self, params: ScreenshotParams) -> Dict[str, Any]:
        """Take a screenshot of the page."""
        try:
            page = self._get_active_page()

            screenshot_options = {
                "full_page": params.full_page,
                "type": params.format
            }

            if params.quality and params.format == "jpeg":
                screenshot_options["quality"] = params.quality

            if params.path:
                screenshot_options["path"] = params.path
                screenshot_bytes = await page.screenshot(**screenshot_options)

                return {
                    "success": True,
                    "path": params.path,
                    "message": f"Screenshot saved to {params.path}"
                }
            else:
                # Return base64 encoded screenshot
                screenshot_bytes = await page.screenshot(**screenshot_options)
                screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

                return {
                    "success": True,
                    "screenshot": screenshot_b64,
                    "format": params.format,
                    "message": "Screenshot captured successfully"
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to take screenshot"
            }

    @tool("browser_evaluate")
    async def evaluate(self, params: EvaluateParams) -> Dict[str, Any]:
        """Evaluate JavaScript on the page."""
        try:
            page = self._get_active_page()

            if params.args:
                result = await page.evaluate(params.script, params.args)
            else:
                result = await page.evaluate(params.script)

            return {
                "success": True,
                "result": result,
                "message": "JavaScript executed successfully"
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to execute JavaScript"
            }

    @tool("browser_wait")
    async def wait(self, params: WaitParams) -> Dict[str, Any]:
        """Wait for elements or conditions."""
        try:
            page = self._get_active_page()

            timeout = params.timeout or self.config.timeout

            if params.selector:
                await page.wait_for_selector(
                    params.selector,
                    state=params.state,
                    timeout=timeout
                )
                message = f"Element found: {params.selector}"

            elif params.text:
                await page.wait_for_function(
                    f"document.body.innerText.includes('{params.text}')",
                    timeout=timeout
                )
                message = f"Text found: {params.text}"

            else:
                await asyncio.sleep(1)  # Default 1 second wait
                message = "Wait completed"

            return {
                "success": True,
                "message": message
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Wait condition failed"
            }

    @tool("browser_get_content")
    async def get_content(self) -> Dict[str, Any]:
        """Get page content and metadata."""
        try:
            page = self._get_active_page()

            # Get page information
            title = await page.title()
            url = page.url
            content = await page.content()
            text_content = await page.inner_text("body")

            return {
                "success": True,
                "url": url,
                "title": title,
                "html": content,
                "text": text_content,
                "message": "Page content retrieved successfully"
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to get page content"
            }

    @tool("browser_new_tab")
    async def new_tab(self, url: Optional[str] = None) -> Dict[str, Any]:
        """Create a new browser tab."""
        try:
            page = await self.context.new_page()

            # Generate unique page ID
            page_id = f"tab_{len(self.pages)}"
            self.pages[page_id] = page
            self.active_page_id = page_id

            if url:
                await page.goto(url)
                title = await page.title()
                message = f"New tab created and navigated to {url}"
            else:
                title = "New Tab"
                message = "New tab created"

            return {
                "success": True,
                "page_id": page_id,
                "url": url or "about:blank",
                "title": title,
                "message": message
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to create new tab"
            }

    @tool("browser_close_tab")
    async def close_tab(self, page_id: Optional[str] = None) -> Dict[str, Any]:
        """Close a browser tab."""
        try:
            if page_id is None:
                page_id = self.active_page_id

            if page_id not in self.pages:
                return {
                    "success": False,
                    "error": f"Tab not found: {page_id}",
                    "message": f"No tab with ID {page_id}"
                }

            page = self.pages[page_id]
            await page.close()
            del self.pages[page_id]

            # Switch to another tab if this was active
            if self.active_page_id == page_id:
                if self.pages:
                    self.active_page_id = next(iter(self.pages.keys()))
                else:
                    self.active_page_id = None

            return {
                "success": True,
                "message": f"Tab {page_id} closed successfully"
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to close tab {page_id}"
            }

    def _get_active_page(self) -> Page:
        """Get the currently active page."""
        if not self.active_page_id or self.active_page_id not in self.pages:
            raise RuntimeError("No active browser tab available")
        return self.pages[self.active_page_id]


# Server factory function
def create_server() -> BrowserMCPServer:
    """Create and configure the browser MCP server."""
    return BrowserMCPServer()


def main():
    """Main entry point for webmcp command."""
    import argparse

    # ASCII art banner
    print("""
██╗    ██╗███████╗██████╗ ███╗   ███╗ ██████╗██████╗
██║    ██║██╔════╝██╔══██╗████╗ ████║██╔════╝██╔══██╗
██║ █╗ ██║█████╗  ██████╔╝██╔████╔██║██║     ██████╔╝
██║███╗██║██╔══╝  ██╔══██╗██║╚██╔╝██║██║     ██╔═══╝
╚███╔███╔╝███████╗██████╔╝██║ ╚═╝ ██║╚██████╗██║
 ╚══╝╚══╝ ╚══════╝╚═════╝ ╚═╝     ╚═╝ ╚═════╝╚═╝

    🌐 Browser Automation MCP Server
    """)

    parser = argparse.ArgumentParser(
        description="webmcp - Browser automation MCP server with local credential support"
    )
    parser.add_argument("--port", type=int, default=8005, help="Server port (default: 8005)")
    parser.add_argument("--host", default="localhost", help="Server host (default: localhost)")
    parser.add_argument("--browser", default="chromium",
                       choices=["chromium", "firefox", "webkit"],
                       help="Browser type (default: chromium)")
    parser.add_argument("--headless", action="store_true",
                       help="Run in headless mode (default: False for local use)")
    parser.add_argument("--user-data-dir", help="Browser user data directory (auto-detected if not specified)")

    args = parser.parse_args()

    print(f"🚀 Starting webmcp server...")
    print(f"🔧 Browser: {args.browser}")
    print(f"👁️ Headless: {args.headless}")
    print(f"🌐 Host: {args.host}:{args.port}")

    # Create and configure server
    server = create_server()
    server.config.browser_type = args.browser
    server.config.headless = args.headless
    server.port = args.port

    if args.user_data_dir:
        server.config.user_data_dir = args.user_data_dir

    try:
        # Run server
        asyncio.run(server.run(host=args.host, port=args.port))
    except KeyboardInterrupt:
        print("\n👋 webmcp server stopped")
    except Exception as e:
        print(f"❌ Server error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())