# mdserve-wrapper

Python wrapper for [mdserve](https://github.com/jfernandez/mdserve) - a fast markdown preview server with live reload written in Rust.

## Features

- **Fast Live Reload**: WebSocket-based instant updates
- **Catppuccin Themes**: Beautiful color schemes
- **Single or Multiple Files**: Serve one file or all markdown files in your project
- **Python Integration**: Use as a library or CLI tool

## Prerequisites

- Python 3.10+
- Rust toolchain (cargo) - Install from https://rustup.rs/
- Git

## Installation

```bash
cd md/
pip install -e .
```

This will:
1. Clone the mdserve repository
2. Compile the Rust binary
3. Install the Python wrapper
4. Add CLI commands to your PATH

## Usage

### CLI - Single File

```bash
# Serve a single markdown file
mdserve README.md

# Custom port
mdserve README.md --port 8080

# Custom theme
mdserve README.md --theme mocha
```

### CLI - All Project Files

```bash
# Serve all markdown files in current directory
mdserve-all

# Serve from specific directory
mdserve-all --directory /path/to/project

# Interactive selection
mdserve-all --select

# Custom starting port (each file gets port+1, port+2, etc.)
mdserve-all --port 8000
```

**Example output:**
```
🔍 Searching for markdown files in F:\naten...
📝 Found 5 markdown file(s):

  1. README.md
  2. AGENTS.md
  3. CONTEXT_OVERLAY_NEXT_STEPS.md
  4. todo.md
  5. md/README.md

🚀 Starting servers...

  ✅ README.md
     → http://127.0.0.1:3000

  ✅ AGENTS.md
     → http://127.0.0.1:3001

  ✅ CONTEXT_OVERLAY_NEXT_STEPS.md
     → http://127.0.0.1:3002

  ✅ todo.md
     → http://127.0.0.1:3003

  ✅ md/README.md
     → http://127.0.0.1:3004

🎉 Serving 5 file(s). Press Ctrl+C to stop all servers...
```

### Python API

```python
from mdserve_wrapper import MarkdownServer

server = MarkdownServer()

# Non-blocking
process = server.serve("README.md", port=8080, theme="mocha")
# ... do other work ...
process.terminate()

# Blocking (Ctrl+C to stop)
server.serve_blocking("README.md")
```

## Available Themes

- `latte` - Light theme
- `frappe` - Dark theme
- `macchiato` - Dark theme
- `mocha` - Dark theme (warmest)

## How It Works

1. **Build Time**: During `pip install`, the setup.py script:
   - Clones mdserve from GitHub
   - Compiles it using cargo
   - Copies the binary to `mdserve_wrapper/bin/`

2. **Runtime**: The Python wrapper:
   - Locates the compiled binary
   - Spawns it as a subprocess
   - Manages multiple instances for `mdserve-all`

## Troubleshooting

### "Cargo not found"

Install Rust:
```bash
# Windows
# Download from: https://rustup.rs/

# Linux/macOS
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

### "Binary not found"

Reinstall the package:
```bash
cd md/
pip uninstall mdserve-wrapper
pip install -e .
```

### Build fails

Check Rust toolchain:
```bash
cargo --version
rustc --version
```

## Development

```bash
# Install in editable mode
pip install -e .

# Run tests (if you add them)
pytest
```

## Credits

- **mdserve**: https://github.com/jfernandez/mdserve by @jfernandez
- **Catppuccin themes**: https://github.com/catppuccin/catppuccin
