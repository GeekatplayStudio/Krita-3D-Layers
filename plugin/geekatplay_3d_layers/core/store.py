"""
The shared user-data folder and small file helpers.

The folder is the same one the Photoshop plugin uses, so both share one model library
and one set of API keys:
  Windows  %APPDATA%\\Geekatplay\\3D Layers
  macOS    ~/Library/Application Support/Geekatplay/3D Layers
  Linux    $XDG_DATA_HOME/Geekatplay/3D Layers (~/.local/share/...)
Krita's own files (settings, jobs) are in its "krita" subfolder; the logs are in "logs".
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional


def data_root() -> Path:
    override = os.environ.get("GEEKATPLAY_3D_DATA")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "Geekatplay" / "3D Layers"


def read_json(path: Path) -> Optional[Any]:
    """Parsed JSON, or None when the file is missing or damaged."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_bytes(path: Path, data: bytes) -> None:
    """Writes through a temporary file and a rename, so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                # Windows: another process (the Photoshop plugin, an antivirus) has the file open.
                time.sleep(0.05 * (attempt + 1))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_json(path: Path, data: Any) -> None:
    write_bytes(path, json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))


def new_id(prefix: str) -> str:
    """Same shape as the Photoshop plugin's ids: <prefix>_<time base36><6 random base36>."""

    def b36(n: int) -> str:
        chars = "0123456789abcdefghijklmnopqrstuvwxyz"
        out = ""
        while True:
            n, r = divmod(n, 36)
            out = chars[r] + out
            if n == 0:
                return out

    return f"{prefix}_{b36(int(time.time() * 1000))}{b36(random.randrange(36**6)).rjust(6, '0')}"


def slug(text: str, fallback: str = "model") -> str:
    """Safe file-name stem from arbitrary text."""
    s = unicodedata.normalize("NFKD", text)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()[:48]
    return s or fallback


def sniff_format(data: bytes) -> Optional[str]:
    """"glb" | "gltf" | "png" | "jpg" | "webp" | "zip" | None, from the first bytes."""
    if data[:4] == b"glTF":
        return "glb"
    if data[:4] == b"\x89PNG":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:10] == b"WE":
        return "webp"
    if data[:4] == b"PK\x03\x04":
        return "zip"
    for c in data[:16]:
        if c == 0x7B:
            return "gltf"
        if c not in (0x20, 0x0A, 0x0D, 0x09, 0xEF, 0xBB, 0xBF):
            break
    return None
