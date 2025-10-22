# Installation Guide

## Quick Start

### 1. Install Rust (if not already installed)

**Windows:**
```bash
# Download and run installer from:
https://rustup.rs/
```

**Linux/macOS:**
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
```

Verify installation:
```bash
cargo --version
```

### 2. Install the package

```bash
cd md/
pip install -e .
```

This will:
- Clone mdserve from GitHub
- Compile the Rust binary (~2-5 minutes)
- Install Python wrapper
- Add `mdserve` and `mdserve-all` commands

### 3. Test it!

```bash
# Serve a single file
mdserve ../README.md

# Serve ALL markdown files in your project
mdserve-all --directory ..
```

## Usage Examples

### Serve all markdown files from naten project

```bash
cd F:/naten
mdserve-all
```

Output:
```
🔍 Searching for markdown files in F:\naten...
📝 Found 5 markdown file(s):

  1. README.md
  2. AGENTS.md
  3. CONTEXT_OVERLAY_NEXT_STEPS.md
  4. todo.md
  5. md/README.md

🚀 Starting servers...

  ✅ README.md → http://127.0.0.1:3000
  ✅ AGENTS.md → http://127.0.0.1:3001
  ✅ CONTEXT_OVERLAY_NEXT_STEPS.md → http://127.0.0.1:3002
  ✅ todo.md → http://127.0.0.1:3003
  ✅ md/README.md → http://127.0.0.1:3004

🎉 Serving 5 file(s). Press Ctrl+C to stop all servers...
```

### Interactive selection

```bash
mdserve-all --select

# Choose which files to serve:
# Enter file numbers to serve (comma-separated, or 'all'):
> 1,2,5
```

### Custom port range

```bash
mdserve-all --port 8000
# Files will be served on 8000, 8001, 8002, etc.
```

## Python API

```python
from mdserve_wrapper import MarkdownServer

server = MarkdownServer()

# Serve README
process = server.serve("README.md", port=3000, theme="mocha")

# Stop when done
process.terminate()
```

## Themes

Available Catppuccin themes:
- `--theme latte` (light)
- `--theme frappe` (dark)
- `--theme macchiato` (dark)
- `--theme mocha` (dark, warmest)

## Troubleshooting

**Build fails:**
```bash
# Update Rust
rustup update

# Clean and retry
cd md/
rm -rf build/
pip uninstall mdserve-wrapper
pip install -e .
```

**Binary not found after install:**
```bash
# Check if binary was compiled
ls md/mdserve_wrapper/bin/

# Should show: mdserve.exe (Windows) or mdserve (Linux/macOS)
```
