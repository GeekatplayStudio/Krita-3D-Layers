"""
The local web server the 3D editor and the task page talk to.

Krita has no web view a Python plugin can use, so the editor (three.js, the same one as in
the Photoshop plugin) runs in a browser window. This server gives it:
  GET  /s/<token>/<file>                  the editor's own files (plugin/.../web)
  GET  /s/<token>/library/<file>          library models and previews
  GET  /s/<token>/import-file/<id>/<n>    files of an import in progress
  POST /s/<token>/rpc                     {"method", "params"} → {"ok", "result" | "error"}

It listens on 127.0.0.1 only, on a free port, and answers only for tokens of open sessions
(24 random bytes each), so other programs and web pages cannot use it. RPC calls are
handed to Krita's UI thread by the plugin.
"""
from __future__ import annotations

import json
import mimetypes
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import unquote, urlsplit

MAX_BODY = 1024 * 1024 * 1024  # an 8192 px render as base64 PNG stays far below this

_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".wasm": "application/wasm",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".exr": "application/octet-stream",
    ".hdr": "application/octet-stream",
}


class Session:
    """An editor or task window. `data` holds what the plugin needs to answer its calls."""

    def __init__(self, kind: str, data: Dict[str, Any]):
        self.kind = kind
        self.data = data
        self.token = secrets.token_urlsafe(24)
        self.created = time.time()
        self.last_seen = time.time()
        self.closed = False


class LocalServer:
    def __init__(
        self,
        web_dir: Path,
        library_dir: Callable[[], Path],
        import_file: Callable[[str, int], Optional[str]],
        rpc: Callable[[Session, str, Any], Any],
        log: Any,
    ):
        self.web_dir = web_dir
        self.library_dir = library_dir
        self.import_file = import_file
        self.rpc = rpc
        self.log = log
        self.sessions: Dict[str, Session] = {}
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._lock = threading.Lock()

    # ---------------------------------------------------------- lifecycle

    @property
    def port(self) -> int:
        return self._httpd.server_address[1] if self._httpd else 0

    def start(self) -> None:
        if self._httpd:
            return
        server = self

        class Handler(_Handler):
            owner = server

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever, name="g3d-server", daemon=True).start()
        self.log.info(f"Local server for the 3D editor on 127.0.0.1:{self.port}")

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def open_session(self, kind: str, data: Dict[str, Any]) -> Session:
        self.start()
        session = Session(kind, data)
        with self._lock:
            self.sessions[session.token] = session
        return session

    def close_session(self, session: Session) -> None:
        session.closed = True
        with self._lock:
            self.sessions.pop(session.token, None)

    def url(self, session: Session, page: str) -> str:
        return f"http://127.0.0.1:{self.port}/s/{session.token}/{page}"

    def session_for(self, token: str) -> Optional[Session]:
        with self._lock:
            return self.sessions.get(token)


class _Handler(BaseHTTPRequestHandler):
    owner: LocalServer
    protocol_version = "HTTP/1.1"
    server_version = "Geekatplay3DLayers"

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet: the plugin log has what matters
        pass

    # ------------------------------------------------------------ routing

    def _route(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return None, None  # another host name pointing here (DNS rebinding)
        parts = unquote(urlsplit(self.path).path).split("/", 3)
        if len(parts) < 3 or parts[1] != "s":
            return None, None
        session = self.owner.session_for(parts[2])
        if not session:
            return None, None
        session.last_seen = time.time()
        return session, (parts[3] if len(parts) > 3 else "")

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        session, rest = self._route()
        if session is None:
            return self._send(404, b"Not found", "text/plain")
        if rest in ("", "/"):
            rest = "editor.html" if session.kind == "editor" else "tasks.html"
        if rest == "library/.reachable":
            return self._send(200, b"ok", "text/plain")
        if rest.startswith("library/"):
            return self._file(self.owner.library_dir(), rest[len("library/") :])
        if rest.startswith("import-file/"):
            bits = rest.split("/")
            path = self.owner.import_file(bits[1], int(bits[2])) if len(bits) == 3 and bits[2].isdigit() else None
            return self._file_at(Path(path)) if path else self._send(404, b"Not part of this import", "text/plain")
        return self._file(self.owner.web_dir, rest)

    def do_POST(self) -> None:  # noqa: N802
        session, rest = self._route()
        if session is None or rest != "rpc":
            return self._send(404, b"Not found", "text/plain")
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._json(400, {"ok": False, "error": "Bad request"})
        try:
            req = json.loads(self.rfile.read(length).decode("utf-8"))
            method, params = req.get("method"), req.get("params")
        except (ValueError, AttributeError):
            return self._json(400, {"ok": False, "error": "Bad request"})
        try:
            result = self.owner.rpc(session, str(method), params)
            self._json(200, {"ok": True, "result": result})
        except Exception as err:  # noqa: BLE001 - every error goes back to the page as a message
            if not isinstance(err, (ValueError, KeyError, PermissionError, LookupError)) and type(err).__name__ != "DocError":
                self.owner.log.error(f"Editor call {method} failed", err)
            message = err.args[0] if isinstance(err, KeyError) and err.args else str(err)
            self._json(200, {"ok": False, "error": message or type(err).__name__})

    # ------------------------------------------------------------ helpers

    def _file(self, base: Path, rel: str) -> None:
        try:
            path = (base / rel).resolve()
            root = base.resolve()
        except (OSError, ValueError):
            return self._send(404, b"Not found", "text/plain")
        if root not in path.parents:
            return self._send(404, b"Not found", "text/plain")
        self._file_at(path)

    def _file_at(self, path: Path) -> None:
        if not path.is_file():
            return self._send(404, b"Not found", "text/plain")
        ctype = _TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (ConnectionError, OSError):
                    return

    def _json(self, status: int, body: Any) -> None:
        self._send(status, json.dumps(body).encode("utf-8"), "application/json")

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionError, OSError):
            pass
