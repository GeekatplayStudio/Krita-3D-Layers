"""
Everything the plugin does to Krita documents, in one place so it is easy to audit.

- Reading what to turn into 3D: the active layer (`Node.thumbnail` at full size gives its
  pixels as 8-bit sRGB in any colour space), or what is visible inside the selection
  (`Document.projection`, masked by the selection).
- Placing a render as a new paint layer and updating it later. Pixels are written in RGBA
  8-bit sRGB: the layer is converted to that space for the write and back to the image's
  space afterwards, so 16-bit, float and other profiles work too.
- 3D layer state (model, pose, lighting, where the render sits) is kept in a document
  annotation, a JSON map keyed by layer id, saved inside the .kra.
- "Show document" in the editor: the composite of the layers below and above a 3D layer,
  read by hiding the other part for a moment.

Every function here runs on Krita's UI thread.

Behaviour verified in Krita 5.3.4 (see docs/ARCHITECTURE.md "Platform findings").
"""
from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Optional, Tuple

from krita import Krita  # type: ignore

from ..core.geometry import Box, box, height, map_box, split_layers, width
from .qt import E, QByteArray, QImage, QPainter, QUuid, Qt, image_bytes, image_to_png

ANNOTATION = "geekatplay-3d-layers"
ANNOTATION_DESCRIPTION = "Geekatplay 3D Layers: model, pose and lighting of the 3D layers"
SRGB = "sRGB-elle-V2-srgbtrc.icc"
#: Composites shown in the editor: sharp in a full-screen window, quick to send.
VIEW_MAX_EDGE = 2048

ARGB32 = E(QImage, "Format", "Format_ARGB32")
ALPHA8 = E(QImage, "Format", "Format_Alpha8")
SMOOTH = E(Qt, "TransformationMode", "SmoothTransformation")
KEEP_ASPECT = E(Qt, "AspectRatioMode", "KeepAspectRatio")
IGNORE_ASPECT = E(Qt, "AspectRatioMode", "IgnoreAspectRatio")


class DocError(Exception):
    """A problem the user can fix (shown as is)."""


# ------------------------------------------------------------------ lookup


def app():
    return Krita.instance()


def doc_key(doc) -> str:
    """A stable id for an open document: its root node's id."""
    return doc.rootNode().uniqueId().toString()


def find_doc(key: Optional[str]):
    for doc in app().documents():
        if doc_key(doc) == key:
            return doc
    return None


def active_doc():
    return app().activeDocument()


def active_node(doc):
    """The selected layer (the integration test replaces this: headless Krita has no view)."""
    return doc.activeNode()


def node_id(node) -> str:
    return node.uniqueId().toString()


def find_node(doc, uuid: Optional[str]):
    if not uuid:
        return None
    try:
        return doc.nodeByUniqueID(QUuid(uuid))
    except Exception:  # noqa: BLE001 - an unknown id
        return None


def doc_title(doc) -> str:
    name = doc.fileName() or doc.name() or "Untitled"
    return name.replace("\\", "/").split("/")[-1]


# ------------------------------------------------------------ layer state


def layer_states(doc) -> Dict[str, Dict[str, Any]]:
    try:
        raw = bytes(doc.annotation(ANNOTATION) or b"")
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except (ValueError, TypeError):
        data = {}
    layers = data.get("layers") if isinstance(data, dict) else None
    return layers if isinstance(layers, dict) else {}


def layer_state(doc, uuid: Optional[str]) -> Optional[Dict[str, Any]]:
    return layer_states(doc).get(uuid or "") if uuid else None


def save_layer_state(doc, uuid: str, state: Optional[Dict[str, Any]]) -> None:
    states = layer_states(doc)
    if state is None:
        states.pop(uuid, None)
    else:
        states[uuid] = state
    # Forget layers that were deleted.
    states = {k: v for k, v in states.items() if find_node(doc, k) is not None}
    doc.setAnnotation(ANNOTATION, ANNOTATION_DESCRIPTION, QByteArray(json.dumps({"version": 1, "layers": states}).encode("utf-8")))


# ----------------------------------------------------------------- context


def context() -> Dict[str, Any]:
    """What the docker shows: document, active layer, selection, 3D layer."""
    doc = active_doc()
    if doc is None:
        return {"hasDocument": False, "hasSelection": False, "is3DLayer": False}
    node = active_node(doc)
    sel = doc.selection()
    uuid = node_id(node) if node is not None else None
    state = layer_state(doc, uuid)
    return {
        "hasDocument": True,
        "docKey": doc_key(doc),
        "docTitle": doc_title(doc),
        "docWidth": doc.width(),
        "docHeight": doc.height(),
        "layerId": uuid,
        "layerName": node.name() if node is not None else None,
        "layerKind": node.type() if node is not None else None,
        "hasSelection": bool(sel is not None and sel.width() > 0 and sel.height() > 0),
        "is3DLayer": state is not None,
        "modelName": state.get("modelName") if state else None,
    }


# -------------------------------------------------------- reading pixels


def _scaled(image: QImage, max_edge: int) -> QImage:
    if max_edge > 0 and max(image.width(), image.height()) > max_edge:
        return image.scaled(max_edge, max_edge, KEEP_ASPECT, SMOOTH)
    return image


def _has_alpha(image: QImage) -> bool:
    alpha = image_alpha(image)
    # Removes the opaque values; anything left is transparency (fast, in C).
    return len(alpha.translate(None, bytes(range(250, 256)))) > 0


def image_alpha(image: QImage) -> bytes:
    a = image.convertToFormat(ALPHA8)
    ptr = a.constBits()
    ptr.setsize(a.bytesPerLine() * a.height())
    data = bytes(ptr)
    if a.bytesPerLine() == a.width():
        return data
    return b"".join(data[y * a.bytesPerLine() : y * a.bytesPerLine() + a.width()] for y in range(a.height()))


def _apply_mask(image: QImage, mask: bytes, w: int, h: int) -> QImage:
    """Multiplies the image's alpha by an 8-bit selection mask (soft edges stay soft)."""
    mask_image = QImage(mask, w, h, w, ALPHA8).copy()
    out = image.convertToFormat(E(QImage, "Format", "Format_ARGB32_Premultiplied"))
    painter = QPainter(out)
    painter.setCompositionMode(E(QPainter, "CompositionMode", "CompositionMode_DestinationIn"))
    painter.drawImage(0, 0, mask_image)
    painter.end()
    return out.convertToFormat(ARGB32)


def png_data_url(image: QImage, edge: int) -> str:
    return "data:image/png;base64," + base64.b64encode(image_to_png(_scaled(image, edge))).decode("ascii")


def read_source(source: str, max_edge: int) -> Dict[str, Any]:
    """
    The pixels to send: the active layer, or what is visible inside the selection.
    source: "auto" (selection if there is one, else the layer) | "layer" | "selection".
    """
    doc = active_doc()
    if doc is None:
        raise DocError("Open an image in Krita first.")
    node = active_node(doc)
    sel = doc.selection()
    has_sel = sel is not None and sel.width() > 0 and sel.height() > 0
    if source == "selection" and not has_sel:
        raise DocError("There is no active selection. Make a selection, or switch the source to Layer.")
    mode = "selection" if source == "selection" or (source == "auto" and has_sel) else "layer"
    base_name = node.name() if node is not None else doc_title(doc).rsplit(".", 1)[0]

    if mode == "selection":
        x, y = max(0, sel.x()), max(0, sel.y())
        r, b = min(doc.width(), sel.x() + sel.width()), min(doc.height(), sel.y() + sel.height())
        w, h = r - x, b - y
        if w <= 0 or h <= 0:
            raise DocError("The selection is outside the image.")
        doc.refreshProjection()
        doc.waitForDone()
        image = _apply_mask(doc.projection(x, y, w, h).convertToFormat(ARGB32), bytes(sel.pixelData(x, y, w, h)), w, h)
        bounds = box(x, y, r, b)
        name = f"{base_name} (selection)"
    else:
        if node is None:
            raise DocError("Select a layer (or make a selection) to send.")
        rect = node.bounds()
        if rect.width() <= 0 or rect.height() <= 0:
            raise DocError(f'Layer "{node.name()}" is empty.')
        w, h = rect.width(), rect.height()
        # The layer at its own size (large layers are read at twice the final size, then smoothed).
        scale = min(1.0, (2 * max_edge) / max(w, h)) if max_edge > 0 else 1.0
        image = node.thumbnail(max(1, round(w * scale)), max(1, round(h * scale))).convertToFormat(ARGB32)
        bounds = box(rect.x(), rect.y(), rect.x() + w, rect.y() + h)
        name = base_name

    image = _scaled(image, max_edge)
    return {
        "png": image_to_png(image),
        "width": image.width(),
        "height": image.height(),
        "hasAlpha": _has_alpha(image),
        "name": name,
        "preview": png_data_url(image, 160),
        "target": {"docKey": doc_key(doc), "docTitle": doc_title(doc), "layerId": node_id(node) if node is not None else None, "bounds": bounds},
    }


# --------------------------------------------------------- writing pixels


def _write(node, image: QImage, left: int, top: int, clear: Optional[Tuple[int, int, int, int]] = None) -> None:
    """Writes an ARGB32 image into a paint layer, in whatever colour space the layer uses."""
    model, depth, profile = node.colorModel(), node.colorDepth(), node.colorProfile()
    convert = (model, depth, profile) != ("RGBA", "U8", SRGB)
    if convert:
        node.setColorSpace("RGBA", "U8", SRGB)
    if clear and clear[2] > 0 and clear[3] > 0:
        node.setPixelData(QByteArray(bytes(clear[2] * clear[3] * 4)), *clear)
    node.setPixelData(QByteArray(image_bytes(image)), left, top, image.width(), image.height())
    if convert:
        node.setColorSpace(model, depth, profile)


def _render_image(png: bytes, frame: Box) -> Tuple[QImage, int, int]:
    image = QImage.fromData(png, "PNG").convertToFormat(ARGB32)
    if image.isNull():
        raise DocError("The render could not be read.")
    w, h = max(1, round(width(frame))), max(1, round(height(frame)))
    if (w, h) != (image.width(), image.height()):
        image = image.scaled(w, h, IGNORE_ASPECT, SMOOTH)
    return image, round(frame["left"]), round(frame["top"])


def content_in_doc(frame: Box, render_w: int, content: Optional[Box]) -> Optional[Box]:
    """The visible object's box in document pixels (content is in render pixels)."""
    if not content:
        return None
    s = width(frame) / render_w
    return box(frame["left"] + content["left"] * s, frame["top"] + content["top"] * s, frame["left"] + content["right"] * s, frame["top"] + content["bottom"] * s)


def place_render(key: Optional[str], png: bytes, render_w: int, content: Optional[Box], frame: Box, state: Dict[str, Any], name: str, above_uuid: Optional[str]) -> Dict[str, Any]:
    """A new paint layer with the render at `frame` (document pixels), above layer `above_uuid`."""
    doc = find_doc(key) or active_doc()
    if doc is None:
        raise DocError("The image is no longer open.")
    image, left, top = _render_image(png, frame)
    node = doc.createNode(name, "paintlayer")
    above = find_node(doc, above_uuid)
    if above is not None and above.parentNode() is not None:
        above.parentNode().addChildNode(node, above)
    else:
        doc.rootNode().addChildNode(node, None)
    _write(node, image, left, top)
    uuid = node_id(node)
    save_layer_state(doc, uuid, {**state, "frame": frame, "renderWidth": render_w, "content": content_in_doc(frame, render_w, content)})
    doc.setActiveNode(node)
    doc.refreshProjection()
    return {"docKey": doc_key(doc), "layerId": uuid, "layerName": node.name(), "updated": False}


def current_frame(doc, node, state: Dict[str, Any]) -> Optional[Box]:
    """
    Where the layer's render frame is now. Paint layers have no transform of their own, so
    a move (or a uniform scale) with Krita's tools is detected by comparing the layer's
    bounds with where the object was placed.
    """
    frame = state.get("frame")
    content = state.get("content")
    if not isinstance(frame, dict):
        return None
    rect = node.bounds()
    if not isinstance(content, dict) or rect.width() <= 0 or rect.height() <= 0:
        return frame
    now = box(rect.x(), rect.y(), rect.x() + rect.width(), rect.y() + rect.height())
    if abs(width(now) - width(content)) <= 2 and abs(height(now) - height(content)) <= 2:
        dx, dy = now["left"] - content["left"], now["top"] - content["top"]
        return box(frame["left"] + dx, frame["top"] + dy, frame["right"] + dx, frame["bottom"] + dy)
    same_shape = width(content) > 0 and height(content) > 0 and abs(width(now) / height(now) - width(content) / height(content)) < 0.03
    return map_box(frame, content, now) if same_shape else frame


def update_render(key: str, uuid: str, png: bytes, render_w: int, render_h: int, content: Optional[Box], state: Dict[str, Any]) -> Dict[str, Any]:
    """Replaces a 3D layer's pixels with a new render, keeping its place (left, top, width)."""
    doc = find_doc(key)
    if doc is None:
        raise DocError("The image with this 3D layer is no longer open.")
    node = find_node(doc, uuid)
    if node is None:
        raise DocError("The 3D layer was deleted.")
    if node.type() != "paintlayer":
        raise DocError("This 3D layer is no longer a paint layer, so it cannot be updated.")
    old = layer_state(doc, uuid) or {}
    frame = current_frame(doc, node, old) or state.get("frame")
    if not frame:
        rect = node.bounds()
        frame = box(rect.x(), rect.y(), rect.x() + rect.width(), rect.y() + rect.height())
    # A different aspect ratio keeps left, top and width; only the height changes.
    frame = box(frame["left"], frame["top"], frame["right"], frame["top"] + width(frame) * render_h / render_w)
    image, left, top = _render_image(png, frame)
    rect = node.bounds()
    _write(node, image, left, top, clear=(rect.x(), rect.y(), rect.width(), rect.height()))
    save_layer_state(doc, uuid, {**state, "frame": frame, "renderWidth": render_w, "content": content_in_doc(frame, render_w, content)})
    doc.refreshProjection()
    return {"docKey": key, "layerId": uuid, "layerName": node.name(), "updated": True}


def detach(key: str, uuid: str) -> None:
    doc = find_doc(key)
    if doc is not None:
        save_layer_state(doc, uuid, None)


# ----------------------------------------------------------- document view


def _tree(nodes) -> List[Dict[str, Any]]:
    # Krita lists child nodes bottom first; the split wants them top first. Masks (the global
    # selection mask, transparency and filter masks) go with their layer and are never split.
    return [
        {"id": node_id(n), "visible": n.visible(), "layers": _tree(n.childNodes()) if n.childNodes() else None}
        for n in reversed(list(nodes))
        if not n.type().endswith("mask")
    ]


def document_view(key: str, split_uuid: Optional[str], split_belongs_below: bool, frame: Optional[Box]) -> Dict[str, Any]:
    """The composite of the visible layers below and above the split layer (PNG, ≤ 2048 px)."""
    doc = find_doc(key)
    if doc is None:
        raise DocError("The image is no longer open.")
    split = split_layers(_tree(doc.topLevelNodes()), split_uuid, split_belongs_below)
    w, h = doc.width(), doc.height()
    s = min(1.0, VIEW_MAX_EDGE / max(w, h))
    tw, th = max(1, round(w * s)), max(1, round(h * s))
    modified = doc.modified()

    def composite(hide: List[str]) -> Dict[str, Any]:
        nodes = [n for n in (find_node(doc, i) for i in hide) if n is not None]
        for n in nodes:
            n.setVisible(False)
        try:
            doc.refreshProjection()
            doc.waitForDone()
            # Not doc.thumbnail(): it has no alpha channel (transparent areas turn black).
            image = doc.projection(0, 0, w, h).convertToFormat(ARGB32)
            if (tw, th) != (w, h):
                image = image.scaled(tw, th, IGNORE_ASPECT, SMOOTH)
        finally:
            for n in nodes:
                n.setVisible(True)
        return {"pngBase64": base64.b64encode(image_to_png(image)).decode("ascii"), "width": image.width(), "height": image.height()}

    try:
        below = composite(split["hideForBelow"]) if split["hasBelow"] else None
        above = composite(split["hideForAbove"]) if split["hasAbove"] else None
    finally:
        doc.refreshProjection()
        doc.setModified(modified)
    out: Dict[str, Any] = {"title": doc_title(doc), "width": w, "height": h, "below": below, "above": above}
    if frame:
        out["frame"] = frame
    return out
