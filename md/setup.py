#!/usr/bin/env python3
"""
Custom setup script to obtain or build mdserve Rust binary during pip install.

Behavior:
- Try to obtain a verified prebuilt binary from GitHub Releases (preferred).
- If not available, fall back to building from source with cargo (requires Rust toolchain).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path
from setuptools import setup
from setuptools.command.build_py import build_py

# Try to import the helper that downloads prebuilt binaries from releases.
try:
    from mdserve_wrapper.prebuilt import download_and_verify
except Exception:
    download_and_verify = None


class BuildMdserve(build_py):
    """Custom build command that obtains mdserve binary from releases or compiles it."""

    def run(self):
        """Obtain mdserve binary before running standard build."""
        build_dir = Path("build")
        bin_dir = Path("mdserve_wrapper") / "bin"

        # Create directories
        build_dir.mkdir(exist_ok=True)
        bin_dir.mkdir(parents=True, exist_ok=True)

        # If binary already present, skip
        binary_name = "mdserve.exe" if sys.platform == "win32" else "mdserve"
        expected_path = bin_dir / binary_name
        if expected_path.exists():
            print(f"ℹ️ mdserve binary already present at {expected_path}, skipping build/download")
            return super().run()

        # 1) Try prebuilt download from GitHub Releases
        try:
            if download_and_verify is not None:
                print("⬇️ Attempting to download prebuilt mdserve binary from releases...")
                downloaded = download_and_verify(bin_dir)
                if downloaded:
                    # Ensure file is named as expected
                    if downloaded.name != expected_path.name:
                        final = bin_dir / expected_path.name
                        shutil.move(str(downloaded), str(final))
                        downloaded = final
                    print(f"✅ Downloaded prebuilt mdserve to {downloaded}")
                    return super().run()
                else:
                    print("⚠️ Prebuilt binary not available or failed verification, falling back to source build...")
        except Exception as e:
            print(f"⚠️ Prebuilt download attempt failed: {e}. Falling back to source build...")

        # 2) Fallback to building from source
        mdserve_repo = build_dir / "mdserve"

        if not mdserve_repo.exists():
            print("📦 Cloning mdserve repository...")
            try:
                subprocess.run(
                    ["git", "clone", "https://github.com/jfernandez/mdserve.git", str(mdserve_repo)],
                    check=True,
                    cwd=build_dir,
                )
            except subprocess.CalledProcessError as e:
                print(f"❌ Failed to clone mdserve: {e}", file=sys.stderr)
                sys.exit(1)

        # Check if cargo is available
        import shutil as _sh

        if not _sh.which("cargo"):
            print("❌ Cargo (Rust toolchain) not found. Please install from https://rustup.rs/", file=sys.stderr)
            sys.exit(1)

        # Build mdserve
        print("🔨 Building mdserve (this may take a few minutes)...")
        try:
            subprocess.run(
                ["cargo", "build", "--release"],
                check=True,
                cwd=mdserve_repo,
            )
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to build mdserve: {e}", file=sys.stderr)
            sys.exit(1)

        # Copy binary to package
        source_binary = mdserve_repo / "target" / "release" / binary_name
        dest_binary = bin_dir / binary_name

        if source_binary.exists():
            print(f"📋 Copying binary to {dest_binary}")
            shutil.copy2(source_binary, dest_binary)
            # Make executable on Unix
            if sys.platform != "win32":
                dest_binary.chmod(0o755)
        else:
            print(f"❌ Binary not found at {source_binary}", file=sys.stderr)
            sys.exit(1)

        print("✅ mdserve built successfully!")

        # Run standard build
        super().run()


if __name__ == "__main__":
    setup(cmdclass={"build_py": BuildMdserve})
"""
Custom setup script to build mdserve Rust binary during pip install.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path
from setuptools import setup
from setuptools.command.build_py import build_py

# New: helper to download prebuilt binaries
try:
    from .mdserve_wrapper.prebuilt import download_and_verify
except Exception:
    download_and_verify = None


class BuildMdserve(build_py):
    """Custom build command that compiles mdserve from source or downloads prebuilt binaries."""

    def run(self):
        """Build or obtain mdserve binary before running standard build."""
        build_dir = Path("build")
        bin_dir = Path("mdserve_wrapper") / "bin"

        # Create directories
        build_dir.mkdir(exist_ok=True)
        bin_dir.mkdir(parents=True, exist_ok=True)

        mdserve_repo = build_dir / "mdserve"

        # Clone mdserve if not already present
        if not mdserve_repo.exists():
            print("📦 Cloning mdserve repository...")
            try:
                subprocess.run(
                    ["git", "clone", "https://github.com/jfernandez/mdserve.git", str(mdserve_repo)],
                    check=True,
                    cwd=build_dir
                )
            except subprocess.CalledProcessError as e:
                print(f"❌ Failed to clone mdserve: {e}", file=sys.stderr)
                sys.exit(1)

        # Check if cargo is available
        try:
            subprocess.run(["cargo", "--version"], check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("❌ Cargo (Rust toolchain) not found. Please install from https://rustup.rs/", file=sys.stderr)
            sys.exit(1)

        # Build mdserve
        print("🔨 Building mdserve (this may take a few minutes)...")
        try:
            subprocess.run(
                ["cargo", "build", "--release"],
                check=True,
                cwd=mdserve_repo
            )
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to build mdserve: {e}", file=sys.stderr)
            sys.exit(1)

        # Copy binary to package
        binary_name = "mdserve.exe" if sys.platform == "win32" else "mdserve"
        source_binary = mdserve_repo / "target" / "release" / binary_name
        dest_binary = bin_dir / binary_name

        if source_binary.exists():
            print(f"📋 Copying binary to {dest_binary}")
            shutil.copy2(source_binary, dest_binary)
            # Make executable on Unix
            if sys.platform != "win32":
                dest_binary.chmod(0o755)
        else:
            print(f"❌ Binary not found at {source_binary}", file=sys.stderr)
            sys.exit(1)

        print("✅ mdserve built successfully!")

        # Run standard build
        super().run()


if __name__ == "__main__":
    setup(cmdclass={"build_py": BuildMdserve})
