"""
Test helpers: a scripted HTTP transport, a provider context and small fixtures
(the Python twin of the Photoshop plugin's tests/unit/helpers.ts).
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Pattern, Union

from geekatplay_3d_layers.core.http import Http, Request, Response
from geekatplay_3d_layers.core.log import MemoryLogger
from geekatplay_3d_layers.core.providers.base import ProviderContext
from geekatplay_3d_layers.core.settings import DEFAULT_SETTINGS, merge


def json_response(body: Any, status: int = 200, headers: Optional[Dict[str, str]] = None) -> Response:
    text = body if isinstance(body, str) else json.dumps(body)
    h = {"content-type": "application/json"}
    h.update({k.lower(): v for k, v in (headers or {}).items()})
    return Response(status, h, text.encode("utf-8"))


def bytes_response(data: bytes, status: int = 200) -> Response:
    return Response(status, {}, data)


@dataclass
class Call:
    url: str
    method: str
    headers: Dict[str, str]  # lower-case names
    body: Optional[bytes]

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8")) if self.body else None


Reply = Union[Response, Callable[[Call], Response]]


@dataclass
class Route:
    method: str
    test: Union[str, Pattern[str]]
    reply: Reply
    #: Answer at most this many times (None = always); later routes take over after.
    times: Optional[int] = None
    used: int = 0

    def matches(self, url: str, method: str) -> bool:
        if method != self.method or (self.times is not None and self.used >= self.times):
            return False
        return url == self.test if isinstance(self.test, str) else self.test.search(url) is not None


def route(method: str, test: Union[str, Pattern[str]], reply: Reply, times: Optional[int] = None) -> Route:
    return Route(method.upper(), test, reply, times)


class ScriptedTransport:
    """Answers from `routes` (first match wins) and records every call."""

    def __init__(self, routes: List[Route]):
        self.routes = routes
        self.calls: List[Call] = []

    def __call__(self, req: Request) -> Response:
        call = Call(req.url, req.method.upper(), {k.lower(): v for k, v in req.headers.items()}, req.body)
        self.calls.append(call)
        for r in self.routes:
            if r.matches(req.url, call.method):
                r.used += 1
                return r.reply(call) if callable(r.reply) else r.reply
        raise AssertionError(f"No route for {call.method} {req.url}")


def context(transport: ScriptedTransport, patch: Optional[Dict[str, Any]] = None, secrets: Optional[Dict[str, str]] = None, now: float = 1_790_000_000_000) -> ProviderContext:
    log = MemoryLogger()
    keys = dict(secrets or {})
    return ProviderContext(http=Http(transport, log), settings=merge(DEFAULT_SETTINGS, patch or {}), secret=lambda k: keys.get(k, ""), log=log, now=lambda: now)


def parse_multipart(body: bytes, content_type: str) -> Dict[str, Dict[str, Any]]:
    """Decodes a body built by core.http.multipart into {"fields": {...}, "files": {name: {"filename", "bytes"}}}."""
    boundary = re.search(r"boundary=(.+)$", content_type).group(1)  # type: ignore[union-attr]
    text = body.decode("latin1")
    fields: Dict[str, str] = {}
    files: Dict[str, Dict[str, Any]] = {}
    for part in text.split(f"--{boundary}")[1:-1]:
        head, _, content = part.partition("\r\n\r\n")
        content = content[:-2] if content.endswith("\r\n") else content
        name = re.search(r'name="([^"]+)"', head).group(1)  # type: ignore[union-attr]
        filename = re.search(r'filename="([^"]*)"', head)
        if filename:
            files[name] = {"filename": filename.group(1), "bytes": content.encode("latin1")}
        else:
            fields[name] = content.encode("latin1").decode("utf-8")
    return {"fields": fields, "files": files}


def fake_glb(size: int = 64) -> bytes:
    """Smallest valid GLB header (enough for format sniffing)."""
    b = bytearray(size)
    b[0:8] = bytes([0x67, 0x6C, 0x54, 0x46, 2, 0, 0, 0])
    return bytes(b)


PNG_1PX = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
