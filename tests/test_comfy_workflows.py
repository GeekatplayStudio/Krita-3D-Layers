"""ComfyUI workflow helpers (ported from the Photoshop plugin's services.test.ts and latest-api.test.ts)."""
import json
import re

import pytest

from geekatplay_3d_layers.core.providers.comfy_workflows import (
    TRELLIS2_MODEL_ALTERNATIVES,
    TRELLIS2_MODEL_FILES,
    build_trellis2_workflow,
    history_error,
    image_node_candidates,
    is_api_workflow,
    is_ui_workflow,
    model_files_from_outputs,
    pick_image_node,
    pick_model_file,
    prepare_custom_workflow,
    prompt_error,
)


def _links_resolve(wf):
    for node in wf.values():
        for v in node["inputs"].values():
            if isinstance(v, list):
                assert v[0] in wf, json.dumps(v)


def test_builds_trellis2_with_birefnet_or_the_layers_alpha():
    bg = build_trellis2_workflow(image="a.png", use_alpha_mask=False, texture_size=1024, face_count=100000, seed=1)
    assert bg["192"]["class_type"] == "RemoveBackground"
    assert bg["312"]["inputs"]["masks"] == ["192", 0]
    assert "195" not in bg
    _links_resolve(bg)
    alpha = build_trellis2_workflow(image="a.png", use_alpha_mask=True, texture_size=4096, face_count=100000, seed=2**48 - 1)
    assert alpha["312"]["inputs"]["masks"] == ["195", 0]
    assert alpha["147"]["inputs"]["texture_size"] == 4096
    assert alpha["233"]["inputs"]["resolution"] == 2048
    assert alpha["18"]["inputs"]["seed"] == 0  # wraps instead of overflowing
    assert "192" not in alpha and "193" not in alpha
    # Every link points at a node that exists.
    _links_resolve(alpha)
    assert is_api_workflow(alpha)
    # The graph is JSON (it is posted as is).
    assert json.loads(json.dumps(alpha)) == alpha


def test_trellis2_uses_the_template_files_unless_told_otherwise():
    wf = build_trellis2_workflow(image="krita3d/x.png", use_alpha_mask=False, texture_size=2048, face_count=300000, seed=7)
    assert wf["122"]["inputs"]["image"] == "krita3d/x.png"
    assert wf["122"]["class_type"] == "LoadImage"
    assert wf["40"]["inputs"]["unet_name"] == TRELLIS2_MODEL_FILES["unet"]
    assert wf["117"]["inputs"]["vae_name"] == TRELLIS2_MODEL_FILES["shapeVae"]
    assert wf["118"]["inputs"]["vae_name"] == TRELLIS2_MODEL_FILES["textureVae"]
    assert wf["15"]["inputs"]["clip_name"] == TRELLIS2_MODEL_FILES["clipVision"]
    assert wf["193"]["inputs"]["bg_removal_name"] == TRELLIS2_MODEL_FILES["backgroundRemoval"]
    assert [wf[n]["inputs"]["seed"] for n in ("3", "18", "23", "12")] == [7, 8, 9, 10]
    assert wf["186"]["inputs"]["target_face_count"] == 300000
    assert wf["900"] == {"class_type": "SaveGLB", "_meta": {"title": "Save for Krita"}, "inputs": {"mesh": ["260", 0], "filename_prefix": "krita3d/trellis2"}}
    custom = build_trellis2_workflow(image="x.png", use_alpha_mask=True, texture_size=1024, face_count=1, seed=0, filename_prefix="krita/t", files={"unet": "trellis_2_bf16.safetensors"})
    assert custom["40"]["inputs"]["unet_name"] == "trellis_2_bf16.safetensors"
    assert custom["117"]["inputs"]["vae_name"] == TRELLIS2_MODEL_FILES["shapeVae"]
    assert custom["900"]["inputs"]["filename_prefix"] == "krita/t"


def test_finds_the_image_node_and_fills_custom_workflows():
    wf = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "x.png"}, "_meta": {"title": "Reference"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "y.png"}, "_meta": {"title": "Photoshop input"}},
        "3": {"class_type": "KSampler", "inputs": {"seed": 1, "noise_seed": 2}},
    }
    assert len(image_node_candidates(wf)) == 2
    assert image_node_candidates(wf)[0] == {"id": "1", "title": "Reference"}
    assert pick_image_node(wf, "") == "2"
    assert pick_image_node(wf, "1") == "1"
    prepared = prepare_custom_workflow(wf, "up.png", "", 42)
    assert prepared["2"]["inputs"]["image"] == "up.png"
    assert prepared["3"]["inputs"] == {"seed": 42, "noise_seed": 42}
    assert wf["2"]["inputs"]["image"] == "y.png"  # original untouched
    with pytest.raises(ValueError, match="no Load Image"):
        pick_image_node({"1": {"class_type": "KSampler", "inputs": {}}}, "")
    assert is_ui_workflow({"nodes": [], "links": []})
    assert not is_api_workflow({"nodes": []})


def test_image_node_choice_edge_cases():
    # The title falls back to the class type; the only candidate wins whatever its title.
    only = {"5": {"class_type": "LoadImageMask", "inputs": {"image": "m.png", "channel": "alpha"}}}
    assert image_node_candidates(only) == [{"id": "5", "title": "LoadImageMask"}]
    assert pick_image_node(only, "nope") == "5"
    # Nodes without a string image input are not candidates.
    assert image_node_candidates({"1": {"class_type": "LoadImage", "inputs": {"image": ["9", 0]}}}) == []
    two = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "a.png"}, "_meta": {"title": "A"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "b.png"}, "_meta": {"title": "B"}},
    }
    with pytest.raises(ValueError, match=re.escape("This workflow has 2 Load Image nodes (#1 A, #2 B). Pick one in Settings → ComfyUI.")):
        pick_image_node(two, "")
    # Booleans are not seeds.
    prepared = prepare_custom_workflow({"1": {"class_type": "LoadImage", "inputs": {"image": "a.png"}}, "2": {"class_type": "X", "inputs": {"seed": True, "noise_seed": "5"}}}, "u.png", "", 3)
    assert prepared["2"]["inputs"] == {"seed": True, "noise_seed": "5"}


def test_api_and_ui_workflow_detection():
    assert not is_api_workflow({})
    assert not is_api_workflow([{"class_type": "A", "inputs": {}}])
    assert not is_api_workflow(None)
    assert not is_api_workflow({"1": {"class_type": "A"}})
    assert not is_api_workflow({"1": {"class_type": 3, "inputs": {}}})
    assert is_api_workflow({"1": {"class_type": "A", "inputs": {}}})
    assert not is_ui_workflow({"nodes": []})
    assert not is_ui_workflow([])


def test_collects_3d_files_from_all_output_shapes():
    assert model_files_from_outputs(
        {
            "9": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]},
            "10": {"3d": [{"filename": "m.glb", "subfolder": "3d", "type": "output"}]},
            "11": {"result": ["sub/dir/old.gltf", {"camera": 1}]},
        }
    ) == [
        {"filename": "m.glb", "subfolder": "3d", "type": "output"},
        {"filename": "old.gltf", "subfolder": "sub/dir", "type": "output"},
    ]
    # Legacy "[output]" tags, backslashes, missing subfolder/type, and junk.
    assert model_files_from_outputs({"5": {"result": ["3d\\old_00001_.GLB [output]"]}, "6": {"3d": [{"filename": "x.glb"}]}, "7": None, "8": "text"}) == [
        {"filename": "old_00001_.GLB", "subfolder": "3d", "type": "output"},
        {"filename": "x.glb", "subfolder": "", "type": "output"},
    ]
    assert model_files_from_outputs(None) == [] and model_files_from_outputs("x") == []


def test_uses_the_model_files_that_are_installed():
    assert pick_model_file(["a.safetensors", "trellis/trellis_2_int8_convrot.safetensors"], "trellis_2_int8_convrot.safetensors") == "trellis/trellis_2_int8_convrot.safetensors"
    assert pick_model_file(["dino_v3_vit_l.safetensors"], "dino_v3_L_naf_fp32.safetensors", re.compile(r"^dino_v3.*\.safetensors$", re.I)) == "dino_v3_vit_l.safetensors"
    assert pick_model_file(["clip_vision_h.safetensors"], "dino_v3_L_naf_fp32.safetensors", re.compile(r"^dino_v3.*\.safetensors$", re.I)) is None
    # The exact name wins over the same name in a subfolder; VAEs are never taken for the diffusion model.
    assert pick_model_file(["x/birefnet.safetensors", "birefnet.safetensors"], "birefnet.safetensors") == "birefnet.safetensors"
    assert pick_model_file(["trellis_2_shape_vae_bf16.safetensors"], TRELLIS2_MODEL_FILES["unet"], TRELLIS2_MODEL_ALTERNATIVES["unet"]) is None
    assert pick_model_file(["models\\trellis_2_bf16.safetensors"], TRELLIS2_MODEL_FILES["unet"], TRELLIS2_MODEL_ALTERNATIVES["unet"]) == "models\\trellis_2_bf16.safetensors"


def test_history_errors():
    assert history_error({"status": {"status_str": "success"}}) is None
    assert history_error({}) is None and history_error(None) is None
    failed = {"status": {"status_str": "error", "messages": [["execution_start", {}], ["execution_error", {"node_type": "UNETLoader", "exception_message": " out of memory \n"}]]}}
    assert history_error(failed) == "UNETLoader: out of memory"
    assert history_error({"status": {"status_str": "error", "messages": [["execution_error", {}]]}}) == "Node: failed"
    assert history_error({"status": {"status_str": "error", "messages": [["execution_interrupted", {}]]}}) == "Cancelled in ComfyUI."
    assert history_error({"status": {"status_str": "error"}}) == "The ComfyUI workflow failed."


def test_prompt_errors():
    body = {"error": {"message": "Prompt outputs failed validation"}, "node_errors": {"40": {"class_type": "UNETLoader", "errors": [{"message": "Value not in list", "details": "unet_name: 'x' not in []"}, {"message": "Required input is missing"}]}}}
    assert prompt_error(body) == "Prompt outputs failed validation\nUNETLoader: Value not in list (unet_name: 'x' not in [])\nUNETLoader: Required input is missing"
    assert prompt_error("Internal Server Error") == "Internal Server Error"
    assert prompt_error({"error": "x"}) == "ComfyUI rejected the workflow."
    assert prompt_error(None) == "ComfyUI rejected the workflow."
