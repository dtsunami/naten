"""MCP server for voice transcription."""

import argparse
import logging
import socket
import sys
from typing import Dict, Optional

import pyperclip
from fastapi import FastAPI
from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel

from voice import VoiceRecorder, WhisperTranscriber, StreamingRecordingSession

logger = logging.getLogger(__name__)
console = Console()


class TranscribeRequest(BaseModel):
    """Request model for voice transcription."""
    duration: float = Field(default=10.0, description="Recording duration in seconds", ge=1.0, le=60.0)
    language: Optional[str] = Field(default=None, description="Language code (e.g., 'en', 'es')")


class TranscribeResponse(BaseModel):
    """Response model for voice transcription."""
    text: str = Field(..., description="Transcribed text")
    language: str = Field(..., description="Detected or specified language")
    success: bool = Field(..., description="Whether transcription succeeded")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class VoiceMCPServer:
    """MCP server exposing voice transcription tools."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765, whisper_model: str = "base"):
        """Initialize voice MCP server.

        Args:
            host: Host to bind to
            port: Port to bind to
            whisper_model: Whisper model size (tiny, base, small, medium, large)
        """
        self.host = host
        self.port = port
        self.app = FastAPI(title="achat - Voice MCP Server", version="0.1.0")

        # Initialize voice components
        self.recorder = VoiceRecorder()
        self.transcriber = WhisperTranscriber(model_name=whisper_model)

        # Session management for streaming recordings
        self.streaming_sessions: Dict[str, StreamingRecordingSession] = {}

        # Register routes
        self._register_routes()

    def _register_routes(self):
        """Register FastAPI routes for MCP tools."""

        @self.app.get("/")
        async def root():
            """Health check endpoint."""
            return {
                "service": "achat",
                "status": "running",
                "version": "0.1.0",
                "tools": [
                    "voice_transcribe",
                    "voice_quick_record",
                    "voice_stream_start",
                    "voice_stream_chunk",
                    "voice_stream_stop"
                ]
            }

        @self.app.post("/tools/voice_transcribe", response_model=TranscribeResponse)
        async def voice_transcribe(request: TranscribeRequest) -> TranscribeResponse:
            """Record audio from microphone and transcribe to text.

            This is the main voice transcription tool for AI agents.
            """
            try:
                # Record audio
                audio = self.recorder.record(duration=request.duration)

                # Transcribe
                result = self.transcriber.transcribe(audio, language=request.language)

                return TranscribeResponse(**result)

            except Exception as e:
                logger.error(f"voice_transcribe failed: {e}")
                return TranscribeResponse(
                    text="",
                    language="unknown",
                    success=False,
                    error=str(e)
                )

        @self.app.post("/tools/voice_quick_record", response_model=TranscribeResponse)
        async def voice_quick_record() -> TranscribeResponse:
            """Quick voice recording (5 seconds) for short prompts.

            Convenience tool for quick voice input without specifying duration.
            """
            try:
                # Record audio (5 seconds)
                audio = self.recorder.record(duration=5.0)

                # Transcribe
                result = self.transcriber.transcribe(audio)

                return TranscribeResponse(**result)

            except Exception as e:
                logger.error(f"voice_quick_record failed: {e}")
                return TranscribeResponse(
                    text="",
                    language="unknown",
                    success=False,
                    error=str(e)
                )

        @self.app.post("/tools/voice_stream_start")
        async def voice_stream_start() -> dict:
            """Start a streaming voice recording session with VAD.

            Returns session_id for polling chunks.
            """
            try:
                # Generate unique session ID
                import uuid
                session_id = str(uuid.uuid4())

                # Create streaming session
                session = StreamingRecordingSession(
                    session_id=session_id,
                    transcriber=self.transcriber,
                    chunk_duration=3.0,  # 3-second chunks
                    max_duration=25.0,   # 25-second max
                    silence_threshold=2.0  # 2 seconds of silence to auto-stop
                )

                # Store session
                self.streaming_sessions[session_id] = session

                # Start recording
                session.start()

                return {
                    "session_id": session_id,
                    "status": "recording",
                    "max_duration": 25.0
                }

            except Exception as e:
                logger.error(f"voice_stream_start failed: {e}")
                return {
                    "error": str(e),
                    "status": "error"
                }

        @self.app.get("/tools/voice_stream_chunk/{session_id}")
        async def voice_stream_chunk(session_id: str) -> dict:
            """Get new transcript chunks for a streaming session.

            Returns new chunks since last poll and completion status.
            """
            try:
                session = self.streaming_sessions.get(session_id)

                if not session:
                    return {
                        "error": "Session not found",
                        "status": "error"
                    }

                # Get new chunks
                new_chunks = session.get_new_chunks()

                # Check if complete
                is_complete = session.is_complete()

                # Clean up completed sessions
                if is_complete:
                    # Keep session for a bit in case of late polls
                    pass

                return {
                    "chunks": new_chunks,
                    "is_complete": is_complete,
                    "status": "success"
                }

            except Exception as e:
                logger.error(f"voice_stream_chunk failed: {e}")
                return {
                    "error": str(e),
                    "status": "error"
                }

        @self.app.post("/tools/voice_stream_stop/{session_id}")
        async def voice_stream_stop(session_id: str) -> dict:
            """Force stop a streaming recording session."""
            try:
                session = self.streaming_sessions.get(session_id)

                if not session:
                    return {
                        "error": "Session not found",
                        "status": "error"
                    }

                # Stop recording
                session.stop()

                # Get any remaining chunks
                final_chunks = session.get_new_chunks()

                return {
                    "chunks": final_chunks,
                    "status": "stopped"
                }

            except Exception as e:
                logger.error(f"voice_stream_stop failed: {e}")
                return {
                    "error": str(e),
                    "status": "error"
                }

    def _get_local_ip(self) -> str:
        """Get local IP address for display."""
        try:
            # Create a socket to get local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            return "localhost"

    def _show_startup_banner(self):
        """Display startup banner with connection info."""
        local_ip = self._get_local_ip()

        # Create connection commands
        local_cmd = f'add_voice http://localhost:{self.port}'
        remote_cmd = f'add_voice http://{local_ip}:{self.port}'

        # Auto-copy to clipboard (clippy style!)
        try:
            pyperclip.copy(local_cmd)
            clipboard_status = "✅ [green]Copied to clipboard![/green]"
        except Exception:
            clipboard_status = "⚠️  [yellow]Clipboard copy failed[/yellow]"

        # Create banner
        banner_content = f"""
🎤 [bold cyan]achat voice server[/bold cyan] v0.1.0

[bold]Status:[/bold] Running on http://{self.host}:{self.port}
[bold]Local IP:[/bold] {local_ip}

[bold]Voice Tools Available:[/bold]
  • Streaming recording with real-time transcription (Alt+V in da_code)
  • Voice Activity Detection (auto-stops on silence)
  • Up to 25 seconds recording per session
  • Whisper-powered transcription

{clipboard_status}

[bold]For Local CLI:[/bold]
[cyan]{local_cmd}[/cyan]

[bold]For Remote CLI (over SSH):[/bold]
[cyan]{remote_cmd}[/cyan]

[dim]Usage: Paste connection command into your da_code CLI prompt[/dim]
        """

        panel = Panel(
            banner_content.strip(),
            title="🎤 achat - Voice MCP Server",
            border_style="cyan",
            padding=(1, 2)
        )

        console.print()
        console.print(panel)
        console.print()
        console.print("🎤 [bold green]Ready to receive voice transcription requests![/bold green]")
        console.print("   Press [cyan]Ctrl+C[/cyan] to stop\n")

    def run(self):
        """Start the MCP server."""
        import uvicorn

        # Show startup banner
        self._show_startup_banner()

        # Start server
        uvicorn.run(
            self.app,
            host=self.host,
            port=self.port,
            log_level="warning",  # Reduce noise
            access_log=False
        )


def main():
    """Main entry point for achat/da_chat commands."""
    parser = argparse.ArgumentParser(
        description="achat - Voice transcription MCP server for AI agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  achat                              # Start with defaults (port 8765)
  achat --port 9000                  # Custom port
  achat --model small                # Better accuracy (slower)
  da_chat                            # Alternative command name

Connection:
  1. Start achat on your local machine
  2. Copy the connection command from output
  3. Paste into your da_code agent (local or remote via SSH)
  4. Agent can now use voice_transcribe() tool!
        """
    )

    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to bind to (default: 8765)"
    )

    parser.add_argument(
        "--model",
        choices=["tiny", "base", "small", "medium", "large"],
        default="base",
        help="Whisper model size (default: base). Larger = more accurate but slower"
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="WARNING",
        help="Logging level (default: WARNING)"
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    try:
        # Create and run server
        server = VoiceMCPServer(
            host=args.host,
            port=args.port,
            whisper_model=args.model
        )
        server.run()

    except KeyboardInterrupt:
        console.print("\n\n👋 [cyan]Shutting down achat server...[/cyan]")
        sys.exit(0)

    except Exception as e:
        console.print(f"\n❌ [red]Error:[/red] {e}")
        logging.exception("Startup failed")
        sys.exit(1)


if __name__ == "__main__":
    main()