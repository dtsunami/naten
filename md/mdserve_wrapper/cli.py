#!/usr/bin/env python3
"""
CLI entry points for mdserve-wrapper.
"""
import argparse
import sys
from pathlib import Path
from typing import List
from . import MarkdownServer


def find_markdown_files(directory: Path = None) -> List[Path]:
    """
    Find all markdown files in a directory recursively.

    Args:
        directory: Directory to search (default: current directory)

    Returns:
        List of markdown file paths
    """
    if directory is None:
        directory = Path.cwd()

    markdown_files = []
    for pattern in ["**/*.md", "**/*.markdown"]:
        markdown_files.extend(directory.glob(pattern))

    return sorted(set(markdown_files))


def main():
    """
    Main CLI entry point - serve a single markdown file.

    Usage:
        mdserve README.md
        mdserve README.md --port 8080
        mdserve README.md --theme mocha
    """
    parser = argparse.ArgumentParser(
        description="Fast markdown preview server with live reload"
    )
    parser.add_argument("file", help="Markdown file to serve")
    parser.add_argument("--port", "-p", type=int, help="Port to serve on (default: 3000)")
    parser.add_argument("--host", help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument(
        "--theme",
        "-t",
        choices=["latte", "frappe", "macchiato", "mocha"],
        help="Catppuccin color theme"
    )

    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"❌ File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    try:
        server = MarkdownServer()
        print(f"🚀 Serving {file_path} at http://{args.host or '127.0.0.1'}:{args.port or 3000}")
        print("Press Ctrl+C to stop...")
        server.serve_blocking(
            file_path,
            port=args.port,
            host=args.host,
            theme=args.theme
        )
    except FileNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


def serve_all():
    """
    Serve all markdown files in the current project.

    Usage:
        mdserve-all
        mdserve-all --port 8080
        mdserve-all --directory /path/to/project
    """
    parser = argparse.ArgumentParser(
        description="Serve all markdown files from a project directory"
    )
    parser.add_argument(
        "--directory",
        "-d",
        type=Path,
        default=Path.cwd(),
        help="Project directory to search (default: current directory)"
    )
    parser.add_argument("--port", "-p", type=int, default=3000, help="Starting port (default: 3000)")
    parser.add_argument("--host", help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument(
        "--theme",
        "-t",
        choices=["latte", "frappe", "macchiato", "mocha"],
        help="Catppuccin color theme"
    )
    parser.add_argument(
        "--select",
        "-s",
        action="store_true",
        help="Interactively select which files to serve"
    )

    args = parser.parse_args()

    # Find all markdown files
    print(f"🔍 Searching for markdown files in {args.directory}...")
    markdown_files = find_markdown_files(args.directory)

    if not markdown_files:
        print("❌ No markdown files found.", file=sys.stderr)
        sys.exit(1)

    print(f"📝 Found {len(markdown_files)} markdown file(s):\n")
    for i, file in enumerate(markdown_files, 1):
        rel_path = file.relative_to(args.directory) if file.is_relative_to(args.directory) else file
        print(f"  {i}. {rel_path}")
    print()

    # Interactive selection
    if args.select:
        selected = []
        print("Enter file numbers to serve (comma-separated, or 'all'):")
        choice = input("> ").strip().lower()

        if choice == "all":
            selected = markdown_files
        else:
            try:
                indices = [int(x.strip()) - 1 for x in choice.split(",")]
                selected = [markdown_files[i] for i in indices if 0 <= i < len(markdown_files)]
            except (ValueError, IndexError):
                print("❌ Invalid selection", file=sys.stderr)
                sys.exit(1)

        if not selected:
            print("❌ No files selected", file=sys.stderr)
            sys.exit(1)

        markdown_files = selected

    # Start servers
    try:
        server = MarkdownServer()
        processes = []

        print(f"\n🚀 Starting servers...\n")
        for i, file in enumerate(markdown_files):
            port = args.port + i
            rel_path = file.relative_to(args.directory) if file.is_relative_to(args.directory) else file

            process = server.serve(
                file,
                port=port,
                host=args.host,
                theme=args.theme
            )
            processes.append((file, port, process))
            print(f"  ✅ {rel_path}")
            print(f"     → http://{args.host or '127.0.0.1'}:{port}\n")

        print(f"🎉 Serving {len(processes)} file(s). Press Ctrl+C to stop all servers...\n")

        # Wait for all processes
        try:
            for _, _, process in processes:
                process.wait()
        except KeyboardInterrupt:
            print("\n\n🛑 Stopping all servers...")
            for file, port, process in processes:
                process.terminate()
            for _, _, process in processes:
                process.wait()
            print("✅ All servers stopped")

    except FileNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    serve_all()
