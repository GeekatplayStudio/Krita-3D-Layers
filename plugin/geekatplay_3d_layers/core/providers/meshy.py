"""
Meshy (https://docs.meshy.ai): image to 3D. A port of the Photoshop plugin's
src/host/providers/meshy.ts; both plugins send the same requests, field for field.

- Create: POST /openapi/v1/image-to-3d with the image as a PNG data URI (Meshy accepts data
  URIs, so there is no upload step) → {"result": task id}. alpha_thumbnail=true asks for a
  transparent preview. Smart Topology (meshy-t2) is sent with model_type "smart-topology".
- Poll: GET /openapi/v1/image-to-3d/{id} → status PENDING | IN_PROGRESS | SUCCEEDED | FAILED |
  CANCELED, progress 0-100, model_urls.glb, alpha_thumbnail_url / thumbnail_url,
  task_error.message.
- Cancel: DELETE the task. Meshy refunds PENDING tasks; running ones answer 409.
- Test: GET /openapi/v1/balance → {"balance"}.

A 429 carries Retry-After, which reaches the job manager as HttpError.retry_after_ms.
Browse (listing past tasks) is not ported.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, Optional
from urllib.parse import quote

from ..http import HttpError
from ..settings import MESHY_SMART_TOPOLOGY_MODEL
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

#: Task kinds and their endpoints. Jobs created here are always image-to-3d; the others
#: come back through resolve() for tasks made elsewhere with the same key.
KIND_PATH: Dict[str, str] = {
    "image-to-3d": "/openapi/v1/image-to-3d",
    "multi-image-to-3d": "/openapi/v1/multi-image-to-3d",
    "text-to-3d": "/openapi/v2/text-to-3d",
}

_KIND_LABEL = {"image-to-3d": "Image to 3D", "multi-image-to-3d": "Multi-image to 3D", "text-to-3d": "Text to 3D"}


# ---------------------------------------------------------------- shared helpers (Tripo uses them too)


def clean_key(key: Optional[str]) -> str:
    """Accepts "msy_…", "Bearer msy_…" or a quoted key pasted from the docs."""
    k = re.sub(r"[\"']", "", key or "").strip()
    return re.sub(r"^bearer\s+", "", k, flags=re.I).strip()


def js_string(v: Any) -> str:
    """
    A value as JavaScript's String() writes it, so messages read the same as in the Photoshop
    plugin: 20.0 → "20" (JSON decimals arrive as floats here), None → "null", True → "true".
    """
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if v != v:
            return "NaN"
        if v in (float("inf"), float("-inf")):
            return "Infinity" if v > 0 else "-Infinity"
        if v.is_integer() and abs(v) < 1e21:
            return str(int(v))
        return repr(v)
    return str(v)


def encode_uri_component(text: str) -> str:
    """JavaScript's encodeURIComponent (task ids go into the URL path)."""
    return quote(str(text), safe="!*'()")


def utc_minute(ms: float) -> Optional[str]:
    """Epoch ms → "2026-09-21 13:46" in UTC (the TS uses toISOString().slice(0, 16)); None if out of range."""
    try:
        return (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=ms)).isoformat()[:16].replace("T", " ")
    except (OverflowError, ValueError):
        return None


def without_none(d: Dict[str, Any]) -> Dict[str, Any]:
    """Drops empty entries, as JSON.stringify drops undefined ones in the TS meta."""
    return {k: v for k, v in d.items() if v is not None}


# ---------------------------------------------------------------- request building


def _headers(ctx: ProviderContext) -> Dict[str, str]:
    key = clean_key(ctx.secret("meshy.apiKey"))
    if not key:
        raise RuntimeError("Meshy: add your API key in Settings → Meshy.")
    # The TS sends the JSON content type on every call, GET and DELETE included.
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _base(ctx: ProviderContext) -> str:
    return ctx.settings["meshy"]["baseUrl"]


def _kind_of(meta: Optional[Dict[str, Any]]) -> str:
    k = meta.get("kind") if meta else None
    return k if k in ("multi-image-to-3d", "text-to-3d") else "image-to-3d"


def _task_url(ctx: ProviderContext, kind: str, remote_id: str) -> str:
    return f"{_base(ctx)}{KIND_PATH[kind]}/{encode_uri_component(remote_id)}"


def build_image_to_3d_body(settings: Dict[str, Any], data_uri: str) -> Dict[str, Any]:
    """Request body for image-to-3d from the user's settings (only documented fields, per model)."""
    model = settings["aiModel"]
    if model == MESHY_SMART_TOPOLOGY_MODEL:
        # Smart Topology: clean low-poly topology; target_polycount 100-15,000 (Meshy's default is 4,000).
        # It takes none of the remesh or resolution fields below.
        body: Dict[str, Any] = {
            "image_url": data_uri,
            "model_type": "smart-topology",
            "ai_model": model,
            "should_texture": settings["shouldTexture"],
            "enable_pbr": settings["shouldTexture"] and settings["enablePbr"],
            "target_formats": ["glb"],
            "alpha_thumbnail": True,
        }
        if settings["moderation"]:
            body["moderation"] = True
        if settings["targetPolycount"] > 0:
            body["target_polycount"] = min(15_000, max(100, settings["targetPolycount"]))
        return body
    body = {
        "image_url": data_uri,
        "ai_model": model,
        "should_texture": settings["shouldTexture"],
        "enable_pbr": settings["shouldTexture"] and settings["enablePbr"],
        "should_remesh": settings["shouldRemesh"],
        "target_formats": ["glb"],
        "alpha_thumbnail": True,
    }
    # Meshy screens the input image for harmful content and rejects it with an explanation.
    if settings["moderation"]:
        body["moderation"] = True
    if settings["shouldRemesh"]:
        body["topology"] = settings["topology"]
        if settings["targetPolycount"] > 0:
            body["target_polycount"] = max(100, settings["targetPolycount"])
    # Each optional field goes only to the models that document it; others answer 400.
    if settings["shouldTexture"] and settings["textureResolution"] != "2k" and model != "meshy-6-lite":
        body["texture_resolution"] = settings["textureResolution"]
    if settings["geometryResolution"] != "standard" and model in ("latest", "meshy-7.1"):
        body["geometry_resolution"] = settings["geometryResolution"]
    if model == "meshy-6":
        body["remove_lighting"] = settings["removeLighting"]
    if model in ("meshy-6", "meshy-7.1", "latest"):
        body["image_enhancement"] = settings["imageEnhancement"]
    return body


# ---------------------------------------------------------------- reading tasks


def _map_status(status: Any) -> str:
    st = str(status if status is not None else "").upper()
    if st == "PENDING":
        return "queued"
    if st == "IN_PROGRESS":
        return "running"
    if st == "SUCCEEDED":
        return "succeeded"
    if st == "FAILED":
        return "failed"
    if st in ("CANCELED", "CANCELLED"):
        return "cancelled"
    if st == "EXPIRED":
        return "expired"
    return "unknown"


def _thumbnail_of(task: Dict[str, Any]) -> Optional[str]:
    """The transparent preview when Meshy made one (alpha_thumbnail), else the regular one."""
    return s(task.get("alpha_thumbnail_url")) or s(task.get("thumbnail_url"))


def _task_name(task: Dict[str, Any], kind: str) -> str:
    prompt = s(task.get("prompt")) or s(task.get("texture_prompt"))
    if prompt:
        return prompt[:60]
    created = to_epoch_ms(task.get("created_at"))
    label = _KIND_LABEL[kind]
    when = utc_minute(created) if created else None
    return f"{label} {when}" if when else label


def _result_from(task: Dict[str, Any], kind: str) -> Optional[ModelResult]:
    glb = s(obj(task.get("model_urls")).get("glb"))
    if not glb:
        return None
    return ModelResult(
        model_url=glb,
        format=format_from_url(glb),
        thumbnail_url=_thumbnail_of(task),
        name=_task_name(task, kind),
        created_at=to_epoch_ms(task.get("created_at")),
        meta=without_none(
            {"kind": kind, "aiModel": task.get("ai_model"), "expiresAt": to_epoch_ms(task.get("expires_at")), "credits": task.get("consumed_credits")}
        ),
    )


class MeshyProvider(Provider):
    id = "meshy"
    label = "Meshy"
    can_cancel = True

    def is_configured(self, ctx: ProviderContext) -> Configured:
        key = clean_key(ctx.secret("meshy.apiKey"))
        return Configured(True) if key else Configured(False, "Add your Meshy API key in Settings.")

    def test(self, ctx: ProviderContext) -> TestResult:
        try:
            body = obj(ctx.http.request_json(f"{_base(ctx)}/openapi/v1/balance", headers=_headers(ctx), timeout=20, label="Meshy"))
            return TestResult(True, "Connected to Meshy.", f"{js_string(body['balance'])} credits" if "balance" in body else None)
        except Exception as err:  # noqa: BLE001 - every failure (missing key included) is reported, not raised
            return TestResult(False, str(err))

    def submit(self, ctx: ProviderContext, inp: SubmitInput) -> SubmitResult:
        data_uri = "data:image/png;base64," + base64.b64encode(bytes(inp.image)).decode("ascii")
        body = build_image_to_3d_body(ctx.settings["meshy"], data_uri)
        res = obj(
            ctx.http.request_json(f"{_base(ctx)}{KIND_PATH['image-to-3d']}", "POST", headers=_headers(ctx), json_body=body, timeout=120, label="Meshy")
        )
        remote_id = s(res.get("result")) or s(res.get("id"))
        if not remote_id:
            raise RuntimeError("Meshy did not return a task id.")
        return SubmitResult(remote_id, {"kind": "image-to-3d", "aiModel": ctx.settings["meshy"]["aiModel"]})

    def _task(self, ctx: ProviderContext, kind: str, remote_id: str) -> Dict[str, Any]:
        return obj(ctx.http.request_json(_task_url(ctx, kind, remote_id), headers=_headers(ctx), timeout=30, label="Meshy"))

    def poll(self, ctx: ProviderContext, remote_id: str, meta: Optional[Dict[str, Any]] = None) -> PollResult:
        kind = _kind_of(meta)
        task = self._task(ctx, kind, remote_id)
        state = _map_status(task.get("status"))
        progress = to_percent(task.get("progress"))
        error_message = s(obj(task.get("task_error")).get("message"))
        if state == "succeeded":
            result = _result_from(task, kind)
            return PollResult("succeeded", progress=100, result=result) if result else PollResult("failed", error="Meshy finished but returned no GLB file.")
        if state in ("failed", "expired"):
            return PollResult("failed", error=error_message or f"Meshy task {state}.")
        if state == "cancelled":
            return PollResult("cancelled")
        if state == "queued":
            ahead = task.get("preceding_tasks")
            if isinstance(ahead, bool) or not isinstance(ahead, (int, float)):
                ahead = None
            return PollResult("queued", progress=progress, message=f"{js_string(ahead)} tasks ahead in Meshy's queue" if ahead else "Waiting in Meshy's queue")
        # IN_PROGRESS, and any status Meshy adds later: keep polling.
        return PollResult("running", progress=progress, message="Meshy is generating")

    def resolve(self, ctx: ProviderContext, remote_id: str, meta: Optional[Dict[str, Any]] = None) -> ModelResult:
        # Without a kind in meta (a bare task id), each endpoint is tried until one knows the task.
        kinds = [_kind_of(meta)] if meta and meta.get("kind") else list(KIND_PATH)
        last_error: Optional[Exception] = None
        for kind in kinds:
            try:
                task = self._task(ctx, kind, remote_id)
                result = _result_from(task, kind)
                if result:
                    return result
                status = task.get("status")
                raise RuntimeError(f"Meshy task {remote_id} has no GLB (status {js_string(status if status is not None else 'unknown')}).")
            except Exception as err:  # noqa: BLE001 - only a 404 moves on to the next kind
                last_error = err
                if not (isinstance(err, HttpError) and err.status == 404):
                    break
        raise last_error if last_error is not None else RuntimeError(f"Meshy task {remote_id} not found.")

    def cancel(self, ctx: ProviderContext, remote_id: str, meta: Optional[Dict[str, Any]] = None) -> None:
        kind = _kind_of(meta)
        try:
            ctx.http.request_json(_task_url(ctx, kind, remote_id), "DELETE", headers=_headers(ctx), timeout=30, label="Meshy")
        except HttpError as err:
            if err.status == 409:
                raise RuntimeError("Meshy already started this task and cannot cancel it; it will finish on Meshy's side.") from err
            raise
