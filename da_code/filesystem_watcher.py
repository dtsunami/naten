"""Filesystem watcher for tracking file changes in real-time."""

import asyncio
import logging
import os
from pathlib import Path
from typing import Callable, Optional, Set
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from .daignore import DaIgnore

logger = logging.getLogger(__name__)


class FilteredFileSystemHandler(FileSystemEventHandler):
    """File system event handler with filtering using .daignore."""

    def __init__(self, callback: Callable, daignore: DaIgnore):
        super().__init__()
        self.callback = callback
        self.daignore = daignore
        self._loop = None

    def set_event_loop(self, loop):
        """Set the event loop for async callback execution."""
        self._loop = loop

    def _should_ignore(self, path: str) -> bool:
        """Check if path should be ignored using .daignore."""
        return self.daignore.is_ignored(path)

    def _handle_event(self, event: FileSystemEvent):
        """Handle filesystem event asynchronously."""
        if event.is_directory:
            return

        if self._should_ignore(event.src_path):
            return

        # Schedule callback in the event loop
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.callback(event),
                self._loop
            )

    def on_created(self, event):
        self._handle_event(event)

    def on_modified(self, event):
        self._handle_event(event)

    def on_deleted(self, event):
        self._handle_event(event)

    def on_moved(self, event):
        self._handle_event(event)


class FileSystemWatcher:
    """Real-time filesystem watcher using watchdog."""

    def __init__(self, root_dir: str, on_change_callback: Callable, daignore: Optional[DaIgnore] = None):
        """
        Initialize filesystem watcher.

        Args:
            root_dir: Root directory to watch
            on_change_callback: Async callback for file changes
            daignore: DaIgnore instance for filtering (will create if None)
        """
        self.root_dir = Path(root_dir)
        self.callback = on_change_callback
        self.daignore = daignore or DaIgnore(project_root=str(self.root_dir))

        self.observer = Observer()
        self.handler = FilteredFileSystemHandler(on_change_callback, self.daignore)
        self.observer.schedule(self.handler, str(self.root_dir), recursive=True)
        self._started = False

        logger.info(f"FileSystemWatcher initialized for {self.root_dir}")

    def start(self, event_loop: asyncio.AbstractEventLoop):
        """Start watching filesystem."""
        if self._started:
            logger.warning("FileSystemWatcher already started")
            return

        self.handler.set_event_loop(event_loop)
        self.observer.start()
        self._started = True
        logger.info(f"FileSystemWatcher started for {self.root_dir}")

    def stop(self):
        """Stop watching filesystem."""
        if not self._started:
            return

        self.observer.stop()
        self.observer.join(timeout=2.0)
        self._started = False
        logger.info("FileSystemWatcher stopped")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
