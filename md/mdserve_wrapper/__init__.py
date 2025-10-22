"""
mdserve-wrapper - Python wrapper for mdserve Rust binary
Fast markdown preview server with live reload.
"""
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Union


class MarkdownServer:
    """Wrapper for the mdserve Rust binary."""

    def __init__(self):
        """Initialize the markdown server wrapper."""
        # Find the binary in the package
        package_dir = Path(__file__).parent
        binary_name = "mdserve.exe" if sys.platform == "win32" else "mdserve"
        self.binary = package_dir / "bin" / binary_name

        if not self.binary.exists():
            raise FileNotFoundError(
                f"mdserve binary not found at {self.binary}. "
                "Please reinstall the package: pip install -e ."
            )

    def serve(
        self,
        file_path: Union[str, Path],
        port: Optional[int] = None,
        host: Optional[str] = None,
        theme: Optional[str] = None,
    ) -> subprocess.Popen:
        """
        Start mdserve for a markdown file.

        Args:
            file_path: Path to the markdown file to serve
            port: Port to serve on (default: 3000)
            host: Host to bind to (default: 127.0.0.1)
            theme: Color theme (e.g., 'latte', 'frappe', 'macchiato', 'mocha')

        Returns:
            Popen process object

        Example:
            >>> server = MarkdownServer()
            >>> process = server.serve("README.md", port=8080)
            >>> # Server running in background
            >>> process.terminate()  # Stop server
        """
        cmd = [str(self.binary), str(file_path)]

        if port:
            cmd.extend(["--port", str(port)])
        if host:
            cmd.extend(["--host", host])
        if theme:
            cmd.extend(["--theme", theme])

        return subprocess.Popen(cmd)

    def serve_blocking(
        self,
        file_path: Union[str, Path],
        port: Optional[int] = None,
        host: Optional[str] = None,
        theme: Optional[str] = None,
    ):
        """
        Start mdserve and wait for it to complete (blocking).

        Args:
            file_path: Path to the markdown file to serve
            port: Port to serve on (default: 3000)
            host: Host to bind to (default: 127.0.0.1)
            theme: Color theme

            
        Example:
            >>> server = MarkdownServer()
            >>> server.serve_blocking("README.md")  # Ctrl+C to stop
        """
        process = self.serve(file_path, port=port, host=host, theme=theme)
        try:
            process.wait()
        except KeyboardInterrupt:
            process.terminate()
            process.wait()


__version__ = "0.1.0"
__all__ = ["MarkdownServer"]