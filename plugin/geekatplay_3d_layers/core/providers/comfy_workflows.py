"""
ComfyUI workflows for image → 3D, as pure functions (no I/O) so they are unit-tested
(a port of the Photoshop plugin's src/host/providers/comfyWorkflows.ts).

Built-in: TRELLIS.2 (native nodes, ComfyUI ≥ 0.34). The graph is the Comfy-Org template
"3d_pixal3d_trellis2_image_to_model" reduced to its TRELLIS.2 branch, with the template's
Save3DAdvanced (whose required viewport_state comes from the frontend's 3D viewer) replaced
by core SaveGLB. Node names and inputs were checked against ComfyUI 0.38's /object_info and
the template on 2026-10-02. Verified on ComfyUI 0.38 / RTX 3090: ~4.5 min, ~30 MB textured GLB.

Custom: any API-format workflow (ComfyUI → Workflow → Export (API)) with a LoadImage node
and a node that saves a .glb/.gltf (SaveGLB, Save3DAdvanced, or a custom node).

Workflows are plain dicts in ComfyUI's API format: {node_id: {"class_type", "inputs", "_meta"}}.
Files found in outputs are dicts {"filename", "subfolder", "type"}.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, Iterable, List, Optional, Pattern, Sequence

from .base import lst, obj

TRELLIS2_REQUIRED_NODES = (
    "Trellis2Conditioning",
    "Trellis2ShapeStage",
    "Trellis2UpsampleStage",
    "Trellis2TextureStage",
    "VaeDecodeShapeTrellis",
    "VaeDecodeTextureTrellis",
    "BakeTextureFromVoxel",
    "SaveGLB",
)

#: The template's model file per loader slot (slot names as in the Photoshop plugin).
TRELLIS2_MODEL_FILES: Dict[str, str] = {
    "unet": "trellis_2_int8_convrot.safetensors",
    "shapeVae": "trellis_2_shape_vae_bf16.safetensors",
    "textureVae": "trellis_2_texture_vae_bf16.safetensors",
    "clipVision": "dino_v3_L_naf_fp32.safetensors",
    "backgroundRemoval": "birefnet.safetensors",
}

#: Accepted substitutes when the template's file is not installed (docs.comfy.org TRELLIS.2 tutorial).
TRELLIS2_MODEL_ALTERNATIVES: Dict[str, Pattern[str]] = {
    "unet": re.compile(r"^trellis_2(?!.*vae).*\.safetensors$", re.I),
    "clipVision": re.compile(r"^dino_v3.*\.safetensors$", re.I),
    "backgroundRemoval": re.compile(r"\.safetensors$", re.I),
}

TRELLIS2_IMAGE_NODE = "122"
SAVE_NODE = "900"

_MODEL_EXT = re.compile(r"\.(glb|gltf)$", re.I)
_OUTPUT_TAG = re.compile(r"\s*\[(output|input|temp)\]$")


def _js_str(v: Any) -> str:
    """String(v) as JavaScript writes it, so messages read the same as in the Photoshop plugin."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return v if isinstance(v, str) else str(v)


def _values(v: Any) -> Iterable[Any]:
    """Object.values(): dict values or list items."""
    if isinstance(v, dict):
        return list(v.values())
    if isinstance(v, list):
        return v
    return []


def _basename(path: str) -> str:
    return re.split(r"[\\/]", path)[-1]


def pick_model_file(options: Sequence[str], preferred: str, alternative: Optional[Pattern[str]] = None) -> Optional[str]:
    """
    Picks the installed file for a model slot from a loader's options: the expected name (also
    inside a subfolder, e.g. "trellis/trellis_2_int8_convrot.safetensors"), else an accepted
    alternative. None when neither is installed.
    """
    for o in options:
        if o == preferred:
            return o
    for o in options:
        if _basename(o) == preferred:
            return o
    if alternative is not None:
        for o in options:
            if alternative.search(_basename(o)):
                return o
    return None


def build_trellis2_workflow(
    image: str,
    use_alpha_mask: bool,
    texture_size: int,
    face_count: int,
    seed: int,
    filename_prefix: Optional[str] = None,
    files: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    The TRELLIS.2 graph in API format.

    `image` is the ComfyUI input name ("krita3d/layer.png"). `use_alpha_mask` uses the
    layer's transparency as the object mask instead of BiRefNet. `files` are the installed model
    files (see pick_model_file); missing slots use the template's names.
    """
    f = dict(TRELLIS2_MODEL_FILES)
    f.update(files or {})

    def seed_at(offset: int) -> int:
        # ComfyUI seeds are at most 48 bits; wrap instead of overflowing.
        return (seed + offset) % 2**48

    wf: Dict[str, Any] = {
        "122": {"class_type": "LoadImage", "_meta": {"title": "Krita Image"}, "inputs": {"image": image}},
        "15": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": f["clipVision"]}},
        "312": {
            "class_type": "ImageCropToMask",
            "inputs": {"images": ["122", 0], "masks": ["195", 0] if use_alpha_mask else ["192", 0], "width": 1024, "height": 1024, "pad_factor": 1.1, "grow_mask": 0, "background": "#000000"},
        },
        "299": {"class_type": "Trellis2Conditioning", "inputs": {"clip_vision_model": ["15", 0], "image": ["312", 0]}},
        "40": {"class_type": "UNETLoader", "inputs": {"unet_name": f["unet"], "weight_dtype": "default"}},
        "199": {"class_type": "CFGOverride", "inputs": {"model": ["40", 0], "cfg": 1, "start_percent": 0.667, "end_percent": 1}},
        "125": {"class_type": "RescaleCFG", "inputs": {"model": ["199", 0], "multiplier": 0.7}},
        "108": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["125", 0], "shift": 5}},
        "87": {"class_type": "EmptyTrellis2LatentStructure", "inputs": {"batch_size": 1}},
        "3": {
            "class_type": "KSampler",
            "_meta": {"title": "Structure Sampler"},
            "inputs": {"model": ["108", 0], "seed": seed_at(0), "steps": 12, "cfg": 7.5, "sampler_name": "euler", "scheduler": "normal", "positive": ["299", 0], "negative": ["299", 1], "latent_image": ["87", 0], "denoise": 1},
        },
        "117": {"class_type": "VAELoader", "inputs": {"vae_name": f["shapeVae"]}},
        "119": {"class_type": "VaeDecodeStructureTrellis2", "inputs": {"samples": ["3", 0], "vae": ["117", 0], "resolution": "32"}},
        "91": {"class_type": "Trellis2ShapeStage", "inputs": {"positive": ["299", 0], "negative": ["299", 1], "voxel": ["119", 0]}},
        "279": {"class_type": "CFGOverride", "inputs": {"model": ["40", 0], "cfg": 1, "start_percent": 0.769, "end_percent": 1}},
        "126": {"class_type": "RescaleCFG", "inputs": {"model": ["279", 0], "multiplier": 0.5}},
        "18": {
            "class_type": "KSampler",
            "_meta": {"title": "Shape Sampler"},
            "inputs": {"model": ["126", 0], "seed": seed_at(1), "steps": 20, "cfg": 7.5, "sampler_name": "euler", "scheduler": "normal", "positive": ["91", 0], "negative": ["91", 1], "latent_image": ["91", 2], "denoise": 1},
        },
        "94": {"class_type": "Trellis2UpsampleStage", "inputs": {"positive": ["91", 0], "negative": ["91", 1], "shape_latent": ["18", 0], "vae": ["117", 0], "target_resolution": 1536}},
        "23": {
            "class_type": "KSampler",
            "_meta": {"title": "Upsample Sampler"},
            "inputs": {"model": ["126", 0], "seed": seed_at(2), "steps": 12, "cfg": 7.5, "sampler_name": "euler", "scheduler": "simple", "positive": ["94", 0], "negative": ["94", 1], "latent_image": ["94", 2], "denoise": 1},
        },
        "92": {"class_type": "VaeDecodeShapeTrellis", "inputs": {"samples": ["23", 0], "vae": ["117", 0]}},
        "98": {"class_type": "Trellis2TextureStage", "inputs": {"positive": ["94", 0], "negative": ["94", 1], "shape_latent": ["23", 0]}},
        "12": {
            "class_type": "KSampler",
            "_meta": {"title": "Texture Sampler"},
            "inputs": {"model": ["40", 0], "seed": seed_at(3), "steps": 12, "cfg": 1, "sampler_name": "euler", "scheduler": "normal", "positive": ["98", 0], "negative": ["98", 1], "latent_image": ["98", 2], "denoise": 1},
        },
        "118": {"class_type": "VAELoader", "inputs": {"vae_name": f["textureVae"]}},
        "93": {"class_type": "VaeDecodeTextureTrellis", "inputs": {"samples": ["12", 0], "vae": ["118", 0], "shape_subdivides": ["92", 1]}},
        "241": {
            "class_type": "RemeshMesh",
            "inputs": {
                "mesh": ["92", 0],
                "resolution": 768,
                "sign_mode": "udf",
                "sign_mode.qef": False,
                "sign_mode.drop_inverted_components": False,
                "sign_mode.drop_enclosed_components": False,
                "band": 1,
                "project_back": 0,
                "fix_poles": False,
                "smooth_iters": 20,
                "drop_small_components": 0.01,
                "precluster_max_verts": 20000000,
            },
        },
        "186": {"class_type": "DecimateMesh", "inputs": {"mesh": ["241", 0], "target_face_count": face_count, "placement_mode": "midpoint"}},
        "238": {"class_type": "MeshSmoothNormals", "inputs": {"mesh": ["186", 0], "crease_angle": 180}},
        "196": {"class_type": "UnwrapMesh", "inputs": {"mesh": ["238", 0], "segmenter": "pec", "resolution": texture_size, "padding": 1, "weld_distance": 0.0002}},
        "147": {"class_type": "BakeTextureFromVoxel", "inputs": {"mesh": ["196", 0], "voxel_colors": ["93", 0], "texture_size": texture_size, "reference_mesh": ["92", 0]}},
        "224": {"class_type": "BakeNormalMapFromMesh", "inputs": {"low_poly": ["196", 0], "high_poly": ["241", 0], "resolution": texture_size, "cage_distance": 0.05, "ignore_backfaces": True}},
        "233": {
            "class_type": "BakeAmbientOcclusion",
            "inputs": {"low_poly": ["196", 0], "high_poly": ["241", 0], "resolution": min(texture_size, 2048), "samples": 64, "max_distance": 0.71, "strength": 1, "bias": 0.01},
        },
        "210": {"class_type": "ApplyTextureToMesh", "inputs": {"mesh": ["196", 0], "base_color": ["147", 0], "metallic": ["147", 1], "roughness": ["147", 2], "occlusion": ["233", 0], "normal_map": ["224", 0]}},
        "260": {"class_type": "MeshSmoothNormals", "inputs": {"mesh": ["210", 0], "crease_angle": 180}},
        SAVE_NODE: {"class_type": "SaveGLB", "_meta": {"title": "Save for Krita"}, "inputs": {"mesh": ["260", 0], "filename_prefix": filename_prefix if filename_prefix is not None else "krita3d/trellis2"}},
    }
    if use_alpha_mask:
        # LoadImage outputs 1 - alpha as its mask; invert it to get the object.
        wf["195"] = {"class_type": "InvertMask", "inputs": {"mask": ["122", 1]}}
    else:
        wf["193"] = {"class_type": "LoadBackgroundRemovalModel", "inputs": {"bg_removal_name": f["backgroundRemoval"]}}
        wf["192"] = {"class_type": "RemoveBackground", "inputs": {"bg_removal_model": ["193", 0], "image": ["122", 0]}}
    return wf


# ------------------------------------------------------------ custom workflows


def is_api_workflow(value: Any) -> bool:
    """True for an API-format workflow (Workflow → Export (API)): every node has class_type and inputs."""
    if not isinstance(value, dict) or not value:
        return False
    for n in value.values():
        if not isinstance(n, dict) or not isinstance(n.get("class_type"), str):
            return False
        # JavaScript's typeof "object" also accepts null and arrays here.
        if "inputs" not in n or not (n["inputs"] is None or isinstance(n["inputs"], (dict, list))):
            return False
    return True


def is_ui_workflow(value: Any) -> bool:
    """True for a workflow saved with Workflow → Save (UI format), which /prompt cannot run."""
    return isinstance(value, dict) and isinstance(value.get("nodes"), list) and isinstance(value.get("links"), list)


def image_node_candidates(wf: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The LoadImage-like nodes that take an image file name, as [{"id", "title"}]."""
    out: List[Dict[str, Any]] = []
    for node_id, n in wf.items():
        node = obj(n)
        class_type = node.get("class_type")
        if not isinstance(class_type, str) or not re.search(r"LoadImage", class_type, re.I):
            continue
        if not isinstance(obj(node.get("inputs")).get("image"), str):
            continue
        title = obj(node.get("_meta")).get("title")
        out.append({"id": node_id, "title": title if title is not None else class_type})
    return out


def pick_image_node(wf: Dict[str, Any], preferred: str) -> str:
    """The LoadImage node that receives the layer: the chosen one, the only one, or one titled "Krita", "Photoshop", "input" or "source"."""
    candidates = image_node_candidates(wf)
    if preferred and any(c["id"] == preferred for c in candidates):
        return preferred
    if len(candidates) == 1:
        return candidates[0]["id"]
    titled = [c for c in candidates if re.search(r"krita|photoshop|input|source", _js_str(c["title"]), re.I)]
    if len(titled) == 1:
        return titled[0]["id"]
    if not candidates:
        raise ValueError("This workflow has no Load Image node to receive the layer.")
    listed = ", ".join(f"#{c['id']} {_js_str(c['title'])}" for c in candidates)
    raise ValueError(f"This workflow has {len(candidates)} Load Image nodes ({listed}). Pick one in Settings → ComfyUI.")


def prepare_custom_workflow(wf: Dict[str, Any], image: str, image_node_id: str, seed: int) -> Dict[str, Any]:
    """Copy of a custom workflow with the uploaded image and seeds filled in."""
    out = copy.deepcopy(wf)
    node_id = pick_image_node(out, image_node_id)
    out[node_id]["inputs"]["image"] = image
    for node in out.values():
        inputs = obj(obj(node).get("inputs"))
        for key in ("seed", "noise_seed"):
            v = inputs.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                inputs[key] = seed
    return out


# ------------------------------------------------------------------ results


def model_files_from_outputs(outputs: Any) -> List[Dict[str, str]]:
    """
    3D files in a /history entry's outputs. SaveGLB and Save3DAdvanced report
    {"3d": [{filename, subfolder, type}]}; older Preview3D nodes report a path string
    in "result"; custom nodes vary, so every array is scanned.
    """
    files: List[Dict[str, str]] = []
    for node_out in _values(outputs):
        for value in _values(node_out):
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, dict) and isinstance(item.get("filename"), str) and _MODEL_EXT.search(item["filename"]):
                    subfolder = item.get("subfolder")
                    kind = item.get("type")
                    files.append({"filename": item["filename"], "subfolder": subfolder if subfolder is not None else "", "type": kind if kind is not None else "output"})
                elif isinstance(item, str) and _MODEL_EXT.search(_OUTPUT_TAG.sub("", item)):
                    # "3d/old_00001_.glb [output]"
                    parts = re.split(r"[\\/]", _OUTPUT_TAG.sub("", item))
                    filename = parts.pop()
                    files.append({"filename": filename, "subfolder": "/".join(parts), "type": "output"})
    return files


def history_error(entry: Any) -> Optional[str]:
    """Error text for a failed /history entry; None when it did not fail."""
    status = obj(entry).get("status")
    if not isinstance(status, dict) or status.get("status_str") != "error":
        return None
    for message in lst(status.get("messages")):
        if not isinstance(message, list) or not message:
            continue
        kind = message[0]
        data = obj(message[1]) if len(message) > 1 else {}
        if kind == "execution_error":
            node_type = data.get("node_type")
            exception = data.get("exception_message")
            return f"{_js_str(node_type if node_type is not None else 'Node')}: {_js_str(exception if exception is not None else 'failed').strip()}"
        if kind == "execution_interrupted":
            return "Cancelled in ComfyUI."
    return "The ComfyUI workflow failed."


def prompt_error(body: Any) -> str:
    """Message for a rejected POST /prompt (validation errors, missing models), one line per node error."""
    if isinstance(body, str):
        return body
    b = obj(body)
    message = obj(b.get("error")).get("message")
    lines = [_js_str(message) if message is not None else "ComfyUI rejected the workflow."]
    node_errors = b.get("node_errors")
    for node in _values(node_errors if node_errors is not None else {}):
        node = obj(node)
        class_type = node.get("class_type")
        for err in lst(node.get("errors")):
            err = obj(err)
            msg = err.get("message")
            details = err.get("details")
            suffix = f" ({_js_str(details)})" if details else ""
            lines.append(f"{_js_str(class_type if class_type is not None else 'Node')}: {_js_str(msg) if msg is not None else ''}{suffix}")
    return "\n".join(lines)
