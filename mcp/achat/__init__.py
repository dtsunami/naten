"""achat - Voice transcription MCP server for AI agents.

Like clippy but for voice input - record audio, transcribe with Whisper,
and expose via MCP protocol for remote/local AI agents.
"""

__version__ = "0.1.0"
__author__ = "da_code contributors"

from .server import VoiceMCPServer
from .voice import VoiceRecorder, WhisperTranscriber

__all__ = ["VoiceMCPServer", "VoiceRecorder", "WhisperTranscriber"]