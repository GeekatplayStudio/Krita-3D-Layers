"""
Hitem3D / Hi3D (https://docs.hi3d.ai, changelog: /en/api/api-reference/changelog), open-api v1
(a port of the Photoshop plugin's src/host/providers/hitem3d.ts).
The API host is still api.hitem3d.ai; keys are created at platform.hi3d.ai.

Auth: the Access Key + Secret Key are exchanged for a bearer token:
  POST /auth/token with "Authorization: Basic base64(AK:SK)" → data.accessToken, data.tokenType.
Tokens are cached in memory for 50 minutes and refreshed once when an API call answers
"login expired" (Hitem3D reports errors as HTTP 200 with a non-200 `code`).
A single value without ":" is used directly as a bearer token.

- Create: POST /submit-task (multipart): images (PNG/JPEG/WebP, ≤ 20 MB), request_type, model,
          resolution, format=2 (GLB; the API's own default is OBJ), face, pbr, rmbg, shading
          (de-shading strength, Aug 2026) → data.task_id
- Poll:   GET  /query-task?task_id= → data.state created|queueing|processing|success|failed,
          data.url (model) and data.cover_url, both valid for 1 hour.
- Test:   GET  /balance → data.totalBalance.
There is no list or cancel endpoint.
"""
from __future__ import annotations

import base64
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

from ..http import multipart
from ..settings import hitem3d_supports_pbr
from .base import (
    Configured,
    ModelResult,
    PollResult,
    Provider,
    ProviderContext,
    SubmitInput,
    SubmitResult,
    TestResult,
    format_from_url,
    obj,
    s,
    to_percent,
)

TOKEN_TTL_MS = 50 * 60 * 1000

#: "<base url>|<access key>" → (authorization header value, expires at epoch ms).
#: Module-level like the TS Map, so every job shares one sign-in. Plain dict reads and
#: writes are atomic in CPython; two threads signing in at once just both get a valid token.
_token_cache: Dict[str, Tuple[str, float]] = {}


def clear_hitem3d_token_cache() -> None:
    """Test hook."""
    _token_cache.clear()


@dataclass
class Credentials:
    kind: str  # "keys" | "token"
    ak: str = ""
    sk: str = ""
    token: str = ""


def _js_str(v: Any) -> str:
    """String(v) as JavaScript writes it (codes and balances arrive as JSON numbers)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return v if isinstance(v, str) else str(v)


def _first(*values: Any) -> Any:
    """JavaScript's `a ?? b ?? c`: the first value that is not None."""
    for v in values:
        if v is not None:
            return v
    return None


def _uri(value: str) -> str:
    """encodeURIComponent()."""
    return quote(value, safe="!~*'()")


def read_credentials(ctx: ProviderContext) -> Optional[Credentials]:
    """
    The keys as typed in Settings. Quotes are stripped (people paste them from docs);
    "AK:SK" in the Access Key field alone is split; "Bearer xyz" or a lone value is a token.
    """

    def clean(v: Any) -> str:
        return re.sub(r"[\"']", "", v or "").strip()

    ak = clean(ctx.secret("hitem3d.accessKey"))
    sk = clean(ctx.secret("hitem3d.secretKey"))
    if not ak and not sk:
        return None
    if ak and not sk and ":" in ak:
        parts = ak.split(":")
        ak, sk = parts[0].strip(), parts[1].strip()
    if re.match(r"^bearer\s+", ak, re.I):
        return Credentials("token", token=re.sub(r"^bearer\s+", "", ak, flags=re.I))
    if ak and sk:
        return Credentials("keys", ak=ak, sk=sk)
    return Credentials("token", token=ak) if ak else None


def is_expired_token_response(body: Any) -> bool:
    """True for Hitem3D's "your token is no good" answers (code 401/403 or "login expired")."""
    b = obj(body)
    code = _js_str(_first(b.get("code"), ""))
    msg = _js_str(_first(b.get("msg"), b.get("message"), ""))
    return code in ("401", "403") or re.search(r"login expired|token expired|invalid token", msg, re.I) is not None


#: Plain-language meaning of Hitem3D's documented error codes (API reference, Sep 2026).
HITEM3D_ERRORS: Dict[str, str] = {
    "40010000": "the Access Key / Secret Key were rejected",
    "30010000": "your Hitem3D balance is too low",
    "50010001": "generation failed (credits refunded)",
    "10000000": "Hitem3D had an internal error; try again later",
    "10031001": "the image is larger than Hitem3D's 20 MB limit",
    "10031002": "the face count is outside the range Hitem3D accepts (Settings → Hitem3D → Face count)",
    "10031003": "this resolution is not available for the chosen model",
    "10031005": "Hitem3D accepts only PNG, JPEG and WebP images",
    "10031006": "Hitem3D does not know this model",
    "10031010": "the image arrived empty",
    "10031017": "this model cannot texture an existing mesh",
}

#: Hitem3D's upload limit per image.
HITEM3D_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _unwrap(body: Any, what: str) -> Dict[str, Any]:
    """Raises for a non-success Hitem3D envelope (errors come as HTTP 200 + code); returns `data`."""
    b = obj(body)
    code = b.get("code")
    if code is not None and _js_str(code) not in ("200", "0"):
        msg = s(b.get("msg")) or s(b.get("message")) or f"code {_js_str(code)}"
        known = HITEM3D_ERRORS.get(_js_str(code))
        raise RuntimeError(f"Hitem3D {what} failed: {f'{known} ({msg})' if known else msg} [code {_js_str(code)}]")
    return obj(b.get("data"))


def _authorization(ctx: ProviderContext, force: bool = False) -> str:
    """The Authorization header value: a raw token, or a cached / fresh sign-in."""
    creds = read_credentials(ctx)
    if creds is None:
        raise RuntimeError("Hitem3D: add your Access Key and Secret Key in Settings → Hitem3D.")
    if creds.kind == "token":
        return f"Bearer {creds.token}"
    base_url = ctx.settings["hitem3d"]["baseUrl"]
    cache_key = f"{base_url}|{creds.ak}"
    now = ctx.now()
    cached = _token_cache.get(cache_key)
    if not force and cached is not None and cached[1] > now:
        return cached[0]

    basic = base64.b64encode(f"{creds.ak}:{creds.sk}".encode("utf-8")).decode("ascii")
    body = ctx.http.request_json(
        f"{base_url}/auth/token",
        "POST",
        headers={"Authorization": f"Basic {basic}", "Accept": "application/json", "Content-Type": "application/json"},
        data=b"{}",
        timeout=30.0,
        label="Hitem3D auth",
    )
    data = _unwrap(body, "sign-in")
    token = s(data.get("accessToken")) or s(data.get("access_token")) or s(data.get("token"))
    if not token:
        raise RuntimeError("Hitem3D sign-in returned no token.")
    kind = s(data.get("tokenType")) or s(data.get("token_type")) or "Bearer"
    value = f"{kind} {token}"
    _token_cache[cache_key] = (value, now + TOKEN_TTL_MS)
    return value


def _call(ctx: ProviderContext, path: str, what: str, method: str = "GET", body: Optional[bytes] = None, content_type: Optional[str] = None, timeout: float = 30.0) -> Dict[str, Any]:
    """Calls the API with a token, signing in again once if Hitem3D says it expired."""
    settings = ctx.settings["hitem3d"]

    def send(auth: str) -> Any:
        headers = {"Authorization": auth, "Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        if settings.get("appId"):
            headers["Appid"] = settings["appId"]
        return ctx.http.request_json(f"{settings['baseUrl']}{path}", method, headers=headers, data=body, timeout=timeout, label="Hitem3D")

    result = send(_authorization(ctx))
    if is_expired_token_response(result):
        creds = read_credentials(ctx)
        if creds is not None and creds.kind == "keys":
            ctx.log.info("Hitem3D token expired; signing in again")
            result = send(_authorization(ctx, True))
    if is_expired_token_response(result):
        raise RuntimeError("Hitem3D: sign-in expired or the token is invalid. Check the keys in Settings → Hitem3D.")
    return _unwrap(result, what)


def build_submit_fields(settings: Dict[str, Any]) -> Dict[str, str]:
    """Multipart fields for submit-task from the user's settings (the "hitem3d" section)."""
    fields: Dict[str, str] = {
        "request_type": settings["requestType"],
        "model": settings["model"],
        "resolution": settings["resolution"],
        "format": "2",  # GLB; Hitem3D defaults to OBJ
        "rmbg": "1" if settings["removeBackground"] else "0",
    }
    if settings["face"] > 0:
        fields["face"] = _js_str(settings["face"])
    textured = hitem3d_supports_pbr(settings["model"]) and settings["requestType"] != "1"
    if textured:
        fields["pbr"] = "1" if settings["pbr"] else "0"
    # De-shading (v2.0, v2.1, v3.0). Only sent when changed from Hitem3D's default of 0.5.
    if textured and settings["shading"] != 0.5:
        fields["shading"] = f"{settings['shading']:.1f}"
    return fields


_STATE_PROGRESS = {"created": 5, "queueing": 15, "processing": 50}


def _result_from(data: Dict[str, Any], remote_id: str) -> Optional[ModelResult]:
    task_result = obj(data.get("task_result"))
    url = s(data.get("url")) or s(data.get("model_url")) or s(task_result.get("model_url")) or s(task_result.get("url")) or s(data.get("download_url"))
    if not url:
        return None
    return ModelResult(
        model_url=url,
        format=format_from_url(url),
        thumbnail_url=s(data.get("cover_url")) or s(task_result.get("cover_url")) or s(data.get("render_url")) or s(task_result.get("render_url")),
        name=f"Hitem3D {remote_id[:8]}",
        meta={"assetId": data["id"]} if "id" in data else {},
    )


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


class Hitem3DProvider(Provider):
    id = "hitem3d"
    label = "Hitem3D"
    can_cancel = False

    def is_configured(self, ctx: ProviderContext) -> Configured:
        if read_credentials(ctx) is not None:
            return Configured(True)
        return Configured(False, "Add your Hitem3D Access Key and Secret Key in Settings.")

    def test(self, ctx: ProviderContext) -> TestResult:
        try:
            data = _call(ctx, "/balance", "balance")
            balance = _first(data.get("totalBalance"), data.get("balance"))
            return TestResult(True, "Connected to Hitem3D.", f"{_js_str(balance)} balance" if balance is not None else None)
        except Exception as err:  # noqa: BLE001 - every failure is reported in Settings
            return TestResult(False, str(err))

    def submit(self, ctx: ProviderContext, inp: SubmitInput) -> SubmitResult:
        size = len(inp.image)
        if size > HITEM3D_MAX_UPLOAD_BYTES:
            mb = math.floor(size / 1e6 + 0.5)
            raise RuntimeError(f"The image is {mb} MB; Hitem3D accepts up to 20 MB. Lower Settings → Generation → Max image size, or crop the layer.")
        settings = ctx.settings["hitem3d"]
        fields = build_submit_fields(settings)
        parts = [{"name": "images", "value": inp.image, "filename": "image.png", "content_type": "image/png"}]
        parts += [{"name": name, "value": value} for name, value in fields.items()]
        body, content_type = multipart(parts)
        data = _call(ctx, "/submit-task", "task creation", method="POST", body=body, content_type=content_type, timeout=180.0)
        task_id = s(data.get("task_id")) or s(data.get("taskId")) or s(data.get("id"))
        if not task_id:
            raise RuntimeError("Hitem3D did not return a task id.")
        return SubmitResult(task_id, {"model": settings["model"], "resolution": settings["resolution"]})

    def poll(self, ctx: ProviderContext, remote_id: str, meta: Optional[Dict[str, Any]] = None) -> PollResult:
        data = _call(ctx, f"/query-task?task_id={_uri(remote_id)}", "task query")
        state = _js_str(_first(data.get("state"), "")).lower()
        legacy_status = data.get("task_status")
        legacy = legacy_status if _is_number(legacy_status) else None
        result = _result_from(data, remote_id)
        previous = meta["progress"] if meta and _is_number(meta.get("progress")) else 0
        if state == "success" or legacy == 4 or (result is not None and state != "failed"):
            if result is not None:
                return PollResult("succeeded", progress=100, result=result)
            return PollResult("failed", error="Hitem3D finished but returned no model URL.")
        if state == "failed" or legacy == -1:
            return PollResult("failed", error=s(data.get("task_msg")) or s(data.get("message")) or "Hitem3D generation failed (credits are refunded).")
        reported = to_percent(_first(data.get("process_pct"), data.get("progress"), data.get("percent")))
        progress = max(previous, reported if reported is not None else _STATE_PROGRESS.get(state, 10))
        new_meta = dict(meta or {})
        new_meta["progress"] = progress
        return PollResult(
            "queued" if state in ("created", "queueing") else "running",
            progress=progress,
            message=f"Hitem3D: {state}" if state else "Hitem3D is generating",
            meta=new_meta,
        )

    def resolve(self, ctx: ProviderContext, remote_id: str, meta: Optional[Dict[str, Any]] = None) -> ModelResult:
        data = _call(ctx, f"/query-task?task_id={_uri(remote_id)}", "task query")
        result = _result_from(data, remote_id)
        if result is None:
            raise RuntimeError(f"Hitem3D task {remote_id} has no downloadable model (state {_js_str(_first(data.get('state'), 'unknown'))}).")
        return result
