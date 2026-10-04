"""
Plugin settings: defaults and validation (a port of the Photoshop plugin's
src/shared/settings.ts, same names and values, so both plugins behave the same).

Settings live in <data folder>/krita/settings.json. API keys never go there: they are in
credentials.json (core/secrets.py), shared with the Photoshop plugin. `sanitize` is the
single gate every load and update goes through, so a hand-edited or old settings file can
never put the plugin into an invalid state.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlsplit

from .providers.base import PROVIDER_IDS

# Model lists as documented by each provider on 2026-10-02 (the Photoshop plugin's
# docs/PROVIDERS.md). Settings also accept any other id typed by hand.
MESHY_AI_MODELS = ("latest", "meshy-7.1", "meshy-6", "meshy-6-lite", "meshy-t2")
MESHY_SMART_TOPOLOGY_MODEL = "meshy-t2"
MESHY_MODEL_SUCCESSORS = {"meshy-7": "meshy-7.1", "meshy-5": "meshy-6-lite", "meshy-4": "latest", "meshy-t1": "meshy-t2"}
TRIPO_MODEL_VERSIONS = ("v3.1-20260211", "v3.0-20250812", "v2.5-20250123", "P1-20260311", "P2-20260801")
TRIPO_TEXTURE_VERSIONS = ("v3.5-20260815", "v3.0-20250812", "v2.5-20250123")
TRIPO_TEXTURE_V35 = "v3.5-20260815"
HITEM3D_MODELS = ("hi3dv3.0", "hitem3dv2.1", "hitem3dv2.0", "hitem3dv1.5", "scene-portraitv2.1", "scene-portraitv2.0", "scene-portraitv1.5")
HITEM3D_RESOLUTIONS = {
    "hi3dv3.0": ["2048quality", "2048master"],
    "hitem3dv2.1": ["1536fast", "1536pro"],
    "hitem3dv2.0": ["1536", "1536pro"],
    "hitem3dv1.5": ["512", "1024", "1536", "1536pro"],
    "scene-portraitv2.1": ["1536profast", "1536pro"],
    "scene-portraitv2.0": ["1536pro"],
    "scene-portraitv1.5": ["1536"],
}
HITEM3D_DEFAULT_RESOLUTION = {
    "hi3dv3.0": "2048quality",
    "hitem3dv2.1": "1536fast",
    "hitem3dv2.0": "1536",
    "hitem3dv1.5": "1024",
    "scene-portraitv2.1": "1536profast",
    "scene-portraitv2.0": "1536pro",
    "scene-portraitv1.5": "1536",
}


def hitem3d_supports_pbr(model: str) -> bool:
    """PBR is only accepted by the v2.0, v2.1 and v3.0 models."""
    return re.search(r"v(2\.[01]|3\.0)$", model) is not None


# 3D editor (shared/threeD.ts)
ENVIRONMENTS = ("studio", "city", "apartment", "dawn", "sunset", "forest", "park", "night", "lobby", "warehouse")
DEFAULT_CAMERA_POSITION = {"x": 0, "y": 0, "z": 4}
DEFAULT_CAMERA_FOV = 45
MAX_RESOLUTION = 8192
DEFAULT_LIGHTING: Dict[str, Any] = {
    "lightPosition": {"x": 5, "y": 5, "z": 5},
    "lightIntensity": 1.2,
    "lightColor": "#ffffff",
    "ambientIntensity": 0.35,
    "environment": "city",
    "envIntensity": 0.6,
    "castShadowEnabled": True,
    "castShadowBlur": 22,
    "castShadowIntensity": 0.35,
    "contactShadowEnabled": True,
    "contactShadowBlur": 8,
    "contactShadowIntensity": 0.6,
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "version": 1,
    "defaultProvider": "meshy",
    "meshy": {
        "baseUrl": "https://api.meshy.ai",
        "aiModel": "latest",
        "geometryResolution": "standard",
        "textureResolution": "2k",
        "shouldTexture": True,
        "enablePbr": True,
        "shouldRemesh": False,
        "topology": "triangle",
        "targetPolycount": 0,
        "removeLighting": True,
        "imageEnhancement": True,
        "moderation": True,
    },
    "tripo": {
        "baseUrl": "https://openapi.tripo3d.ai/v3",
        "model": "v3.1-20260211",
        "texture": True,
        "pbr": True,
        "textureQuality": "standard",
        "textureVersion": "",
        "delight": True,
        "geometryQuality": "standard",
        "faceLimit": 0,
        "smartLowPoly": False,
        "autoSize": False,
        "orientation": "default",
    },
    "hitem3d": {
        "baseUrl": "https://api.hitem3d.ai/open-api/v1",
        "appId": "",
        "model": "hi3dv3.0",
        "resolution": "2048quality",
        "requestType": "3",
        "face": 0,
        "pbr": True,
        "removeBackground": True,
        "shading": 0.5,
    },
    "comfyui": {
        "url": "http://127.0.0.1:8188",
        "workflow": "trellis2",
        "customWorkflowName": "",
        "customWorkflow": None,
        "imageNodeId": "",
        "removeBackground": False,
        "textureSize": 2048,
        "faceCount": 300000,
        "seed": -1,
        "timeoutMinutes": 30,
    },
    "send": {
        "source": "auto",  # auto | layer | selection
        "maxEdge": 2048,
    },
    "editor": {
        "defaultResolution": 2048,
        "rememberLighting": True,
        "lighting": copy.deepcopy(DEFAULT_LIGHTING),
        "view": {"showDocument": True, "showAbove": True, "aboveOpacity": 1},
        #: "app" opens the editor in a browser app window (Edge/Chrome), "browser" in a normal tab.
        "window": "app",
    },
    "ui": {
        "tab": "create",
        "libraryFolder": "",
    },
}


def _is_obj(v: Any) -> bool:
    return isinstance(v, dict)


def _bool(v: Any, d: bool) -> bool:
    return v if isinstance(v, bool) else d


def _str(v: Any, d: str) -> str:
    return v if isinstance(v, str) else d


def _num(v: Any, d: float, lo: float, hi: float) -> float:
    if isinstance(v, bool):
        return d
    if isinstance(v, (int, float)):
        n = float(v)
    elif isinstance(v, str) and v.strip():
        try:
            n = float(v)
        except ValueError:
            return d
    else:
        return d
    if n != n or n in (float("inf"), float("-inf")):
        return d
    return min(hi, max(lo, n))


def _int(v: Any, d: int, lo: int, hi: int) -> int:
    return int(round(_num(v, d, lo, hi)))


def _one_of(v: Any, allowed: Iterable[str], d: str) -> str:
    return v if isinstance(v, str) and v in allowed else d


def normalize_url(v: Any, d: str) -> str:
    """http(s) URL without trailing slashes; anything else falls back to the default."""
    if not isinstance(v, str) or not v.strip():
        return d
    url = v.strip().rstrip("/")
    if not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    try:
        parts = urlsplit(url)
    except ValueError:
        return d
    if not parts.netloc:
        return d
    return url.rstrip("/")


def _color(v: Any, d: str) -> str:
    return v.lower() if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v) else d


def _vec(v: Any, d: Dict[str, float]) -> Dict[str, float]:
    if not _is_obj(v):
        return dict(d)
    return {k: _num(v.get(k), d[k], -1000, 1000) for k in ("x", "y", "z")}


def sanitize_lighting(raw: Any) -> Dict[str, Any]:
    r = raw if _is_obj(raw) else {}
    d = DEFAULT_LIGHTING
    return {
        "lightPosition": _vec(r.get("lightPosition"), d["lightPosition"]),
        "lightIntensity": _num(r.get("lightIntensity"), d["lightIntensity"], 0, 10),
        "lightColor": _color(r.get("lightColor"), d["lightColor"]),
        "ambientIntensity": _num(r.get("ambientIntensity"), d["ambientIntensity"], 0, 5),
        "environment": _one_of(r.get("environment"), ENVIRONMENTS, d["environment"]),
        "envIntensity": _num(r.get("envIntensity"), d["envIntensity"], 0, 5),
        "castShadowEnabled": _bool(r.get("castShadowEnabled"), d["castShadowEnabled"]),
        "castShadowBlur": _num(r.get("castShadowBlur"), d["castShadowBlur"], 0, 100),
        "castShadowIntensity": _num(r.get("castShadowIntensity"), d["castShadowIntensity"], 0, 1),
        "contactShadowEnabled": _bool(r.get("contactShadowEnabled"), d["contactShadowEnabled"]),
        "contactShadowBlur": _num(r.get("contactShadowBlur"), d["contactShadowBlur"], 0, 50),
        "contactShadowIntensity": _num(r.get("contactShadowIntensity"), d["contactShadowIntensity"], 0, 1),
    }


def sanitize(raw: Any) -> Dict[str, Any]:
    """Valid settings from anything (old files, partial objects, garbage)."""
    r = raw if _is_obj(raw) else {}
    d = DEFAULT_SETTINGS
    m = r.get("meshy") if _is_obj(r.get("meshy")) else {}
    t = r.get("tripo") if _is_obj(r.get("tripo")) else {}
    h = r.get("hitem3d") if _is_obj(r.get("hitem3d")) else {}
    c = r.get("comfyui") if _is_obj(r.get("comfyui")) else {}
    snd = r.get("send") if _is_obj(r.get("send")) else {}
    e = r.get("editor") if _is_obj(r.get("editor")) else {}
    ev = e.get("view") if _is_obj(e.get("view")) else {}
    ui = r.get("ui") if _is_obj(r.get("ui")) else {}

    h_model = _one_of(h.get("model"), HITEM3D_MODELS, d["hitem3d"]["model"])
    h_res = h.get("resolution") if h.get("resolution") in HITEM3D_RESOLUTIONS[h_model] else HITEM3D_DEFAULT_RESOLUTION[h_model]
    h_face = _int(h.get("face"), 0, 0, 5_000_000)
    meshy_model = m["aiModel"].strip() if isinstance(m.get("aiModel"), str) and m["aiModel"].strip() else d["meshy"]["aiModel"]
    tex_version = _one_of(t.get("textureVersion"), ("",) + TRIPO_TEXTURE_VERSIONS, d["tripo"]["textureVersion"])
    tex_quality = _one_of(t.get("textureQuality"), ("fast", "standard", "detailed", "extreme"), d["tripo"]["textureQuality"])

    return {
        "version": 1,
        "defaultProvider": _one_of(r.get("defaultProvider"), PROVIDER_IDS, d["defaultProvider"]),
        "meshy": {
            "baseUrl": normalize_url(m.get("baseUrl"), d["meshy"]["baseUrl"]),
            "aiModel": MESHY_MODEL_SUCCESSORS.get(meshy_model, meshy_model),
            "geometryResolution": _one_of(m.get("geometryResolution"), ("standard", "2k", "4k"), d["meshy"]["geometryResolution"]),
            "textureResolution": _one_of(m.get("textureResolution"), ("2k", "4k", "8k"), d["meshy"]["textureResolution"]),
            "shouldTexture": _bool(m.get("shouldTexture"), d["meshy"]["shouldTexture"]),
            "enablePbr": _bool(m.get("enablePbr"), d["meshy"]["enablePbr"]),
            "shouldRemesh": _bool(m.get("shouldRemesh"), d["meshy"]["shouldRemesh"]),
            "topology": _one_of(m.get("topology"), ("triangle", "quad"), d["meshy"]["topology"]),
            "targetPolycount": _int(m.get("targetPolycount"), 0, 0, 300_000),
            "removeLighting": _bool(m.get("removeLighting"), d["meshy"]["removeLighting"]),
            "imageEnhancement": _bool(m.get("imageEnhancement"), d["meshy"]["imageEnhancement"]),
            "moderation": _bool(m.get("moderation"), d["meshy"]["moderation"]),
        },
        "tripo": {
            "baseUrl": normalize_url(t.get("baseUrl"), d["tripo"]["baseUrl"]),
            "model": t["model"].strip() if isinstance(t.get("model"), str) and t["model"].strip() else d["tripo"]["model"],
            "texture": _bool(t.get("texture"), d["tripo"]["texture"]),
            "pbr": _bool(t.get("pbr"), d["tripo"]["pbr"]),
            # "fast" exists only on the v3.5 texture model (Tripo answers 1004 otherwise).
            "textureQuality": "standard" if tex_quality == "fast" and tex_version != TRIPO_TEXTURE_V35 else tex_quality,
            "textureVersion": tex_version,
            "delight": _bool(t.get("delight"), d["tripo"]["delight"]),
            "geometryQuality": _one_of(t.get("geometryQuality"), ("standard", "detailed"), d["tripo"]["geometryQuality"]),
            "faceLimit": _int(t.get("faceLimit"), 0, 0, 2_000_000),
            "smartLowPoly": _bool(t.get("smartLowPoly"), d["tripo"]["smartLowPoly"]),
            "autoSize": _bool(t.get("autoSize"), d["tripo"]["autoSize"]),
            "orientation": _one_of(t.get("orientation"), ("default", "align_image"), d["tripo"]["orientation"]),
        },
        "hitem3d": {
            "baseUrl": normalize_url(h.get("baseUrl"), d["hitem3d"]["baseUrl"]),
            "appId": _str(h.get("appId"), "").strip(),
            "model": h_model,
            "resolution": h_res,
            "requestType": _one_of(h.get("requestType"), ("1", "3"), d["hitem3d"]["requestType"]),
            "face": 0 if h_face == 0 else max(100_000, h_face),
            "pbr": _bool(h.get("pbr"), d["hitem3d"]["pbr"]),
            "removeBackground": _bool(h.get("removeBackground"), d["hitem3d"]["removeBackground"]),
            "shading": round(_num(h.get("shading"), d["hitem3d"]["shading"], 0, 1) * 10) / 10,
        },
        "comfyui": {
            "url": normalize_url(c.get("url"), d["comfyui"]["url"]),
            "workflow": _one_of(c.get("workflow"), ("trellis2", "custom"), d["comfyui"]["workflow"]),
            "customWorkflowName": _str(c.get("customWorkflowName"), ""),
            "customWorkflow": c.get("customWorkflow") if _is_obj(c.get("customWorkflow")) else None,
            "imageNodeId": _str(c.get("imageNodeId"), ""),
            "removeBackground": _bool(c.get("removeBackground"), d["comfyui"]["removeBackground"]),
            "textureSize": _int(c.get("textureSize"), d["comfyui"]["textureSize"], 512, 8192),
            "faceCount": _int(c.get("faceCount"), d["comfyui"]["faceCount"], 10_000, 5_000_000),
            "seed": _int(c.get("seed"), -1, -1, 2**48),
            "timeoutMinutes": _int(c.get("timeoutMinutes"), d["comfyui"]["timeoutMinutes"], 1, 240),
        },
        "send": {
            "source": _one_of(snd.get("source"), ("auto", "layer", "selection"), d["send"]["source"]),
            "maxEdge": _int(snd.get("maxEdge"), d["send"]["maxEdge"], 256, 4096),
        },
        "editor": {
            "defaultResolution": _int(e.get("defaultResolution"), d["editor"]["defaultResolution"], 256, MAX_RESOLUTION),
            "rememberLighting": _bool(e.get("rememberLighting"), d["editor"]["rememberLighting"]),
            "lighting": sanitize_lighting(e.get("lighting")),
            "view": {
                "showDocument": _bool(ev.get("showDocument"), True),
                "showAbove": _bool(ev.get("showAbove"), True),
                "aboveOpacity": _num(ev.get("aboveOpacity"), 1, 0, 1),
            },
            "window": _one_of(e.get("window"), ("app", "browser"), d["editor"]["window"]),
        },
        "ui": {
            "tab": _one_of(ui.get("tab"), ("create", "library", "settings"), d["ui"]["tab"]),
            "libraryFolder": _str(ui.get("libraryFolder"), ""),
        },
    }


def merge(base: Dict[str, Any], patch: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Deep-merges `patch` into a copy of `base` and sanitizes the result."""

    def deep(a: Any, b: Any) -> Any:
        if _is_obj(a) and _is_obj(b):
            out = dict(a)
            for k, v in b.items():
                out[k] = deep(a.get(k), v) if k in a else copy.deepcopy(v)
            return out
        return copy.deepcopy(b)

    return sanitize(deep(copy.deepcopy(base), patch or {}))


def clamp_resolution(width: Any, height: Any) -> Dict[str, int]:
    def c(v: Any) -> int:
        try:
            return min(MAX_RESOLUTION, max(64, int(round(float(v)))))
        except (TypeError, ValueError):
            return 2048

    return {"width": c(width), "height": c(height)}


def settings_for_new_model(lighting: Optional[Dict[str, Any]], resolution: int) -> Dict[str, Any]:
    """Full 3D settings (ThreeDSettings) for a new model from remembered lighting and an export size."""
    out = dict(copy.deepcopy(DEFAULT_LIGHTING))
    out.update(copy.deepcopy(lighting or {}))
    out.update(
        {
            "resolution": clamp_resolution(resolution, resolution),
            "cameraPosition": dict(DEFAULT_CAMERA_POSITION),
            "cameraTarget": {"x": 0, "y": 0, "z": 0},
            "cameraFov": DEFAULT_CAMERA_FOV,
            "environmentBackground": False,
            "modelRotationX": 0,
            "modelRotationY": 0,
            "modelRotationZ": 0,
            "modelScale": 1,
        }
    )
    return out


def lighting_of(settings3d: Dict[str, Any]) -> Dict[str, Any]:
    """The lighting part of 3D settings (remembered for the next new model)."""
    return sanitize_lighting({k: settings3d.get(k) for k in DEFAULT_LIGHTING})
