# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller configuration for a self-contained AniRSS desktop build."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


project_root = Path(SPECPATH).resolve()
source_root = project_root / "src"
resources_root = project_root / "resources"

datas = [
    (str(resources_root), "resources"),
    (str(project_root / "LICENSE"), "."),
]
third_party_notices = project_root / "THIRD_PARTY_NOTICES.md"
if third_party_notices.is_file():
    datas.append((str(third_party_notices), "."))

hiddenimports = ["anirss.app"]
bundle_torrent = os.environ.get("ANIRSS_BUNDLE_TORRENT") == "1"
if bundle_torrent:
    try:
        libtorrent_available = importlib.util.find_spec("libtorrent") is not None
    except (ImportError, ValueError):
        libtorrent_available = False
    if not libtorrent_available:
        raise RuntimeError(
            "ANIRSS_BUNDLE_TORRENT=1 but the libtorrent module is not installed"
        )
    # The application intentionally imports this optional engine lazily.
    hiddenimports.append("libtorrent")

if sys.platform == "win32":
    icon_candidate = resources_root / "icons" / "anirss.ico"
    version_candidate = resources_root / "windows-version-info.txt"
elif sys.platform == "darwin":
    icon_candidate = resources_root / "icons" / "anirss.icns"
    version_candidate = None
else:
    icon_candidate = resources_root / "icons" / "anirss.png"
    version_candidate = None
icon = str(icon_candidate) if icon_candidate.is_file() else None
version = (
    str(version_candidate)
    if version_candidate is not None and version_candidate.is_file()
    else None
)

analysis = Analysis(
    [str(project_root / "scripts" / "anirss_launcher.py")],
    pathex=[str(source_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "mypy",
        "ruff",
        # These Qt modules are not used by AniRSS. In particular, excluding the
        # Virtual Keyboard plugin avoids accidentally redistributing its GPL-only
        # open-source module in the otherwise MIT/LGPL application bundle.
        "PySide6.QtPdf",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtVirtualKeyboard",
        *([] if bundle_torrent else ["libtorrent"]),
    ],
    noarchive=False,
    optimize=1,
)

# Qt's platform and image-format hooks discover two optional plugins even when
# the corresponding Python modules are excluded. Remove the plugins together
# with the DLLs that are reachable only through them. This list is deliberately
# narrow so normal Qt Widgets, SVG, networking, TLS, and image support remain.
unused_qt_artifacts = {
    "qpdf.dll",
    "qt6pdf.dll",
    "qt6qml.dll",
    "qt6qmlmeta.dll",
    "qt6qmlmodels.dll",
    "qt6qmlworkerscript.dll",
    "qt6quick.dll",
    "qt6virtualkeyboard.dll",
    "qtvirtualkeyboardplugin.dll",
}


def is_used_artifact(entry):
    destination_name = entry[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
    return destination_name not in unused_qt_artifacts


analysis.binaries = [entry for entry in analysis.binaries if is_used_artifact(entry)]
analysis.datas = [entry for entry in analysis.datas if is_used_artifact(entry)]

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="AniRSS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=icon,
    version=version,
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="AniRSS",
)

if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="AniRSS.app",
        icon=icon,
        bundle_identifier="org.anirss.desktop",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
