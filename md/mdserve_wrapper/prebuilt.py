"""
Helpers to download and verify prebuilt mdserve binaries from GitHub Releases.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Optional

try:
    from urllib.request import Request, urlopen
except Exception:
    Request = None
    urlopen = None

GITHUB_REPO = os.environ.get("MDERVE_GITHUB_REPO", "jfernandez/mdserve")
GITHUB_RELEASE = os.environ.get("MDERVE_RELEASE", "latest")


def _read_os_release() -> dict:
    data = {}
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    data[k] = v.strip('"')
    except FileNotFoundError:
        pass
    return data


def detect_platform() -> tuple[str, str]:
    """Return (platform_key, arch) platform_key in ("windows", "suse15", "linux")"""
    arch = os.environ.get("MDERVE_ARCH") or ("x86_64" if sys.maxsize > 2**32 else "x86")
    if sys.platform == "win32":
        return "windows", arch
    if sys.platform.startswith("linux"):
        os_rel = _read_os_release()
        name = os_rel.get("NAME", "").lower()
        version = os_rel.get("VERSION_ID", "")
        if "suse" in name or "opensuse" in name or "sles" in name or version.startswith("15"):
            return "suse15", arch
        return "linux", arch
    return (sys.platform, arch)


def _asset_name_for(platform_key: str, arch: str) -> str:
    if platform_key == "windows":
        return f"mdserve-windows-{arch}.exe"
    if platform_key == "suse15":
        return f"mdserve-suse15-{arch}"
    return f"mdserve-linux-{arch}"


def _github_release_api_url(tag: str) -> str:
    if tag == "latest":
        return f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    return f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{tag}"


def _download_url(url: str, dest: Path) -> None:
    req = Request(url, headers={"User-Agent": "mdserve-wrapper/1.0"})
    with urlopen(req) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def download_and_verify(dest_dir: Path) -> Optional[Path]:
    """Download platform-specific prebuilt binary from GitHub Releases and verify sha256.

    Returns path to downloaded binary on success, or None on failure.
    """
    platform_key, arch = detect_platform()
    asset_name = _asset_name_for(platform_key, arch)
    checksum_name = asset_name + ".sha256"

    api_url = _github_release_api_url(GITHUB_RELEASE)
    try:
        req = Request(api_url, headers={"User-Agent": "mdserve-wrapper/1.0"})
        with urlopen(req) as resp:
            release = json.load(resp)
    except Exception:
        return None

    assets = {a["name"]: a for a in release.get("assets", [])}
    if asset_name not in assets:
        return None

    asset = assets[asset_name]
    checksum_asset = assets.get(checksum_name)

    # Download binary
    bin_dest = dest_dir / asset_name
    if not dest_dir.exists():
        dest_dir.mkdir(parents=True, exist_ok=True)

    download_url = asset.get("browser_download_url")
    try:
        _download_url(download_url, bin_dest)
    except Exception:
        return None

    # Download checksum and verify if available
    if checksum_asset:
        checksum_dest = dest_dir / checksum_name
        try:
            _download_url(checksum_asset.get("browser_download_url"), checksum_dest)
            expected = checksum_dest.read_text(encoding="utf-8").split()[0]
            actual = _sha256_of_file(bin_dest)
            if expected != actual:
                bin_dest.unlink(missing_ok=True)
                return None
        except Exception:
            bin_dest.unlink(missing_ok=True)
            return None

    # Make executable on unix
    if sys.platform != "win32":
        bin_dest.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)

    return bin_dest