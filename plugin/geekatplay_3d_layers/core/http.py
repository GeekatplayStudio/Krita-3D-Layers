"""
HTTP for the 3D services, on Python's standard library (Krita ships no `requests`).

Calls are synchronous: the job manager runs them on worker threads, never on Krita's UI
thread. Errors carry the service's own message so the panel can show something useful,
and every request is logged without credentials. The transport is injectable, so the
providers are tested against scripted responses (tests/test_providers_*.py).
"""
from __future__ import annotations

import email.utils
import json
import ssl
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import urlsplit


@dataclass
class Request:
    method: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[bytes] = None
    timeout: float = 60.0


@dataclass
class Response:
    status: int
    headers: Dict[str, str] = field(default_factory=dict)  # lower-case names
    body: bytes = b""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text()) if self.body else None


Transport = Callable[[Request], Response]


class HttpError(Exception):
    """The service answered with an error status."""

    def __init__(self, message: str, status: int, body: Any = None, url: str = "", retry_after_ms: Optional[float] = None):
        super().__init__(message)
        self.status = status
        self.body = body
        self.url = url
        #: How long the service asked us to wait (Retry-After / X-RateLimit-Reset), if it said.
        self.retry_after_ms = retry_after_ms


class NetworkError(Exception):
    """The service could not be reached (DNS, refused connection, timeout, TLS)."""


_ssl_context: Optional[ssl.SSLContext] = None


def _context() -> ssl.SSLContext:
    global _ssl_context
    if _ssl_context is None:
        # Uses the operating system's certificate store (Windows/macOS), like a browser.
        _ssl_context = ssl.create_default_context()
    return _ssl_context


def urllib_transport(req: Request) -> Response:
    """The real network transport."""
    r = urllib.request.Request(req.url, data=req.body, method=req.method, headers=req.headers)
    try:
        handler = urllib.request.urlopen(r, timeout=req.timeout, context=_context() if req.url.startswith("https") else None)
        with handler as res:
            return Response(res.status, {k.lower(): v for k, v in res.headers.items()}, res.read())
    except urllib.error.HTTPError as err:
        try:
            body = err.read()
        except Exception:  # noqa: BLE001 - the body is optional
            body = b""
        return Response(err.code, {k.lower(): v for k, v in (err.headers or {}).items()}, body)


def retry_after_ms(headers: Dict[str, str], now_ms: Optional[float] = None) -> Optional[float]:
    """Milliseconds the service asked us to wait (`Retry-After` seconds or date, or `X-RateLimit-Reset`)."""
    now_ms = time.time() * 1000 if now_ms is None else now_ms
    value = headers.get("retry-after")
    if value:
        try:
            return max(0.0, float(value) * 1000)
        except ValueError:
            parsed = email.utils.parsedate_to_datetime(value) if value else None
            if parsed is not None:
                return max(0.0, parsed.timestamp() * 1000 - now_ms)
    reset = headers.get("x-ratelimit-reset")
    if reset:
        try:
            n = float(reset)
        except ValueError:
            return None
        if n > 1e12:
            return max(0.0, n - now_ms)
        if n > 1e9:
            return max(0.0, n * 1000 - now_ms)
        return max(0.0, n * 1000)
    return None


def error_message_from(body: Any) -> Optional[str]:
    """A human message from typical API error bodies."""
    if not body:
        return None
    if isinstance(body, str):
        return body.strip()[:300] or None
    if not isinstance(body, dict):
        return None

    def pick(v: Any) -> Optional[str]:
        return v.strip() if isinstance(v, str) and v.strip() else None

    nested = body.get("error") if isinstance(body.get("error"), dict) else {}
    return pick(body.get("message")) or pick(body.get("msg")) or pick(nested.get("message")) or pick(body.get("error")) or pick(body.get("detail")) or pick(body.get("suggestion"))


def error_extras(body: Any, shown: Optional[str], status: int) -> str:
    """The service's error code, suggestion and request id (Tripo sends all three)."""
    if not isinstance(body, dict):
        return ""

    def text(v: Any) -> Optional[str]:
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
        return None

    suggestion = text(body.get("suggestion"))
    code = text(body.get("code"))
    request_id = text(body.get("request_id")) or text(body.get("requestId")) or text(body.get("trace_id"))
    parts: List[str] = []
    if code and code != "0" and code != str(status):
        parts.append(f"code {code}")
    if request_id:
        parts.append(f"request {request_id}")
    out = f" ({suggestion})" if suggestion and suggestion != shown else ""
    if parts:
        out += f" [{', '.join(parts)}]"
    return out


def safe_url(url: str) -> str:
    """URL without its query string (signed URLs carry credentials there)."""
    q = url.find("?")
    return url if q == -1 else url[:q] + "?…"


def host_of(url: str) -> str:
    try:
        return urlsplit(url).netloc or url
    except ValueError:
        return url


def multipart(parts: List[Dict[str, Any]]) -> Tuple[bytes, str]:
    """
    A multipart/form-data body. Each part: {"name", "value" (str|bytes), optional "filename",
    optional "content_type"}. Returns (body, content-type header value).
    """
    boundary = "----g3d" + uuid.uuid4().hex
    chunks: List[bytes] = []
    for p in parts:
        head = f'--{boundary}\r\nContent-Disposition: form-data; name="{p["name"]}"'
        if p.get("filename") is not None:
            head += f'; filename="{p["filename"]}"'
        head += "\r\n"
        if p.get("content_type"):
            head += f'Content-Type: {p["content_type"]}\r\n'
        head += "\r\n"
        chunks.append(head.encode("utf-8"))
        value = p["value"]
        chunks.append(value.encode("utf-8") if isinstance(value, str) else bytes(value))
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


JsonBody = Union[dict, list]


class Http:
    """Requests with timeouts, readable errors and logging. One instance is shared."""

    def __init__(self, transport: Optional[Transport] = None, log: Any = None):
        self.transport = transport or urllib_transport
        self.log = log
        self._deprecations: set = set()

    def _send(self, req: Request, label: str) -> Response:
        started = time.time()
        try:
            res = self.transport(req)
        except (urllib.error.URLError, OSError, ssl.SSLError, ValueError) as err:
            reason = getattr(err, "reason", None) or err
            if self.log:
                self.log.warn(f"{label} {req.method} {safe_url(req.url)} failed", str(reason))
            raise NetworkError(f"{label}: cannot reach {host_of(req.url)} ({reason})") from err
        if self.log:
            self.log.debug(f"{label} {req.method} {safe_url(req.url)} → {res.status} in {int((time.time() - started) * 1000)} ms")
        self._report_deprecation(res.headers, label, req.method, req.url)
        return res

    def _report_deprecation(self, headers: Dict[str, str], label: str, method: str, url: str) -> None:
        deprecation = headers.get("deprecation")
        if not deprecation or not self.log:
            return
        parts = urlsplit(url)
        key = f"{method} {parts.netloc}{parts.path}"
        if key in self._deprecations:
            return
        self._deprecations.add(key)
        extra = "".join(f"; {k.title()}: {headers[k]}" for k in ("sunset", "link") if headers.get(k))
        self.log.warn(f"{label}: the service marked {key} as deprecated (Deprecation: {deprecation}{extra}). Please report this so the plugin can be updated.")

    def request(self, url: str, method: str = "GET", headers: Optional[Dict[str, str]] = None, body: Optional[bytes] = None, timeout: float = 60.0, label: str = "Request") -> Response:
        """A raw request; no status check."""
        return self._send(Request(method, url, dict(headers or {}), body, timeout), label)

    def request_json(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        json_body: Optional[JsonBody] = None,
        data: Optional[bytes] = None,
        timeout: float = 60.0,
        label: str = "Request",
    ) -> Any:
        """JSON request; returns the parsed body (or the text when it is not JSON). Raises HttpError on 4xx/5xx."""
        h = dict(headers or {})
        body = data
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            h.setdefault("Content-Type", "application/json")
        res = self._send(Request(method, url, h, body, timeout), label)
        text = res.text()
        parsed: Any = text
        if text:
            try:
                parsed = json.loads(text)
            except ValueError:
                pass  # HTML error page, plain text
        else:
            parsed = None
        if self.log and isinstance(parsed, str):
            self.log.debug(f"{label} body", parsed[:300])
        if not res.ok:
            detail = error_message_from(parsed)
            wait = retry_after_ms(res.headers)
            raise HttpError(f"{label} error {res.status}" + (f": {detail}" if detail else "") + error_extras(parsed, detail, res.status), res.status, parsed, url, wait)
        return parsed

    def download(self, url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 600.0, max_bytes: int = 512 * 1024 * 1024, label: str = "Download") -> bytes:
        """Downloads a file into memory. Signed provider links expire, so this runs as soon as a result is ready."""
        started = time.time()
        try:
            res = self.transport(Request("GET", url, dict(headers or {}), None, timeout))
        except (urllib.error.URLError, OSError, ssl.SSLError, ValueError) as err:
            raise NetworkError(f"{label}: cannot download {safe_url(url)} ({getattr(err, 'reason', None) or err})") from err
        if not res.ok:
            hint = " (the link may have expired)" if res.status == 403 else ""
            raise HttpError(f"{label} failed with HTTP {res.status}{hint}", res.status, res.text()[:300], url)
        if len(res.body) > max_bytes:
            raise ValueError(f"{label}: file is {round(len(res.body) / 1e6)} MB, over the {round(max_bytes / 1e6)} MB limit")
        if self.log:
            self.log.debug(f"{label} {safe_url(url)} {len(res.body)} bytes in {int((time.time() - started) * 1000)} ms")
        return res.body
