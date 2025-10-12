"""Voice recording and transcription functionality."""

import logging
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Optional, List

import numpy as np
import sounddevice as sd
import whisper
from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()


class VoiceRecorder:
    """Records audio from microphone."""

    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        """Initialize voice recorder.

        Args:
            sample_rate: Audio sample rate (Whisper uses 16kHz)
            channels: Number of audio channels (1 = mono)
        """
        self.sample_rate = sample_rate
        self.channels = channels

    def record(self, duration: float = 10.0) -> np.ndarray:
        """Record audio from microphone.

        Args:
            duration: Recording duration in seconds

        Returns:
            Audio data as numpy array
        """
        console.print(f"🔴 [red]Recording for {duration}s...[/red] (speak now)")

        try:
            # Record audio
            audio = sd.rec(
                int(duration * self.sample_rate),
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=np.float32
            )
            sd.wait()  # Wait for recording to complete

            console.print("✅ [green]Recording complete[/green]")
            return audio.flatten()

        except Exception as e:
            logger.error(f"Recording failed: {e}")
            console.print(f"❌ [red]Recording failed: {e}[/red]")
            raise


class WhisperTranscriber:
    """Transcribes audio using OpenAI Whisper."""

    def __init__(self, model_name: str = "base"):
        """Initialize Whisper transcriber.

        Args:
            model_name: Whisper model size (tiny, base, small, medium, large)
        """
        console.print(f"🔄 Loading Whisper '{model_name}' model...")
        self.model = whisper.load_model(model_name)
        console.print(f"✅ Whisper model loaded")
        self.sample_rate = 16000

    def transcribe(self, audio: np.ndarray, language: Optional[str] = None) -> dict:
        """Transcribe audio to text.

        Args:
            audio: Audio data as numpy array
            language: Optional language code (e.g., 'en', 'es')

        Returns:
            Dict with 'text' and 'language' keys
        """
        console.print("🔄 [yellow]Transcribing...[/yellow]")

        try:
            # Pass audio data directly to Whisper (no temp file needed!)
            # Whisper can accept numpy arrays directly
            kwargs = {"language": language} if language else {}

            # Ensure audio is float32 and in the right format
            audio_float32 = audio.astype(np.float32)

            result = self.model.transcribe(audio_float32, **kwargs)

            text = result["text"].strip()
            detected_language = result.get("language", "unknown")

            console.print(f"✅ [green]Transcribed:[/green] [cyan]{text}[/cyan]")
            if not language:
                console.print(f"   Language detected: {detected_language}")

            return {
                "text": text,
                "language": detected_language,
                "success": True
            }

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            console.print(f"❌ [red]Transcription failed: {e}[/red]")
            return {
                "text": "",
                "language": "unknown",
                "success": False,
                "error": str(e)
            }


class StreamingRecordingSession:
    """Manages a streaming voice recording session with VAD and chunked transcription."""

    def __init__(self, session_id: str, transcriber: WhisperTranscriber, chunk_duration: float = 3.0, max_duration: float = 25.0, silence_threshold: float = 2.0):
        """Initialize streaming session.

        Args:
            session_id: Unique session identifier
            transcriber: WhisperTranscriber instance
            chunk_duration: Duration of each transcription chunk in seconds
            max_duration: Maximum total recording duration in seconds
            silence_threshold: Seconds of silence before auto-stopping
        """
        self.session_id = session_id
        self.transcriber = transcriber
        self.chunk_duration = chunk_duration
        self.max_duration = max_duration
        self.silence_threshold = silence_threshold

        self.sample_rate = 16000
        self.is_recording = False
        self.is_stopped = False
        self.audio_chunks: List[np.ndarray] = []
        self.transcribed_chunks: List[str] = []
        self.last_chunk_index = 0  # Track which chunks have been retrieved
        self.recording_thread = None
        self.start_time = None
        self.lock = threading.Lock()

    def _detect_silence(self, audio: np.ndarray) -> bool:
        """Simple energy-based voice activity detection.

        Args:
            audio: Audio chunk to analyze

        Returns:
            True if audio is silent, False if voice detected
        """
        # Calculate RMS energy
        energy = np.sqrt(np.mean(audio ** 2))

        # Silence threshold (tuned for typical speech)
        # Values below 0.01 are usually silence
        threshold = 0.01

        return energy < threshold

    def _recording_loop(self):
        """Background thread that continuously records audio in chunks."""
        console.print("🔴 [red]Recording started...[/red] (streaming mode)")
        self.start_time = time.time()

        try:
            silence_start = None

            while self.is_recording:
                # Check max duration
                elapsed = time.time() - self.start_time
                if elapsed >= self.max_duration:
                    console.print(f"⏱️  [yellow]Max duration ({self.max_duration}s) reached[/yellow]")
                    break

                # Record chunk
                chunk_samples = int(self.chunk_duration * self.sample_rate)
                audio_chunk = sd.rec(
                    chunk_samples,
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype=np.float32
                )
                sd.wait()
                audio_chunk = audio_chunk.flatten()

                # VAD: Check for silence
                is_silent = self._detect_silence(audio_chunk)

                if is_silent:
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start >= self.silence_threshold:
                        console.print("🔇 [green]Silence detected - stopping[/green]")
                        break
                else:
                    # Reset silence timer when voice detected
                    silence_start = None

                # Store chunk
                with self.lock:
                    self.audio_chunks.append(audio_chunk)

                # Transcribe chunk immediately
                self._transcribe_latest_chunk()

        except Exception as e:
            logger.error(f"Recording loop error: {e}")
            console.print(f"❌ [red]Recording error: {e}[/red]")
        finally:
            self.is_recording = False
            self.is_stopped = True
            console.print("✅ [green]Recording complete[/green]")

    def _transcribe_latest_chunk(self):
        """Transcribe the latest audio chunk."""
        with self.lock:
            if not self.audio_chunks:
                return

            # Get latest chunk
            latest_chunk = self.audio_chunks[-1]

        try:
            # Transcribe (without console output to avoid spam)
            result = self.transcriber.transcribe(latest_chunk, language=None)

            if result.get("success") and result.get("text"):
                with self.lock:
                    self.transcribed_chunks.append(result["text"])
                    logger.info(f"Chunk transcribed: {result['text'][:50]}...")

        except Exception as e:
            logger.error(f"Chunk transcription error: {e}")

    def start(self):
        """Start recording in background thread."""
        if self.is_recording:
            return

        self.is_recording = True
        self.recording_thread = threading.Thread(target=self._recording_loop, daemon=True)
        self.recording_thread.start()

    def stop(self):
        """Stop recording."""
        self.is_recording = False
        if self.recording_thread:
            self.recording_thread.join(timeout=2.0)
        self.is_stopped = True

    def get_new_chunks(self) -> List[str]:
        """Get new transcribed chunks since last call.

        Returns:
            List of new transcript chunks
        """
        with self.lock:
            new_chunks = self.transcribed_chunks[self.last_chunk_index:]
            self.last_chunk_index = len(self.transcribed_chunks)
            return new_chunks

    def is_complete(self) -> bool:
        """Check if recording session is complete."""
        return self.is_stopped