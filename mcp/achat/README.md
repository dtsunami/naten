# 🎤 achat - Voice MCP Server

**Like clippy but for voice input!** Record audio on your local machine, transcribe with Whisper, and expose as MCP tools for remote/local AI agents.

## 🌟 Features

- **🎤 Local Voice Recording** - Capture audio from your microphone
- **🔄 Whisper Transcription** - Fast, accurate speech-to-text (runs locally!)
- **🌐 MCP Protocol** - Works with any MCP-compatible agent (like da_code)
- **📋 Auto-Copy Connection** - Clippy-style clipboard integration
- **🔒 SSH-Friendly** - Works over SSH tunnel for remote agents
- **⚡ Fast** - Local processing, no cloud API calls

## 🚀 Quick Start

### Installation

```bash
# Install achat
cd achat
pip install -e .

# Or with development dependencies
pip install -e ".[dev]"
```

### Usage

```bash
# 1. Start achat on your local machine (laptop/workstation)
$ achat

🎤 achat voice server v0.1.0

Status: Running on http://0.0.0.0:8765
Local IP: 192.168.1.100

✅ Copied to clipboard!

For Local Agent:
add_mcp {"name":"voice","url":"http://localhost:8765"}

For Remote Agent (over SSH):
add_mcp {"name":"voice","url":"http://192.168.1.100:8765"}

🎤 Ready to receive voice transcription requests!


# 2. In your da_code agent (local or remote via SSH)
agent! add_mcp {"name":"voice","url":"http://localhost:8765"}
✅ MCP server 'voice' added successfully
🎤 Voice tools available: voice_transcribe, voice_quick_record


# 3. Use voice input!
agent! "get my next instruction via voice"

🔧 Calling voice_transcribe()...
[on laptop: 🔴 Recording for 10s... speak now]
[on laptop: ✅ Transcribed: "fix the authentication bug"]

✅ Agent received: "fix the authentication bug"
```

## 🛠️ Configuration

### Command Line Options

```bash
achat --help

Options:
  --host HOST          Host to bind to (default: 0.0.0.0)
  --port PORT          Port to bind to (default: 8765)
  --model MODEL        Whisper model: tiny, base, small, medium, large
                       (default: base)
  --log-level LEVEL    Logging level (default: WARNING)
```

### Examples

```bash
# Better accuracy (slower, uses ~500MB RAM)
achat --model small

# Custom port
achat --port 9000

# Debug mode
achat --log-level DEBUG

# Alternative command name
da_chat --model base
```

## 🎯 MCP Tools Exposed

### `voice_transcribe`

Record audio and transcribe to text.

**Parameters:**
- `duration` (float): Recording duration in seconds (1-60, default: 10)
- `language` (string, optional): Language code (e.g., 'en', 'es')

**Returns:**
- `text` (string): Transcribed text
- `language` (string): Detected/specified language
- `success` (bool): Whether transcription succeeded
- `error` (string, optional): Error message if failed

**Example:**
```python
# Agent can call:
result = voice_transcribe(duration=15, language="en")
# User speaks for 15 seconds
# Returns: {"text": "fix the bug...", "language": "en", "success": true}
```

### `voice_quick_record`

Quick 5-second recording for short prompts.

**Parameters:** None

**Returns:** Same as `voice_transcribe`

**Example:**
```python
# Agent can call:
result = voice_quick_record()
# User speaks for 5 seconds
# Returns: {"text": "run tests", "language": "en", "success": true}
```

## 🌐 Remote Setup (SSH)

When your agent runs on a remote server:

```bash
# Option 1: Direct connection (if firewall allows)
laptop$ achat
agent! add_mcp {"name":"voice","url":"http://192.168.1.100:8765"}

# Option 2: SSH tunnel (more secure)
laptop$ achat
laptop$ ssh -R 8765:localhost:8765 user@remote-server

remote$ da_code
agent! add_mcp {"name":"voice","url":"http://localhost:8765"}
```

## 🎨 Integration Examples

### Basic Voice Prompt

```python
# Agent behavior:
"get next instruction via voice"
→ calls voice_transcribe(duration=10)
→ receives text
→ processes as normal prompt
```

### Long-Form Input

```python
# For complex multi-line prompts:
"use voice input for my detailed requirements"
→ calls voice_transcribe(duration=30)
→ user speaks naturally for 30 seconds
→ agent receives full transcription
```

### Multi-Language

```python
# Specify language:
"get Spanish instructions via voice"
→ calls voice_transcribe(duration=10, language="es")
→ optimizes transcription for Spanish
```

## 🔧 Whisper Models

| Model | Size | RAM | Speed | Accuracy |
|-------|------|-----|-------|----------|
| tiny | 39M | ~150MB | Fast | Good |
| base | 74M | ~200MB | Fast | Better |
| small | 244M | ~500MB | Medium | Great |
| medium | 769M | ~1.5GB | Slow | Excellent |
| large | 1550M | ~3GB | Very Slow | Best |

**Recommendation:** Start with `base` (default), upgrade to `small` if accuracy matters.

## 🐛 Troubleshooting

### Microphone not working

```bash
# List available audio devices
python -c "import sounddevice as sd; print(sd.query_devices())"

# Test recording
python -c "import sounddevice as sd; import numpy as np; sd.rec(48000, samplerate=16000, channels=1)"
```

### Clipboard auto-copy fails

No problem! Just manually copy the connection command from terminal output.

### Connection refused from remote agent

Check firewall:
```bash
# Allow port (Linux)
sudo ufw allow 8765

# Or use SSH tunnel (more secure)
ssh -R 8765:localhost:8765 user@remote
```

## 📊 Performance

- **Whisper base model**: ~1-2s transcription for 10s audio (CPU)
- **Network latency**: <100ms (local network)
- **Total time**: ~3-5s for record → transcribe → send

**Still 5-10x faster than typing complex prompts!** 🚀

## 🤝 Contributing

achat follows the same patterns as da_code:
1. Fork the repo
2. Create feature branch
3. Add tests
4. Submit PR

## 📝 License

MIT License - see LICENSE file

## 🆘 Support

Issues? Check:
1. Microphone permissions
2. Firewall/network connectivity
3. Whisper model downloaded correctly

Open issue at: [GitHub repo]

---

**🎤 Happy voice coding with achat!**