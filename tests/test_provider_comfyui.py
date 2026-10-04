"""ComfyUI provider (ported from the Photoshop plugin's providers.test.ts and latest-api.test.ts)."""
import re

import pytest

from geekatplay_3d_layers.core.http import HttpError, NetworkError
from geekatplay_3d_layers.core.providers.base import PollResult, SubmitInput
from geekatplay_3d_layers.core.providers.comfyui import CLIENT_ID, ComfyUIProvider, check_trellis2, check_trellis2_details, view_url
from helpers import PNG_1PX, ScriptedTransport, context, json_response, parse_multipart, route

BASE = "http://127.0.0.1:8188"
INPUT = SubmitInput(image=PNG_1PX, width=1, height=1, has_alpha=True, name="Chair")
OPAQUE = SubmitInput(image=PNG_1PX, width=1, height=1, has_alpha=False, name="Chair")
OBJECT_INFO = re.compile(r"/object_info/(\w+)$")
comfyui = ComfyUIProvider()


def _combo(options):
    return ["COMBO", {"options": options}]


#: A ComfyUI with a different diffusion model, an older-style DINOv3 list and no BiRefNet file.
DEFS = {
    "UNETLoader": {"input": {"required": {"unet_name": _combo(["trellis_2_bf16.safetensors"])}}},
    "VAELoader": {"input": {"required": {"vae_name": _combo(["trellis_2_shape_vae_bf16.safetensors", "trellis_2_texture_vae_bf16.safetensors"])}}},
    "CLIPVisionLoader": {"input": {"required": {"clip_name": [["dino_v3_vit_l.safetensors"]]}}},
    "LoadBackgroundRemovalModel": {"input": {"required": {"bg_removal_name": _combo([])}}},
}


def _object_info(defs, fallback=None):
    """/object_info/<node> answering from `defs`; a missing node answers {} (or `fallback`)."""

    def reply(call):
        name = OBJECT_INFO.search(call.url).group(1)
        if name in defs:
            return json_response({name: defs[name]})
        return json_response({name: fallback} if fallback is not None else {})

    return route("GET", OBJECT_INFO, reply)


def _capture_prompt(store, answer=None):
    def reply(call):
        body = call.json()
        store["prompt"] = body["prompt"]
        store["client_id"] = body["client_id"]
        store["content_type"] = call.headers.get("content-type")
        return json_response(answer or {"prompt_id": "p1", "number": 1, "node_errors": {}})

    return route("POST", f"{BASE}/prompt", reply)


def test_uploads_queues_trellis2_with_the_alpha_mask_and_finds_the_glb():
    queued = {}
    t = ScriptedTransport([route("POST", f"{BASE}/upload/image", json_response({"name": "k3d-x.png", "subfolder": "krita3d", "type": "input"})), _capture_prompt(queued)])
    ctx = context(t, {"comfyui": {"seed": 7}})
    res = comfyui.submit(ctx, INPUT)
    assert res.remote_id == "p1"
    assert res.meta == {"workflow": "trellis2", "submittedAt": 1_790_000_000_000}
    wf = queued["prompt"]
    assert wf["122"]["inputs"]["image"] == "krita3d/k3d-x.png"
    assert wf["195"]["class_type"] == "InvertMask"
    assert "192" not in wf
    assert wf["3"]["inputs"]["seed"] == 7
    assert wf["900"]["class_type"] == "SaveGLB"
    assert queued["client_id"] == CLIENT_ID and CLIENT_ID.startswith("krita3d-")
    assert queued["content_type"] == "application/json"
    # The upload layout ComfyUI expects.
    upload = t.calls[0]
    form = parse_multipart(upload.body, upload.headers["content-type"])
    assert form["fields"] == {"subfolder": "krita3d", "type": "input", "overwrite": "true"}
    assert re.fullmatch(r"k3d-[0-9a-z]+\.png", form["files"]["image"]["filename"])
    assert form["files"]["image"]["bytes"] == PNG_1PX
    assert 'Content-Type: image/png' in upload.body.decode("latin1")
    # The model files could not be read here (no /object_info route), so the template's names were used.
    assert wf["40"]["inputs"]["unet_name"] == "trellis_2_int8_convrot.safetensors"
    assert any("could not read the installed model files" in line for line in ctx.log.lines)


def test_opaque_images_and_remove_background_use_birefnet():
    queued = {}
    t = ScriptedTransport([route("POST", f"{BASE}/upload/image", json_response({"name": "a.png", "subfolder": " "})), _capture_prompt(queued)])
    comfyui.submit(context(t), OPAQUE)
    assert queued["prompt"]["122"]["inputs"]["image"] == "a.png"  # a blank subfolder is ignored
    assert queued["prompt"]["192"]["class_type"] == "RemoveBackground"
    assert "195" not in queued["prompt"]
    comfyui.submit(context(t, {"comfyui": {"removeBackground": True}}), INPUT)
    assert queued["prompt"]["312"]["inputs"]["masks"] == ["192", 0]
    seeds = {queued["prompt"]["3"]["inputs"]["seed"]}
    comfyui.submit(context(t), INPUT)
    seeds.add(queued["prompt"]["3"]["inputs"]["seed"])
    assert all(0 <= x < 2**32 for x in seeds)


def test_reports_comfyui_validation_errors_readably():
    t = ScriptedTransport(
        [
            route("POST", f"{BASE}/upload/image", json_response({"name": "a.png"})),
            route(
                "POST",
                f"{BASE}/prompt",
                json_response({"error": {"message": "Prompt outputs failed validation"}, "node_errors": {"40": {"class_type": "UNETLoader", "errors": [{"message": "Value not in list", "details": "unet_name: 'trellis' not in []"}]}}}, 400),
            ),
        ]
    )
    with pytest.raises(RuntimeError, match="UNETLoader: Value not in list") as err:
        comfyui.submit(context(t), INPUT)
    assert str(err.value) == "Prompt outputs failed validation\nUNETLoader: Value not in list (unet_name: 'trellis' not in [])"
    plain = ScriptedTransport([route("POST", f"{BASE}/upload/image", json_response({"name": "a.png"})), route("POST", f"{BASE}/prompt", json_response("Server busy", 500))])
    with pytest.raises(RuntimeError, match="^Server busy$"):
        comfyui.submit(context(plain), INPUT)
    no_id = ScriptedTransport([route("POST", f"{BASE}/upload/image", json_response({"name": "a.png"})), route("POST", f"{BASE}/prompt", json_response({"number": 1}))])
    with pytest.raises(RuntimeError, match="did not return a prompt id"):
        comfyui.submit(context(no_id), INPUT)
    no_name = ScriptedTransport([route("POST", f"{BASE}/upload/image", json_response({}))])
    with pytest.raises(RuntimeError, match="upload returned no file name"):
        comfyui.submit(context(no_name), INPUT)


def test_cannot_reach_comfyui_names_the_address():
    def refused(call):
        raise ConnectionRefusedError("connection refused")

    t = ScriptedTransport([route("POST", f"{BASE}/upload/image", json_response({"name": "a.png"})), route("POST", f"{BASE}/prompt", refused)])
    with pytest.raises(RuntimeError, match=re.escape(f"Cannot reach ComfyUI at {BASE} (connection refused).")):
        comfyui.submit(context(t), INPUT)
    down = ScriptedTransport([route("POST", f"{BASE}/upload/image", refused)])
    with pytest.raises(NetworkError, match="ComfyUI upload: cannot reach 127.0.0.1:8188"):
        comfyui.submit(context(down), INPUT)


def test_queues_custom_workflows():
    wf = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "old.png"}, "_meta": {"title": "Photoshop input"}},
        "2": {"class_type": "KSampler", "inputs": {"seed": 1}},
        "3": {"class_type": "SaveGLB", "inputs": {"filename_prefix": "x"}},
    }
    queued = {}
    t = ScriptedTransport([route("POST", f"{BASE}/upload/image", json_response({"name": "a.png", "subfolder": "krita3d"})), _capture_prompt(queued)])
    ctx = context(t, {"comfyui": {"workflow": "custom", "customWorkflow": wf, "seed": 99}})
    assert comfyui.is_configured(ctx).configured
    res = comfyui.submit(ctx, INPUT)
    assert res.meta["workflow"] == "custom"
    assert queued["prompt"]["1"]["inputs"]["image"] == "krita3d/a.png"
    assert queued["prompt"]["2"]["inputs"]["seed"] == 99
    assert not any("/object_info/" in c.url for c in t.calls)
    empty = context(t, {"comfyui": {"workflow": "custom"}})
    assert comfyui.is_configured(empty).configured is False
    assert comfyui.is_configured(empty).hint == "Choose a ComfyUI workflow (API format) in Settings → ComfyUI."
    with pytest.raises(RuntimeError, match="No custom ComfyUI workflow is set"):
        comfyui.submit(empty, INPUT)
    assert comfyui.is_configured(context(t)).configured


def test_polls_queue_position_running_time_and_the_finished_output():
    clock = [1_000_000]
    state = {"history": {}, "queue": {"queue_running": [], "queue_pending": [[1, "other"], [2, "p1"]]}}
    t = ScriptedTransport([route("GET", f"{BASE}/history/p1", lambda call: json_response(state["history"])), route("GET", f"{BASE}/queue", lambda call: json_response(state["queue"]))])
    ctx = context(t)
    ctx.now = lambda: clock[0]
    first = comfyui.poll(ctx, "p1", {"submittedAt": clock[0]})
    assert (first.state, first.progress, first.message) == ("queued", 0, "1 jobs ahead in ComfyUI's queue")
    state["queue"] = {"queue_running": [], "queue_pending": [[2, "p1"]]}
    assert comfyui.poll(ctx, "p1", {"submittedAt": clock[0]}).message == "Next in ComfyUI's queue"
    state["queue"] = {"queue_running": [[2, "p1"]], "queue_pending": []}
    running = comfyui.poll(ctx, "p1", {"submittedAt": clock[0]})
    assert (running.state, running.progress, running.message) == ("running", 0, "Running on ComfyUI (0:00)")
    assert running.meta == {"submittedAt": 1_000_000, "startedAt": 1_000_000}
    clock[0] += 140_000
    later = comfyui.poll(ctx, "p1", running.meta)
    assert (later.progress, later.message) == (50, "Running on ComfyUI (2:20)")
    state["history"] = {
        "p1": {
            "status": {"status_str": "success", "completed": True, "messages": [["execution_start", {"timestamp": 5}]]},
            "outputs": {"900": {"3d": [{"filename": "trellis2_00001_.glb", "subfolder": "krita3d", "type": "output"}]}},
        }
    }
    done = comfyui.poll(ctx, "p1", later.meta)
    assert (done.state, done.progress) == ("succeeded", 100)
    assert done.result.model_url == f"{BASE}/view?filename=trellis2_00001_.glb&subfolder=krita3d&type=output"
    assert (done.result.format, done.result.name, done.result.created_at) == ("glb", "trellis2_00001", 5)
    assert done.result.meta == {"promptId": "p1", "file": "krita3d/trellis2_00001_.glb"}


def test_progress_is_capped_and_custom_workflows_expect_three_minutes():
    clock = [10_000_000]
    t = ScriptedTransport([route("GET", f"{BASE}/history/p1", json_response({})), route("GET", f"{BASE}/queue", json_response({"queue_running": [[0, "p1", {}]], "queue_pending": []}))])
    ctx = context(t, {"comfyui": {"workflow": "custom", "customWorkflow": {"1": {"class_type": "LoadImage", "inputs": {"image": "a"}}}}})
    ctx.now = lambda: clock[0]
    assert comfyui.poll(ctx, "p1", {"submittedAt": clock[0] - 1000, "startedAt": clock[0] - 90_000}).progress == 50
    assert comfyui.poll(ctx, "p1", {"submittedAt": clock[0] - 1000, "startedAt": clock[0] - 600_000}).progress == 95


def test_poll_timeouts_lost_jobs_and_failures():
    clock = [50_000_000]
    history = {"value": {}}
    t = ScriptedTransport([route("GET", f"{BASE}/history/p1", lambda call: json_response(history["value"])), route("GET", f"{BASE}/queue", json_response({"queue_running": [[1, "p1"]], "queue_pending": []}))])
    ctx = context(t, {"comfyui": {"timeoutMinutes": 2}})
    ctx.now = lambda: clock[0]
    assert comfyui.poll(ctx, "p1", {"submittedAt": clock[0] - 121_000}) == PollResult("failed", error="ComfyUI did not finish within 2 minutes.")
    t.routes[1] = route("GET", f"{BASE}/queue", json_response({"queue_running": [], "queue_pending": []}))
    assert comfyui.poll(ctx, "p1", {"submittedAt": clock[0] - 30_000}) == PollResult("queued", message="Waiting for ComfyUI")
    assert comfyui.poll(ctx, "p1", {"submittedAt": clock[0] - 61_000}) == PollResult("failed", error="ComfyUI no longer knows this job (was the server restarted?).")
    history["value"] = {"p1": {"status": {"status_str": "error", "messages": [["execution_error", {"node_type": "DecimateMesh", "exception_message": "CUDA out of memory"}]]}}}
    assert comfyui.poll(ctx, "p1") == PollResult("failed", error="DecimateMesh: CUDA out of memory")
    history["value"] = {"p1": {"status": {"status_str": "error", "messages": [["execution_interrupted", {}]]}}}
    assert comfyui.poll(ctx, "p1") == PollResult("cancelled", error="Cancelled in ComfyUI.")
    history["value"] = {"p1": {"status": {"status_str": "running", "completed": False}, "outputs": {}}}
    assert comfyui.poll(ctx, "p1") == PollResult("running", message="ComfyUI is finishing")
    history["value"] = {"p1": {"status": {"status_str": "success", "completed": True}, "outputs": {"9": {"images": [{"filename": "a.png"}]}}}}
    assert comfyui.poll(ctx, "p1") == PollResult("failed", error="The workflow finished but saved no .glb file. Add a Save GLB node to it.")
    # An empty entry still counts as known (as {} is truthy in the Photoshop plugin).
    history["value"] = {"p1": {}}
    assert comfyui.poll(ctx, "p1").state == "failed"


def test_resolves_fresh_urls_from_history():
    entry = {"status": {"status_str": "success", "completed": True}, "outputs": {"5": {"3d": [{"filename": "a b.gltf", "subfolder": "", "type": "temp"}, {"filename": "m_00002_.glb", "subfolder": "3d", "type": "output"}]}}}
    t = ScriptedTransport([route("GET", f"{BASE}/history/p%2F1", json_response({"p/1": entry})), route("GET", f"{BASE}/history/gone", json_response({})), route("GET", f"{BASE}/history/none", json_response({"none": {"outputs": {}}}))])
    ctx = context(t)
    res = comfyui.resolve(ctx, "p/1")
    # The first file of type "output" wins.
    assert res.model_url == f"{BASE}/view?filename=m_00002_.glb&subfolder=3d&type=output"
    assert (res.name, res.meta["file"]) == ("m_00002", "3d/m_00002_.glb")
    with pytest.raises(RuntimeError, match="no longer has this job"):
        comfyui.resolve(ctx, "gone")
    with pytest.raises(RuntimeError, match="has no .glb output"):
        comfyui.resolve(ctx, "none")
    assert view_url(BASE, {"filename": "a b&c.gltf", "subfolder": "x/y", "type": ""}) == f"{BASE}/view?filename=a%20b%26c.gltf&subfolder=x%2Fy&type=output"


def test_cancels_through_the_jobs_api_and_the_old_routes_on_older_servers():
    modern = ScriptedTransport([route("POST", f"{BASE}/api/jobs/p1/cancel", json_response({"cancelled": True}))])
    comfyui.cancel(context(modern), "p1")
    assert [c.url for c in modern.calls] == [f"{BASE}/api/jobs/p1/cancel"]

    old = ScriptedTransport(
        [
            route("POST", f"{BASE}/api/jobs/p1/cancel", json_response({"error": "Not Found"}, 404)),
            route("GET", f"{BASE}/queue", json_response({"queue_running": [[1, "p1"]], "queue_pending": []})),
            route("POST", f"{BASE}/interrupt", json_response({})),
        ]
    )
    comfyui.cancel(context(old), "p1")
    assert [f"{c.method} {c.url.replace(BASE, '')}" for c in old.calls] == ["POST /api/jobs/p1/cancel", "GET /queue", "POST /interrupt"]
    assert old.calls[2].json() == {"prompt_id": "p1"}

    queued = ScriptedTransport(
        [
            route("POST", f"{BASE}/api/jobs/p1/cancel", json_response("405: Method Not Allowed", 405)),
            route("GET", f"{BASE}/queue", json_response({"queue_running": [], "queue_pending": [[1, "p1"]]})),
            route("POST", f"{BASE}/queue", json_response({})),
        ]
    )
    comfyui.cancel(context(queued), "p1")
    assert queued.calls[-1].json() == {"delete": ["p1"]}
    assert queued.calls[-1].headers["content-type"] == "application/json"

    broken = ScriptedTransport([route("POST", f"{BASE}/api/jobs/p1/cancel", json_response({"error": "boom"}, 500))])
    with pytest.raises(HttpError):
        comfyui.cancel(context(broken), "p1")
    assert comfyui.can_cancel


def test_uses_the_model_files_that_are_installed():
    queued = {}
    t = ScriptedTransport([_object_info(DEFS), route("POST", f"{BASE}/upload/image", json_response({"name": "x.png", "subfolder": "krita3d"})), _capture_prompt(queued, {"prompt_id": "p1"})])
    ctx = context(t)
    comfyui.submit(ctx, INPUT)
    assert queued["prompt"]["40"]["inputs"]["unet_name"] == "trellis_2_bf16.safetensors"
    assert queued["prompt"]["15"]["inputs"]["clip_name"] == "dino_v3_vit_l.safetensors"
    assert queued["prompt"]["117"]["inputs"]["vae_name"] == "trellis_2_shape_vae_bf16.safetensors"
    assert any("using trellis_2_bf16.safetensors for unet" in line for line in ctx.log.lines)
    # Each loader is asked once, even though VAELoader serves two slots.
    asked = [c.url for c in t.calls if "/object_info/" in c.url]
    assert asked == [f"{BASE}/object_info/{n}" for n in ("UNETLoader", "VAELoader", "CLIPVisionLoader", "LoadBackgroundRemovalModel")]
    # An opaque image needs BiRefNet, which is not installed here.
    with pytest.raises(RuntimeError, match=r"background-removal model \(birefnet\.safetensors\) is not installed"):
        comfyui.submit(ctx, OPAQUE)
    # The TRELLIS.2 nodes are missing from this fake server, but the files are not reported missing.
    problems = check_trellis2(ctx)
    assert not re.search("download model files", "; ".join(problems))
    assert problems == ["update ComfyUI (missing nodes: Trellis2Conditioning, Trellis2ShapeStage, Trellis2UpsampleStage, Trellis2TextureStage, VaeDecodeShapeTrellis, VaeDecodeTextureTrellis, BakeTextureFromVoxel, SaveGLB)"]
    test = comfyui.test(
        context(
            ScriptedTransport(
                [
                    route("GET", f"{BASE}/system_stats", json_response({"system": {"comfyui_version": "0.38.0"}, "devices": []})),
                    _object_info(DEFS, fallback={"input": {"required": {}}}),
                ]
            )
        )
    )
    assert test.ok
    assert re.search(r"Note: the background-removal model \(birefnet\.safetensors\) is missing", test.message)
    assert test.message == "Connected: ComfyUI 0.38.0. Note: the background-removal model (birefnet.safetensors) is missing, so only layers with transparency will work."


def test_reports_version_gpu_and_what_trellis2_lacks():
    stats = {"system": {"comfyui_version": "0.38.0"}, "devices": [{"name": "cuda:0 NVIDIA GeForce RTX 3090 : cudaMallocAsync", "type": "cuda"}]}
    # Every node present, but no model files at all.
    empty = {name: {"input": {"required": {}}} for name in DEFS}
    empty["UNETLoader"] = {"input": {"required": {"unet_name": _combo(["sd_xl.safetensors"])}}}
    t = ScriptedTransport([route("GET", f"{BASE}/system_stats", json_response(stats)), _object_info(empty, fallback={"input": {}})])
    res = comfyui.test(context(t))
    assert not res.ok
    assert res.message == "Connected (ComfyUI 0.38.0, NVIDIA GeForce RTX 3090), but TRELLIS.2 is not ready: download model files: trellis_2_int8_convrot.safetensors."
    problems, warnings = check_trellis2_details(context(t))
    assert warnings == ["the background-removal model (birefnet.safetensors) is missing, so only layers with transparency will work"]
    # A custom workflow skips the TRELLIS.2 checks.
    custom = context(t, {"comfyui": {"workflow": "custom"}})
    assert comfyui.test(custom).message == "Connected: ComfyUI 0.38.0, NVIDIA GeForce RTX 3090."
    # Everything installed: no note.
    full = dict(DEFS)
    full["UNETLoader"] = {"input": {"required": {"unet_name": _combo(["trellis/trellis_2_int8_convrot.safetensors"])}}}
    full["CLIPVisionLoader"] = {"input": {"required": {"clip_name": _combo(["dino_v3_L_naf_fp32.safetensors"])}}}
    full["LoadBackgroundRemovalModel"] = {"input": {"required": {"bg_removal_name": _combo(["birefnet.safetensors"])}}}
    ready = ScriptedTransport([route("GET", f"{BASE}/system_stats", json_response({"system": {}, "devices": [{"name": "cpu"}]})), _object_info(full, fallback={"input": {}})])
    assert comfyui.test(context(ready)).message == "Connected: ComfyUI, cpu."


def test_a_server_that_is_down_or_old():
    def refused(call):
        raise ConnectionRefusedError("refused")

    res = comfyui.test(context(ScriptedTransport([route("GET", "http://192.168.1.5:8188/system_stats", refused)]), {"comfyui": {"url": "192.168.1.5:8188"}}))
    assert not res.ok
    assert res.message.startswith("ComfyUI: cannot reach 192.168.1.5:8188")
    assert res.message.endswith(". Is ComfyUI running at http://192.168.1.5:8188?")
    # /object_info/<node> answering 404 (old server) is a missing node, not a failure.
    old = ScriptedTransport([route("GET", f"{BASE}/system_stats", json_response({"system": {"comfyui_version": "0.3.10"}})), route("GET", OBJECT_INFO, json_response({"error": "nope"}, 404))])
    res = comfyui.test(context(old))
    assert not res.ok and "update ComfyUI (missing nodes: Trellis2Conditioning" in res.message
    assert "download model files" not in res.message
