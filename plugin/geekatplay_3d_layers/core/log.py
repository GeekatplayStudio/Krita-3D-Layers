"""
The plugin log: <data folder>/logs/krita3d.log, rotated at 2 MB (one old copy kept).

Credentials are never logged: `redact` masks anything that looks like a key or token,
as a safety net behind the rule of never passing secrets to the logger.
"""
from __future__ import annotations

import datetime
import json
import re
import threading
from pathlib import Path
from typing import Any, List, Optional

_PATTERNS = [
    (re.compile(r"""(authorization["']?\s*[:=]\s*["']?)(bearer\s+|basic\s+)?[^"',\s}]+""", re.I), lambda m: f"{m.group(1)}{m.group(2) or ''}***"),
    (re.compile(r"\b(msy_|tsk_|sk-)[A-Za-z0-9_-]{6,}"), lambda m: f"{m.group(1)}***"),
    (re.compile(r'("(?:api_?key|apiKey|secret|secretKey|accessKey|token|access_token|accessToken)"\s*:\s*")[^"]+', re.I), lambda m: f"{m.group(1)}***"),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _stringify(data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, BaseException):
        return f" {type(data).__name__}: {data}"
    if isinstance(data, str):
        return f" {data}"
    try:
        return " " + json.dumps(data, default=str)[:4000]
    except (TypeError, ValueError):
        return f" {data!r}"[:4000]


class Logger:
    """Thread-safe file logger with an in-memory tail (shown in Settings)."""

    LEVELS = ("debug", "info", "warn", "error")

    def __init__(self, path: Optional[Path] = None, max_bytes: int = 2 * 1024 * 1024, echo: bool = False):
        self.path = path
        self.max_bytes = max_bytes
        self.echo = echo
        self.lines: List[str] = []
        self._lock = threading.Lock()
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, level: str, message: str, data: Any = None) -> None:
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        line = redact(f"{stamp} {level.upper():<5} {message}{_stringify(data)}")
        with self._lock:
            self.lines.append(line)
            del self.lines[:-500]
            if self.echo:
                print(line)
            if not self.path:
                return
            try:
                if self.path.exists() and self.path.stat().st_size > self.max_bytes:
                    old = self.path.with_suffix(".1.log")
                    if old.exists():
                        old.unlink()
                    self.path.rename(old)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass  # logging must never break the plugin

    def debug(self, message: str, data: Any = None) -> None:
        self._write("debug", message, data)

    def info(self, message: str, data: Any = None) -> None:
        self._write("info", message, data)

    def warn(self, message: str, data: Any = None) -> None:
        self._write("warn", message, data)

    def error(self, message: str, data: Any = None) -> None:
        self._write("error", message, data)

    def tail(self, n: int = 200) -> str:
        with self._lock:
            return "\n".join(self.lines[-n:])


class MemoryLogger(Logger):
    """For tests: keeps lines in memory only."""

    def __init__(self) -> None:
        super().__init__(None)
