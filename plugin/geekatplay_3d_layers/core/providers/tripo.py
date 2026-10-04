"""
Tripo (https://developers.tripo3d.ai), API v3. A port of the Photoshop plugin's
src/host/providers/tripo.ts; both plugins send the same requests, field for field.

Tripo's V2 API (api.tripo3d.ai/v2/openapi) stops accepting requests on 2026-11-01, so this
targets V3 (https://openapi.tripo3d.ai/v3):

- Upload: POST /files (multipart "file", PNG/JPEG/WebP up to 20 MB) → data.file_token.
  V3 rejects data URIs, so the image is always uploaded first.
- Create: POST /generation/image-to-model {input: file_token, model, texture, pbr, ...} →
  data.task_id. H series (v3.1, v3.0, v2.5) and P series (P1, P2 preview); texture_version
  picks the texture model (v3.5 adds texture_quality "fast" and delight).
- Poll: GET /tasks/{id} → data.status queued | running | success | failed | cancelled (banned
  and expired count as failed), data.progress, data.output.model_url / rendered_image_url.
- Test: GET /account/balance → data.balance / data.frozen (decimals).

Answers come in a {"code", "data"} envelope, and a non-zero code is an error even with HTTP
200. There is no cancel endpoint. A 429 (too many tasks at once) carries Retry-After, which
reaches the job manager as HttpError.retry_after_ms. Unknown task statuses count as failed, as
Tripo's v3 migration guide asks. Browse (account usage + batch task query) is not ported.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, Optional, Tuple

from ..http import multipart
from ..settings import TRIPO_TEXTURE_V35
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
    to_epoch_ms,
    to_percent,
)
from .meshy import clean_key, encode_uri_component, js_string, utc_minute, without_none

#: Tripo's upload limit for /files.
TRIPO_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _auth(ctx: ProviderContext) -> Dict[str, str]:
    key = clean_key(ctx.secret("tripo.apiKey"))
    if not key:
        raise RuntimeError("Tripo: add your API key in Settings → Tripo.")
    return {"Authorization": f"Bearer {key}"}


def _base(ctx: ProviderContext) -> str:
    return ctx.settings["tripo"]["baseUrl"]


def _nullish(v: Any, fallback: Any) -> Any:
    """JavaScript's `v ?? fallback`."""
    return v if v is not None else fallback


def _payload(body: Any, what: str) -> Any:
    """The `data` of a {"code", "data"} envelope; a non-zero code becomes an error."""
    b = obj(body)
    code = b.get("code")
    if isinstance(code, (int, float)) and not isinstance(code, bool) and code != 0:
        msg = s(b.get("message")) or s(b.get("msg")) or f"code {js_string(code)}"
        hint = s(b.get("suggestion"))
        request_id = s(b.get("request_id"))
        raise RuntimeError(
            f"Tripo {what} failed: {msg}" + (f" ({hint})" if hint else "") + f" [code {js_string(code)}" + (f", request {request_id}" if request_id else "") + "]"
        )
    return _nullish(b.get("data"), body)


def _unwrap(body: Any, what: str) -> Dict[str, Any]:
    return obj(_payload(body, what))


def tripo_face_limit_range(model: str, geometry_quality: str, smart_low_poly: bool) -> Optional[Tuple[int, int]]:
    """
    Documented face_limit range for a model and mode (the image-to-model H series and P series
    pages). Values outside it are answered with error 1004, so they are clamped. None for a
    model the docs do not cover yet (the value is then sent as is).
    """
    if re.match(r"P1-", model, re.I):
        return (50, 20_000)
    if re.match(r"P2-", model, re.I):
        return (50, 50_000)
    if smart_low_poly:
        return (500, 20_000)
    if re.match(r"v3\.1-", model):
        return (1, 2_000_000 if geometry_quality == "detailed" else 1_500_000)
    if re.match(r"v3\.0-", model):
        return (1, 2_000_000 if geometry_quality == "detailed" else 1_000_000)
    if re.match(r"v2\.5-", model):
        return (1, 500_000)
    return None


def build_image_to_model_body(settings: Dict[str, Any], file_token: str) -> Dict[str, Any]:
    """Request body for image-to-model from the user's settings (only documented fields, per model)."""
    model = settings["model"]
    is_p = re.match(r"P\d", model, re.I) is not None
    # geometry_quality, smart_low_poly and auto_size are valid only for H-series models from v3.0.
    is_v3 = re.match(r"v3\.", model) is not None and not is_p
    textured = settings["texture"] or settings["pbr"]
    body: Dict[str, Any] = {
        "input": file_token,
        "model": model,
        "texture": textured,
        "pbr": settings["pbr"],
        "orientation": settings["orientation"],
    }
    if is_v3:
        body["auto_size"] = settings["autoSize"]
    if textured:
        body["texture_quality"] = settings["textureQuality"]
        if settings["textureVersion"] and not is_p:
            body["texture_version"] = settings["textureVersion"]
        # "fast" only exists on the v3.5 texture model; delight is read only by v3.5.
        if settings["textureQuality"] == "fast" and not is_p:
            body["texture_version"] = TRIPO_TEXTURE_V35
        if body.get("texture_version") == TRIPO_TEXTURE_V35:
            body["delight"] = settings["delight"]
    if is_v3:
        body["geometry_quality"] = settings["geometryQuality"]
        if settings["smartLowPoly"]:
            body["smart_low_poly"] = True
    if settings["faceLimit"] > 0:
        rng = tripo_face_limit_range(
            model,
            geometry_quality=settings["geometryQuality"] if is_v3 else "standard",
            smart_low_poly=is_v3 and settings["smartLowPoly"],
        )
        body["face_limit"] = min(rng[1], max(rng[0], settings["faceLimit"])) if rng else settings["faceLimit"]
    return body


# ---------------------------------------------------------------- reading tasks and balances


def _map_status(status: Any) -> str:
    st = str(_nullish(status, "")).lower()
    if st in ("queued", "running"):
        return st
    if st == "success":
        return "succeeded"
    if st in ("cancelled", "canceled"):
        return "cancelled"
    if st == "expired":
        return "expired"
    if st in ("failed", "banned"):
        return "failed"
    return "unknown"


def _task_name(task: Dict[str, Any]) -> str:
    prompt = s(obj(task.get("input")).get("prompt")) or s(task.get("prompt"))
    if prompt:
        return prompt[:60]
    created = to_epoch_ms(_nullish(task.get("created_at"), task.get("create_time")))
    when = utc_minute(created) if created else None
    return f"Tripo model {when}" if when else "Tripo model"


def _result_from(task: Dict[str, Any]) -> Optional[ModelResult]:
    out = obj(task.get("output"))
    url = s(out.get("model_url")) or s(out.get("pbr_model")) or s(out.get("model")) or s(out.get("base_model"))
    if not url:
        return None
    return ModelResult(
        model_url=url,
        format=format_from_url(url),
        thumbnail_url=s(out.get("rendered_image_url")) or s(out.get("rendered_image")) or s(out.get("generated_image_url")),
        name=_task_name(task),
        created_at=to_epoch_ms(_nullish(task.get("created_at"), task.get("create_time"))),
        meta=without_none({"type": task.get("type"), "credits": _nullish(task.get("credits_consumed"), task.get("consumed_credit"))}),
    )


_NUMERIC = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def _number(data: Dict[str, Any], key: str) -> Optional[float]:
    """
    data[key] read like the TS (`typeof v === "number" ? v : Number(v)`), or None when that is
    not a finite number. Tripo documents decimals, which may come as strings ("120.50").
    JavaScript's Number() turns null, "" and booleans into numbers; that is kept so both
    plugins show the same balance.
    """
    if key not in data:
        return None
    v = data[key]
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v if math.isfinite(v) else None
    if isinstance(v, str):
        t = v.strip()
        if not t:
            return 0
        if _NUMERIC.fullmatch(t):
            n = float(t)
            return n if math.isfinite(n) else None
    return None


class TripoProvider(Provider):
    id = "tripo"
    label = "Tripo"
    can_cancel = False  # Tripo has no cancel endpoint; base.cancel() stays unimplemented.

    def is_configured(self, ctx: ProviderContext) -> Configured:
        key = clean_key(ctx.secret("tripo.apiKey"))
        return Configured(True) if key else Configured(False, "Add your Tripo API key in Settings.")

    def test(self, ctx: ProviderContext) -> TestResult:
        try:
            data = _unwrap(ctx.http.request_json(f"{_base(ctx)}/account/balance", headers=_auth(ctx), timeout=20, label="Tripo"), "balance")
            balance = _number(data, "balance")
            frozen = _number(data, "frozen")
            text = None
            if balance is not None:
                text = f"{js_string(balance)} credits" + (f" ({js_string(frozen)} reserved)" if frozen is not None and frozen > 0 else "")
            return TestResult(True, "Connected to Tripo (API v3).", text)
        except Exception as err:  # noqa: BLE001 - every failure (missing key included) is reported, not raised
            return TestResult(False, str(err))

    def submit(self, ctx: ProviderContext, inp: SubmitInput) -> SubmitResult:
        size = len(inp.image)
        if size > TRIPO_MAX_UPLOAD_BYTES:
            # math.floor(x + 0.5) is JavaScript's Math.round (Python's round() rounds halves to even).
            raise RuntimeError(
                f"The image is {math.floor(size / 1e6 + 0.5)} MB; Tripo accepts up to 20 MB. Lower Settings → Generation → Max image size, or crop the layer."
            )
        h = _auth(ctx)
        form, content_type = multipart([{"name": "file", "value": inp.image, "filename": "image.png", "content_type": "image/png"}])
        uploaded = _unwrap(
            ctx.http.request_json(f"{_base(ctx)}/files", "POST", headers={**h, "Content-Type": content_type}, data=form, timeout=180, label="Tripo upload"),
            "upload",
        )
        token = s(uploaded.get("file_token")) or s(uploaded.get("image_token")) or s(uploaded.get("token"))
        if not token:
            raise RuntimeError("Tripo upload did not return a file token.")

        body = build_image_to_model_body(ctx.settings["tripo"], token)
        created = _unwrap(
            ctx.http.request_json(
                f"{_base(ctx)}/generation/image-to-model", "POST", headers={**h, "Content-Type": "application/json"}, json_body=body, timeout=60, label="Tripo"
            ),
            "task creation",
        )
        remote_id = s(created.get("task_id")) or s(created.get("id"))
        if not remote_id:
            raise RuntimeError("Tripo did not return a task id.")
        return SubmitResult(remote_id, {"model": ctx.settings["tripo"]["model"]})

    def _task(self, ctx: ProviderContext, remote_id: str) -> Dict[str, Any]:
        url = f"{_base(ctx)}/tasks/{encode_uri_component(remote_id)}"
        return _unwrap(ctx.http.request_json(url, headers=_auth(ctx), timeout=30, label="Tripo"), "task query")

    def poll(self, ctx: ProviderContext, remote_id: str, meta: Optional[Dict[str, Any]] = None) -> PollResult:
        task = self._task(ctx, remote_id)
        state = _map_status(task.get("status"))
        progress = to_percent(task.get("progress"))
        if state == "succeeded":
            result = _result_from(task)
            return PollResult("succeeded", progress=100, result=result) if result else PollResult("failed", error="Tripo finished but returned no model URL.")
        if state in ("failed", "expired"):
            # The TS tests `error_code !== undefined`, so a present null still prints "(code null)".
            code = f" (code {js_string(task['error_code'])})" if "error_code" in task else ""
            return PollResult("failed", error=f"{s(task.get('error_message')) or f'Tripo task {state}'}{code}")
        if state == "cancelled":
            return PollResult("cancelled")
        if state == "queued":
            return PollResult("queued", progress=progress, message="Waiting in Tripo's queue")
        if state == "running":
            return PollResult("running", progress=progress, message="Tripo is generating")
        # Tripo's v3 migration guide: treat any unrecognised status as failed.
        return PollResult("failed", error=f'Tripo reported an unknown task status "{js_string(_nullish(task.get("status"), ""))}".')

    def resolve(self, ctx: ProviderContext, remote_id: str, meta: Optional[Dict[str, Any]] = None) -> ModelResult:
        # Result URLs last about 24 h; querying the task again returns fresh ones.
        task = self._task(ctx, remote_id)
        result = _result_from(task)
        if not result:
            raise RuntimeError(f"Tripo task {remote_id} has no downloadable model (status {js_string(_nullish(task.get('status'), 'unknown'))}).")
        return result
