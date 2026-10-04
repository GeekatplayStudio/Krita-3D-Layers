"""
Where renders go in the document, and how the document is split around a 3D layer
(ports of the Photoshop plugin's src/shared/placement.ts and documentView.ts).

Boxes are dicts {"left", "top", "right", "bottom"} in pixels.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

Box = Dict[str, float]


def box(left: float, top: float, right: float, bottom: float) -> Box:
    return {"left": left, "top": top, "right": right, "bottom": bottom}


def width(b: Box) -> float:
    return b["right"] - b["left"]


def height(b: Box) -> float:
    return b["bottom"] - b["top"]


def frame_for_target(render_w: float, render_h: float, content: Optional[Box], target: Box) -> Box:
    """Where the render frame must go (document pixels) so the object inside it (`content`, render pixels) fits centred inside `target`."""
    c = content if content and width(content) > 0 and height(content) > 0 else box(0, 0, render_w, render_h)
    scale = min(width(target) / width(c), height(target) / height(c))
    cx = (c["left"] + c["right"]) / 2
    cy = (c["top"] + c["bottom"]) / 2
    tx = (target["left"] + target["right"]) / 2
    ty = (target["top"] + target["bottom"]) / 2
    left = tx - cx * scale
    top = ty - cy * scale
    return box(left, top, left + render_w * scale, top + render_h * scale)


def centered_target(doc_w: float, doc_h: float, fraction: float = 0.6) -> Box:
    """Default target for a new 3D layer: the middle `fraction` of the canvas."""
    w, h = doc_w * fraction, doc_h * fraction
    return box((doc_w - w) / 2, (doc_h - h) / 2, (doc_w + w) / 2, (doc_h + h) / 2)


def map_box(b: Box, src: Box, dst: Box) -> Box:
    """`b` moved and scaled the way `src` became `dst` (uniform scale from the widths)."""
    s = width(dst) / width(src) if width(src) > 0 else 1.0
    left = dst["left"] + (b["left"] - src["left"]) * s
    top = dst["top"] + (b["top"] - src["top"]) * s
    return box(left, top, left + width(b) * s, top + height(b) * s)


# --------------------------------------------------------- document view


def split_layers(layers: List[Dict[str, Any]], split_id: Optional[str], split_belongs_below: bool) -> Dict[str, Any]:
    """
    Splits the layer stack at layer `split_id`. Layers are {"id", "visible", "layers"?},
    listed TOP FIRST. Only whole subtrees are hidden: a group holding the split layer stays
    visible and is split inside. The split layer goes with the layers below when
    `split_belongs_below` (a new layer is placed above the active one) and is hidden in both
    parts otherwise (the 3D layer being edited). Without a split layer, everything visible
    counts as below.
    """
    hide_for_above: List[str] = []
    hide_for_below: List[str] = []

    def contains(node: Dict[str, Any], target: str) -> bool:
        return node["id"] == target or any(contains(c, target) for c in node.get("layers") or [])

    found = split_id is not None and any(contains(n, split_id) for n in layers)

    def walk(nodes: List[Dict[str, Any]]) -> None:
        below = False
        for node in nodes:
            if not node.get("visible"):
                if found and not below and contains(node, split_id):  # type: ignore[arg-type]
                    below = True
                continue
            if below or not found:
                hide_for_above.append(node["id"])
            elif node["id"] == split_id:
                below = True
                hide_for_above.append(node["id"])
                if not split_belongs_below:
                    hide_for_below.append(node["id"])
            elif contains(node, split_id):  # type: ignore[arg-type]
                below = True
                walk(node.get("layers") or [])
            else:
                hide_for_below.append(node["id"])

    walk(layers)

    def own(i: str) -> bool:
        return i == split_id and not split_belongs_below

    return {
        "hideForAbove": hide_for_above,
        "hideForBelow": hide_for_below,
        "found": found,
        "hasAbove": any(not own(i) for i in hide_for_below),
        "hasBelow": any(not own(i) for i in hide_for_above),
    }
