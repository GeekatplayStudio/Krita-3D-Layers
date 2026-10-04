"""
ComfyUI (local or LAN server): runs an image → 3D workflow
(a port of the Photoshop plugin's src/host/providers/comfyui.ts).

- Upload: POST /upload/image (multipart image, subfolder=krita3d, overwrite=true)
- Run:    POST /prompt {prompt, client_id} → prompt_id (validation errors come back as node_errors)
- Poll:   GET  /history/{id}; while absent, GET /queue tells queued vs running.
          ComfyUI reports no percentage over HTTP, so progress is estimated from elapsed time.
- Result: the first .glb/.gltf in the history outputs (SaveGLB reports outputs[node]["3d"]),
          downloaded through GET /view?filename=&subfolder=&type=output
- Cancel: POST /api/jobs/{id}/cancel (ComfyUI ≥ 0.26; only interrupts if that job is the one
          running). Older servers: POST /queue {delete} or POST /interrupt, which ComfyUI 0.38
          marks deprecated.
- Check:  GET  /object_info/<node> for the TRELLIS.2 nodes and the model files they can load.

ComfyUI keeps history in memory only, since the server last started. The upload subfolder,
client id and output prefix use "krita3d" (the Photoshop plugin uses "photoshop3d"), so it is
clear on a shared ComfyUI server which program made which file.
"""
from __future__ import annotations

import json
import math
import random
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from ..http import HttpError, NetworkError, multipart
from .base import Configured, ModelResult, PollResult, Provider, ProviderContext, SubmitInput, SubmitResult, TestResult, lst, obj, s
from .comfy_workflows import (
    TRELLIS2_MODEL_ALTERNATIVES,
    TRELLIS2_MODEL_FILES,
    TRELLIS2_REQUIRED_NODES,
    build_trellis2_workflow,
    history_error,
    is_api_workflow,
    model_files_from_outputs,
    pick_model_file,
    prepare_custom_workflow,
    prompt_error,
)

UPLOAD_SUBFOLDER = "krita3d"
_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"
CLIENT_ID = "krita3d-" + "".join(random.choice(_BASE36) for _ in range(8))

#: Loader node and input that list the installed files, per TRELLIS.2 model slot.
TRELLIS2_LOADERS: Dict[str, Tuple[str, str]] = {
    "unet": ("UNETLoader", "unet_name"),
    "shapeVae": ("VAELoader", "vae_name"),
    "textureVae": ("VAELoader", "vae_name"),
    "clipVision": ("CLIPVisionLoader", "clip_name"),
    "backgroundRemoval": ("LoadBackgroundRemovalModel", "bg_removal_name"),
}

_MODEL_EXT = re.compile(r"\.(glb|gltf)$", re.I)


# ---------------------------------------------------------------- small helpers


def _uri(value: str) -> str:
    """encodeURIComponent()."""
    return quote(value, safe="!~*'()")


def _js_round(x: float) -> int:
    """Math.round(): halves go up (Python's round() goes to even)."""
    return int(math.floor(x + 0.5))


def _js_str(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return v if isinstance(v, str) else str(v)


def _truthy(v: Any) -> bool:
    """JavaScript truthiness: {} and [] count as present, 0 and "" do not."""
    if v is None or v is False:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v == v and v != 0
    if isinstance(v, str):
        return v != ""
    return True


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _base36(n: int) -> str:
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = _BASE36[r] + out
        if n == 0:
            return out


def _base(ctx: ProviderContext) -> str:
    return ctx.settings["comfyui"]["url"]


def view_url(base_url: str, f: Dict[str, str]) -> str:
    """Download URL of an output file."""
    query = {"filename": f["filename"], "subfolder": f["subfolder"], "type": f.get("type") or "output"}
    return f"{base_url}/view?" + "&".join(f"{k}={_uri(_js_str(v))}" for k, v in query.items())


def _queue_ids(items: Any) -> List[str]:
    """Prompt ids of /queue entries ([number, prompt_id, prompt, ...])."""
    return [_js_str(q[1]) if isinstance(q, list) and len(q) > 1 else "" for q in lst(items)]


def _new_seed(ctx: ProviderContext) -> int:
    seed = ctx.settings["comfyui"]["seed"]
    return seed if seed >= 0 else int(random.random() * 2**32)


def _get_history(ctx: ProviderContext, prompt_id: str) -> Optional[Dict[str, Any]]:
    body = obj(ctx.http.request_json(f"{_base(ctx)}/history/{_uri(prompt_id)}", timeout=20.0, label="ComfyUI"))
    entry = body.get(prompt_id)
    return obj(entry) if _truthy(entry) else None


def _start_timestamp(entry: Dict[str, Any]) -> Optional[float]:
    messages = obj(entry.get("status")).get("messages")
    if not isinstance(messages, list):
        return None
    for m in messages:
        if isinstance(m, list) and m and m[0] == "execution_start":
            stamp = obj(m[1] if len(m) > 1 else None).get("timestamp")
            if _is_number(stamp):
                return stamp
    return None


def _result_from_entry(ctx: ProviderContext, prompt_id: str, entry: Dict[str, Any]) -> Optional[ModelResult]:
    files = model_files_from_outputs(entry.get("outputs"))
    file = next((f for f in files if f["type"] == "output"), files[0] if files else None)
    if file is None:
        return None
    filename = file["filename"]
    subfolder = file["subfolder"]
    return ModelResult(
        model_url=view_url(_base(ctx), file),
        format="gltf" if re.search(r"\.gltf$", filename, re.I) else "glb",
        name=re.sub(r"_+$", "", _MODEL_EXT.sub("", filename)),
        created_at=_start_timestamp(entry),
        meta={"promptId": prompt_id, "file": f"{subfolder}/{filename}" if subfolder else filename},
    )


def _expected_seconds(ctx: ProviderContext) -> int:
    """Expected run time used for the progress estimate."""
    return 280 if ctx.settings["comfyui"]["workflow"] == "trellis2" else 180


# ---------------------------------------------------------------- TRELLIS.2 checks


def _node_defs(ctx: ProviderContext, names: Iterable[str]) -> Dict[str, Any]:
    """
    Node definitions from /object_info (a missing node answers {}). The Photoshop plugin asks for
    them in parallel; here they are fetched one after another (synchronous code).
    """
    defs: Dict[str, Any] = {}
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        try:
            defs.update(obj(ctx.http.request_json(f"{_base(ctx)}/object_info/{name}", timeout=15.0, label="ComfyUI")))
        except HttpError:
            pass
    return defs


def _combo_options(defs: Dict[str, Any], node: str, inp: str) -> List[str]:
    """Choices of a COMBO input: ["COMBO", {options}] (current) or [[...]] (older servers)."""
    spec = obj(obj(obj(defs.get(node)).get("input")).get("required")).get(inp)
    if not isinstance(spec, list):
        return []
    if spec and isinstance(spec[0], list):
        return spec[0]
    options = obj(spec[1] if len(spec) > 1 else None).get("options")
    return options if isinstance(options, list) else []


def resolve_trellis2_files(ctx: ProviderContext, defs: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, str], List[str]]:
    """
    The model files this ComfyUI has for each TRELLIS.2 slot (the template's file, also in a
    subfolder, or an accepted alternative), and the expected names of those it lacks. When a
    loader cannot be inspected, the template's name is assumed.
    """
    d = defs if defs is not None else _node_defs(ctx, [node for node, _ in TRELLIS2_LOADERS.values()])
    files = dict(TRELLIS2_MODEL_FILES)
    missing: List[str] = []
    for slot, (node, inp) in TRELLIS2_LOADERS.items():
        options = _combo_options(d, node, inp)
        if not options:
            # An installed loader with an empty list means no background-removal model at all.
            if slot == "backgroundRemoval" and node in d:
                missing.append(TRELLIS2_MODEL_FILES[slot])
            continue
        picked = pick_model_file(options, TRELLIS2_MODEL_FILES[slot], TRELLIS2_MODEL_ALTERNATIVES.get(slot))
        if picked:
            files[slot] = picked
            if picked != TRELLIS2_MODEL_FILES[slot]:
                ctx.log.info(f"ComfyUI TRELLIS.2: using {picked} for {slot}")
        else:
            missing.append(TRELLIS2_MODEL_FILES[slot])
    return files, missing


def check_trellis2_details(ctx: ProviderContext) -> Tuple[List[str], List[str]]:
    """
    What stops the built-in TRELLIS.2 workflow on this server: missing nodes or model files
    (`problems`, empty = ready), and the background-removal model, which only opaque images need
    (`warnings`). Returns (problems, warnings).
    """
    problems: List[str] = []
    warnings: List[str] = []
    defs = _node_defs(ctx, list(TRELLIS2_REQUIRED_NODES) + [node for node, _ in TRELLIS2_LOADERS.values()])
    missing_nodes = [n for n in TRELLIS2_REQUIRED_NODES if not _truthy(defs.get(n))]
    if missing_nodes:
        problems.append(f"update ComfyUI (missing nodes: {', '.join(missing_nodes)})")
    _, missing = resolve_trellis2_files(ctx, defs)
    bg = TRELLIS2_MODEL_FILES["backgroundRemoval"]
    required = [f for f in missing if f != bg]
    if required:
        problems.append(f"download model files: {', '.join(required)}")
    if bg in missing or not _truthy(defs.get("LoadBackgroundRemovalModel")):
        warnings.append(f"the background-removal model ({bg}) is missing, so only layers with transparency will work")
    return problems, warnings


def check_trellis2(ctx: ProviderContext) -> List[str]:
    """The problems part of check_trellis2_details (empty = ready)."""
    return check_trellis2_details(ctx)[0]


# ---------------------------------------------------------------- provider


class ComfyUIProvider(Provider):
    id = "comfyui"
    label = "ComfyUI (local)"
    can_cancel = True

    def is_configured(self, ctx: ProviderContext) -> Configured:
        c = ctx.settings["comfyui"]
        if c["workflow"] == "custom" and not is_api_workflow(c.get("customWorkflow")):
            return Configured(False, "Choose a ComfyUI workflow (API format) in Settings → ComfyUI.")
        return Configured(bool(c["url"]))

    def test(self, ctx: ProviderContext) -> TestResult:
        try:
            stats = obj(ctx.http.request_json(f"{_base(ctx)}/system_stats", timeout=8.0, label="ComfyUI"))
            system = obj(stats.get("system"))
            devices = stats.get("devices")
            device = obj(devices[0] if isinstance(devices, list) and devices else None)
            version = s(system.get("comfyui_version"))
            name = s(device.get("name"))
            # "cuda:0 NVIDIA GeForce RTX 3090 : cudaMallocAsync" → "NVIDIA GeForce RTX 3090"
            gpu = re.sub(r"^cuda:\d+\s*", "", name).split(" : ")[0] if name else None
            parts = [p for p in (f"ComfyUI {version or ''}".strip(), gpu) if p]
            joined = ", ".join(parts)
            if ctx.settings["comfyui"]["workflow"] == "trellis2":
                problems, warnings = check_trellis2_details(ctx)
                if problems:
                    return TestResult(False, f"Connected ({joined}), but TRELLIS.2 is not ready: {'; '.join(problems)}.")
                if warnings:
                    return TestResult(True, f"Connected: {joined}. Note: {'; '.join(warnings)}.")
            return TestResult(True, f"Connected: {joined}.")
        except Exception as err:  # noqa: BLE001 - every failure is reported in Settings
            return TestResult(False, f"{err}. Is ComfyUI running at {_base(ctx)}?")

    def submit(self, ctx: ProviderContext, inp: SubmitInput) -> SubmitResult:
        c = ctx.settings["comfyui"]
        base = _base(ctx)
        body, content_type = multipart(
            [
                {"name": "image", "value": inp.image, "filename": f"k3d-{_base36(int(ctx.now()))}.png", "content_type": "image/png"},
                {"name": "subfolder", "value": UPLOAD_SUBFOLDER},
                {"name": "type", "value": "input"},
                {"name": "overwrite", "value": "true"},
            ]
        )
        uploaded = obj(ctx.http.request_json(f"{base}/upload/image", "POST", headers={"Content-Type": content_type}, data=body, timeout=120.0, label="ComfyUI upload"))
        name = s(uploaded.get("name"))
        if not name:
            raise RuntimeError("ComfyUI upload returned no file name.")
        image = f"{uploaded['subfolder']}/{name}" if s(uploaded.get("subfolder")) else name

        seed = _new_seed(ctx)
        if c["workflow"] == "custom":
            if not is_api_workflow(c.get("customWorkflow")):
                raise RuntimeError("No custom ComfyUI workflow is set. Choose one in Settings → ComfyUI (save it with Workflow → Export (API)).")
            workflow = prepare_custom_workflow(c["customWorkflow"], image, c["imageNodeId"], seed)
        else:
            use_alpha_mask = inp.has_alpha and not c["removeBackground"]
            # If the loaders cannot be inspected, queue with the template's file names; ComfyUI's own
            # validation then names anything missing.
            files: Optional[Dict[str, str]]
            try:
                files, missing = resolve_trellis2_files(ctx)
            except Exception as err:  # noqa: BLE001 - only an optimisation; the queue still validates
                ctx.log.warn("ComfyUI: could not read the installed model files; using the template's names", str(err))
                files, missing = None, []
            bg = TRELLIS2_MODEL_FILES["backgroundRemoval"]
            if not use_alpha_mask and bg in missing:
                raise RuntimeError(
                    f"This image has no transparency, so ComfyUI must remove its background, but the background-removal model ({bg}) is not installed. "
                    "Cut the object out on a transparent layer, or install the model (Settings → ComfyUI → Test connection lists what is missing)."
                )
            workflow = build_trellis2_workflow(image=image, use_alpha_mask=use_alpha_mask, texture_size=c["textureSize"], face_count=c["faceCount"], seed=seed, files=files)

        # A raw request: a rejected prompt answers 400 with node_errors, which prompt_error explains.
        try:
            res = ctx.http.request(
                f"{base}/prompt",
                "POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"prompt": workflow, "client_id": CLIENT_ID}).encode("utf-8"),
                timeout=120.0,
                label="ComfyUI",
            )
        except NetworkError as err:
            cause = err.__cause__
            reason = (getattr(cause, "reason", None) or cause) if cause is not None else err
            raise RuntimeError(f"Cannot reach ComfyUI at {base} ({reason}).") from err
        text = res.text()
        answer: Any = text
        try:
            answer = json.loads(text)
        except ValueError:
            pass  # plain-text error
        if not res.ok:
            raise RuntimeError(prompt_error(answer))
        prompt_id = s(obj(answer).get("prompt_id"))
        if not prompt_id:
            raise RuntimeError("ComfyUI did not return a prompt id.")
        ctx.log.info(f"ComfyUI queued {c['workflow']} workflow", {"promptId": prompt_id, "seed": seed})
        return SubmitResult(prompt_id, {"workflow": c["workflow"], "submittedAt": ctx.now()})

    def poll(self, ctx: ProviderContext, remote_id: str, meta: Optional[Dict[str, Any]] = None) -> PollResult:
        entry = _get_history(ctx, remote_id)
        now = ctx.now()
        submitted_at = meta["submittedAt"] if meta and _is_number(meta.get("submittedAt")) else now
        if entry is not None:
            error = history_error(entry)
            if error:
                return PollResult("cancelled" if error.startswith("Cancelled") else "failed", error=error)
            status = obj(entry.get("status"))
            if status.get("completed") is False and status.get("status_str") != "success":
                return PollResult("running", message="ComfyUI is finishing")
            result = _result_from_entry(ctx, remote_id, entry)
            if result is not None:
                return PollResult("succeeded", progress=100, result=result)
            return PollResult("failed", error="The workflow finished but saved no .glb file. Add a Save GLB node to it.")

        queue = obj(ctx.http.request_json(f"{_base(ctx)}/queue", timeout=20.0, label="ComfyUI"))
        running = _queue_ids(queue.get("queue_running"))
        pending = _queue_ids(queue.get("queue_pending"))
        minutes = ctx.settings["comfyui"]["timeoutMinutes"]
        if now - submitted_at > minutes * 60_000:
            return PollResult("failed", error=f"ComfyUI did not finish within {minutes} minutes.")
        if remote_id in running:
            started_at = meta["startedAt"] if meta and _is_number(meta.get("startedAt")) else now
            elapsed = (now - started_at) / 1000
            progress = min(95, _js_round(elapsed / _expected_seconds(ctx) * 100))
            mm = int(math.floor(elapsed / 60))
            ss = str(int(math.floor(math.fmod(elapsed, 60)))).zfill(2)
            new_meta = dict(meta or {})
            new_meta["startedAt"] = started_at
            return PollResult("running", progress=progress, message=f"Running on ComfyUI ({mm}:{ss})", meta=new_meta)
        if remote_id in pending:
            position = pending.index(remote_id)
            return PollResult("queued", progress=0, message="Next in ComfyUI's queue" if position == 0 else f"{position} jobs ahead in ComfyUI's queue")
        # Not in history and not queued: ComfyUI restarted or the prompt was deleted.
        if now - submitted_at > 60_000:
            return PollResult("failed", error="ComfyUI no longer knows this job (was the server restarted?).")
        return PollResult("queued", message="Waiting for ComfyUI")

    def resolve(self, ctx: ProviderContext, remote_id: str, meta: Optional[Dict[str, Any]] = None) -> ModelResult:
        entry = _get_history(ctx, remote_id)
        if entry is None:
            raise RuntimeError("ComfyUI no longer has this job in its history.")
        result = _result_from_entry(ctx, remote_id, entry)
        if result is None:
            raise RuntimeError("This ComfyUI job has no .glb output.")
        return result

    def cancel(self, ctx: ProviderContext, remote_id: str, meta: Optional[Dict[str, Any]] = None) -> None:
        base = _base(ctx)
        try:
            # Cancels a queued job or interrupts it if it is the one running; harmless if it already finished.
            ctx.http.request_json(f"{base}/api/jobs/{_uri(remote_id)}/cancel", "POST", timeout=20.0, label="ComfyUI")
            return
        except HttpError as err:
            # 404/405: a ComfyUI before 0.26, which has no jobs cancel route.
            if err.status not in (404, 405):
                raise
        queue = obj(ctx.http.request_json(f"{base}/queue", timeout=20.0, label="ComfyUI"))
        headers = {"Content-Type": "application/json"}
        if remote_id in _queue_ids(queue.get("queue_running")):
            ctx.http.request_json(f"{base}/interrupt", "POST", headers=headers, json_body={"prompt_id": remote_id}, timeout=20.0, label="ComfyUI")
        else:
            ctx.http.request_json(f"{base}/queue", "POST", headers=headers, json_body={"delete": [remote_id]}, timeout=20.0, label="ComfyUI")
