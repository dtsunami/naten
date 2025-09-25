"""Async UI components for responsive command execution with interruption support."""

import asyncio
import sys
import time
import threading
from typing import Optional, Callable, Any
import signal


class AsyncProgressIndicator:
    """Animated progress indicator that runs in background."""

    def __init__(self, message: str = "Processing"):
        self.message = message
        self.is_running = False
        self.task = None
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.current_frame = 0

    async def start(self):
        """Start the progress indicator."""
        self.is_running = True
        self.task = asyncio.create_task(self._animate())

    async def stop(self):
        """Stop the progress indicator."""
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        # Clear the line
        sys.stdout.write("\r" + " " * (len(self.message) + 10) + "\r")
        sys.stdout.flush()

    async def update_message(self, message: str):
        """Update the progress message."""
        self.message = message

    async def _animate(self):
        """Animation loop."""
        try:
            while self.is_running:
                frame = self.frames[self.current_frame]
                sys.stdout.write(f"\r🤖 {frame} {self.message}...")
                sys.stdout.flush()
                self.current_frame = (self.current_frame + 1) % len(self.frames)
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass


class InterruptibleTask:
    """Wrapper for async tasks that can be interrupted with Escape key."""

    def __init__(self):
        self.interrupted = False
        self.task = None
        self.progress = None

    async def run_with_progress(self,
                               coro: Callable[[], Any],
                               initial_message: str = "Processing",
                               allow_interrupt: bool = True) -> Any:
        """Run a coroutine with progress indicator and interrupt support."""

        # Set up progress indicator
        self.progress = AsyncProgressIndicator(initial_message)
        await self.progress.start()

        # Set up keyboard interrupt handler
        interrupt_task = None
        if allow_interrupt:
            interrupt_task = asyncio.create_task(self._monitor_interrupt())

        try:
            # Run the main task
            self.task = asyncio.create_task(coro())

            # Wait for either task completion or interrupt
            if interrupt_task:
                done, pending = await asyncio.wait(
                    [self.task, interrupt_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                # Cancel remaining tasks
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                # Check if interrupted
                if interrupt_task in done:
                    await self.progress.stop()
                    print("\n❌ Operation cancelled by user")
                    return None

                # Get result from completed task
                result = self.task.result()
            else:
                result = await self.task

            return result

        except asyncio.CancelledError:
            await self.progress.stop()
            print("\n❌ Operation cancelled")
            return None
        except Exception as e:
            await self.progress.stop()
            print(f"\n❌ Error: {e}")
            return None
        finally:
            if self.progress:
                await self.progress.stop()

    async def _monitor_interrupt(self):
        """Monitor for escape key press in a separate thread."""
        import termios
        import tty

        def check_input():
            """Check for escape key in blocking way."""
            if sys.stdin.isatty():
                try:
                    # Save terminal settings
                    fd = sys.stdin.fileno()
                    old_settings = termios.tcgetattr(fd)

                    try:
                        # Set to raw mode for immediate key detection
                        tty.setraw(sys.stdin.fileno())

                        while not self.interrupted:
                            # Non-blocking read with timeout
                            import select
                            if select.select([sys.stdin], [], [], 0.1)[0]:
                                key = sys.stdin.read(1)
                                if ord(key) == 27:  # Escape key
                                    self.interrupted = True
                                    break

                            if self.task and self.task.done():
                                break

                    finally:
                        # Restore terminal settings
                        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

                except (OSError, termios.error):
                    # Fallback: just wait and check periodically
                    while not self.interrupted and not (self.task and self.task.done()):
                        time.sleep(0.1)

        # Run input checking in thread to avoid blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, check_input)

        if self.interrupted:
            # Cancel the main task
            if self.task and not self.task.done():
                self.task.cancel()

    async def update_progress(self, message: str):
        """Update progress message."""
        if self.progress:
            await self.progress.update_message(message)


class AsyncCommandUI:
    """Enhanced UI for async command execution with status updates."""

    def __init__(self):
        self.current_task = None

    async def execute_with_status(self,
                                 command_func: Callable[[], Any],
                                 initial_message: str = "Executing command",
                                 success_message: str = "✅ Command completed",
                                 allow_interrupt: bool = True) -> Any:
        """Execute a command with live status updates and interrupt support."""

        # Show initial status
        print(f"\n🤖 Assistant: {initial_message}...")

        # Create interruptible task
        self.current_task = InterruptibleTask()

        # Show hint about interruption
        if allow_interrupt:
            print("💡 Press ESC to cancel")

        try:
            result = await self.current_task.run_with_progress(
                command_func,
                initial_message,
                allow_interrupt
            )

            if result is not None:
                print(f"{success_message}")
                return result
            else:
                return None

        except Exception as e:
            print(f"❌ Error: {e}")
            return None
        finally:
            self.current_task = None

    async def chat_with_agent(self, agent_chat_func: Callable[[str], Any],
                             message: str) -> Optional[str]:
        """Execute agent chat with status updates."""

        async def chat_wrapper():
            # Update progress through different stages
            if self.current_task:
                await self.current_task.update_progress("Analyzing request")
                await asyncio.sleep(0.5)  # Brief pause for user to see

                await self.current_task.update_progress("Generating response")

            # Execute the actual chat
            return await agent_chat_func(message)

        result = await self.execute_with_status(
            chat_wrapper,
            "Thinking",
            "🤖",  # Just show the robot emoji when done
            allow_interrupt=True
        )

        return result

    async def execute_shell_command(self,
                                   shell_func: Callable[[], Any],
                                   command: str) -> Any:
        """Execute shell command with status updates."""

        async def shell_wrapper():
            if self.current_task:
                await self.current_task.update_progress(f"Preparing: {command[:30]}...")
                await asyncio.sleep(0.2)

                await self.current_task.update_progress("Executing command")

            return await shell_func()

        return await self.execute_with_status(
            shell_wrapper,
            f"Running: {command[:40]}...",
            "✅ Command executed",
            allow_interrupt=False  # Don't interrupt actual command execution
        )


# Global instance
async_ui = AsyncCommandUI()


def setup_signal_handlers():
    """Setup signal handlers for graceful interruption."""
    def signal_handler(signum, frame):
        print("\n🛑 Received interrupt signal")
        # Set a flag or trigger cleanup
        # This will be caught by the main event loop

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)