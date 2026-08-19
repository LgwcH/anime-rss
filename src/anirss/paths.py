"""Platform-aware paths used by the desktop application.

All paths can be overridden for development and portable builds.  Keeping this
logic outside the UI also makes the core straightforward to test.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "AniRSS"


def app_data_dir(override: str | os.PathLike[str] | None = None) -> Path:
    """Return the writable per-user data directory and create it if needed."""

    if override:
        path = Path(override).expanduser()
    elif portable_root := os.environ.get("ANIRSS_PORTABLE_DIR"):
        path = Path(portable_root).expanduser()
    elif sys.platform == "win32":
        path = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        path = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "anirss"

    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def default_download_dir() -> Path:
    """Return the default root for per-show download folders."""

    configured = os.environ.get("ANIRSS_DOWNLOAD_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / "Downloads" / APP_NAME).resolve()


def resource_path(relative: str) -> Path:
    """Resolve an application resource in source and PyInstaller builds."""

    bundle_root = getattr(sys, "_MEIPASS", None)
    # Repository resources live beside ``src`` while a PyInstaller build puts
    # them directly below its temporary bundle root.
    if bundle_root:
        return Path(bundle_root) / relative
    repository_candidate = Path(__file__).resolve().parents[2] / relative
    if repository_candidate.exists():
        return repository_candidate
    return Path(__file__).resolve().parent / relative
