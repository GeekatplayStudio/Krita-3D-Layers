"""
API keys, in credentials.json in the shared user-data folder.

The file is the same one the Photoshop plugin uses ({"_note": ..., "keys": {"meshy.apiKey": ...}}),
so a key entered in either plugin works in both. It is readable only by your user account
on macOS and Linux, never written to settings.json and never logged.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Dict

from .providers.base import SECRET_KEYS
from .store import read_json, write_json

CREDENTIALS_FILE = "credentials.json"
NOTE = "API keys for Geekatplay 3D Layers. Keep this file private; delete a key here or in the plugin's Settings tab."


class SecretStore:
    def __init__(self, root: Path):
        self.path = root / CREDENTIALS_FILE
        self._lock = threading.Lock()

    def _all(self) -> Dict[str, str]:
        # Read every time: the Photoshop plugin may have changed the file.
        data = read_json(self.path)
        keys = data.get("keys") if isinstance(data, dict) else None
        return {k: v for k, v in (keys or {}).items() if isinstance(v, str)}

    def get(self, key: str) -> str:
        return self._all().get(key, "")

    def set(self, key: str, value: str) -> None:
        if key not in SECRET_KEYS:
            raise ValueError(f"Unknown key {key}")
        with self._lock:
            keys = self._all()
            if value.strip():
                keys[key] = value.strip()
            else:
                keys.pop(key, None)
            write_json(self.path, {"_note": NOTE, "keys": keys})
            if sys.platform != "win32":
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass


def preview(value: str) -> str:
    """"msy_…1234": enough to recognise a key, never enough to use it."""
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    head = value[: value.find("_") + 1] if "_" in value[:6] else value[:3]
    return f"{head}…{value[-4:]}"
