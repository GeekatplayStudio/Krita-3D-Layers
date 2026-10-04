"""
Integration test that runs inside Krita (headless, with kritarunner): the document
operations of ui/krita_doc.py against real Krita documents.

    python tests/krita/run.py        (finds Krita, runs this, prints the results)

Each check records {"name", "ok", "detail"}; the runner fails if any check failed.
"""
import base64
import json
import os
import sys
import tempfile
import traceback

os.environ["G3D_NO_REGISTER"] = "1"
sys.path.insert(0, os.environ["G3D_PLUGIN_DIR"])

from krita import Krita, Selection  # noqa: E402

from geekatplay_3d_layers.ui import krita_doc  # noqa: E402
from geekatplay_3d_layers.ui.qt import QByteArray, QColor, QImage, QPainter, image_to_png  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append({"name": name, "ok": bool(ok), "detail": str(detail)})


def fill(node, x, y, w, h, bgra):
    node.setPixelData(QByteArray(bytes(bgra) * (w * h)), x, y, w, h)


def render(size, color, radius_frac=0.35):
    """A transparent square PNG with a filled circle, like a render of a model."""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setBrush(QColor(*color))
    p.setPen(QColor(*color))
    r = int(size * radius_frac)
    p.drawEllipse(size // 2 - r, size // 2 - r, 2 * r, 2 * r)
    p.end()
    c = int(size / 2 - r)
    return image_to_png(img), {"left": c, "top": c, "right": size - c, "bottom": size - c}


def pixel(doc, x, y):
    doc.refreshProjection()
    doc.waitForDone()
    b, g, r, a = bytes(doc.pixelData(x, y, 1, 1))
    return r, g, b, a


def png_pixel(b64, x, y):
    img = QImage.fromData(base64.b64decode(b64), "PNG")
    c = img.pixelColor(x, y)
    return c.red(), c.green(), c.blue(), c.alpha()


def __main__(args):
    out_path = args[0]
    app = Krita.instance()
    try:
        doc = app.createDocument(800, 600, "g3d-test", "RGBA", "U8", "", 72.0)
        # Headless Krita has no window, so no active document: point the module at this one.
        krita_doc.active_doc = lambda: doc
        current = {"node": None}
        krita_doc.active_node = lambda d: current["node"]
        doc.setActiveNode = lambda n: current.__setitem__("node", n)
        root = doc.rootNode()
        for n in list(root.childNodes()):
            n.remove()
        bg = doc.createNode("bg", "paintlayer")
        root.addChildNode(bg, None)
        fill(bg, 0, 0, 800, 600, [255, 255, 255, 255])
        obj = doc.createNode("obj", "paintlayer")
        root.addChildNode(obj, bg)
        fill(obj, 100, 100, 200, 150, [0, 0, 255, 255])  # red
        top = doc.createNode("top", "paintlayer")
        root.addChildNode(top, obj)
        fill(top, 0, 500, 800, 40, [0, 255, 0, 255])  # green bar
        doc.setActiveNode(obj)
        doc.refreshProjection()
        doc.waitForDone()

        # ---- reading the source
        src = krita_doc.read_source("layer", 2048)
        check("layer source size", (src["width"], src["height"]) == (200, 150), (src["width"], src["height"]))
        check("layer source is opaque", src["hasAlpha"] is False, src["hasAlpha"])
        check("layer source bounds", src["target"]["bounds"] == {"left": 100, "top": 100, "right": 300, "bottom": 250}, src["target"]["bounds"])
        img = QImage.fromData(src["png"], "PNG")
        check("layer source pixels are the layer's own", img.pixelColor(10, 10).red() == 255 and img.pixelColor(10, 10).blue() == 0, img.pixelColor(10, 10).name())
        small = krita_doc.read_source("layer", 100)
        check("source scaled to max edge", max(small["width"], small["height"]) == 100, (small["width"], small["height"]))

        sel = Selection()
        sel.select(150, 120, 300, 100, 255)
        doc.setSelection(sel)
        ssrc = krita_doc.read_source("auto", 2048)
        check("auto uses the selection", ssrc["name"].endswith("(selection)") and (ssrc["width"], ssrc["height"]) == (300, 100), (ssrc["name"], ssrc["width"], ssrc["height"]))
        simg = QImage.fromData(ssrc["png"], "PNG")
        check("selection reads the composite", simg.pixelColor(10, 10).red() == 255 and simg.pixelColor(250, 50).green() == 255, (simg.pixelColor(10, 10).name(), simg.pixelColor(250, 50).name()))
        doc.setSelection(None) if False else doc.setSelection(Selection())
        ctx = krita_doc.context()
        check("context", ctx["hasDocument"] and ctx["layerName"] == "obj" and not ctx["is3DLayer"], ctx)

        # ---- placing a render above the active layer
        png, content = render(256, (40, 80, 230, 255))
        frame = {"left": 50, "top": 60, "right": 306, "bottom": 316}
        state = {"v": 1, "libraryId": "lib_x", "modelName": "Ball", "origin": "local", "settings": {"resolution": {"width": 256, "height": 256}}, "updatedAt": 1}
        placed = krita_doc.place_render(krita_doc.doc_key(doc), png, 256, content, frame, state, "Ball (3D)", krita_doc.node_id(obj))
        names = [n.name() for n in root.childNodes() if not n.type().endswith("mask")]
        check("new layer goes above the active one", names == ["bg", "obj", "Ball (3D)", "top"], names)
        node = krita_doc.find_node(doc, placed["layerId"])
        b = node.bounds()
        check("render placed at its frame", abs(b.x() - (50 + content["left"])) <= 2 and abs(b.width() - (content["right"] - content["left"])) <= 2, (b.x(), b.y(), b.width(), b.height()))
        check("render pixels", pixel(doc, 178, 188)[:3] == (40, 80, 230), pixel(doc, 178, 188))
        st = krita_doc.layer_state(doc, placed["layerId"])
        check("state saved with frame and content", st and st["modelName"] == "Ball" and st["frame"] == frame and abs(st["content"]["left"] - (50 + content["left"])) < 1, st)
        doc.setActiveNode(node)
        check("context sees a 3D layer", krita_doc.context()["is3DLayer"] is True)

        # ---- show document: split at the new layer (re-posing it)
        view = krita_doc.document_view(krita_doc.doc_key(doc), placed["layerId"], False, frame)
        s = view["below"]["width"] / 800
        below_red = png_pixel(view["below"]["pngBase64"], int(120 * s), int(110 * s))
        below_ball_hidden = png_pixel(view["below"]["pngBase64"], int(178 * s), int(188 * s))
        above_bar = png_pixel(view["above"]["pngBase64"], int(400 * s), int(520 * s))
        above_empty = png_pixel(view["above"]["pngBase64"], int(120 * s), int(110 * s))
        check("below has the layers under it", below_red[:3] == (255, 0, 0) and below_ball_hidden[:3] == (255, 0, 0), (below_red, below_ball_hidden))
        check("above has only the layers above it", above_bar[1] == 255 and above_empty[3] == 0, (above_bar, above_empty))
        check("visibility restored", all(n.visible() for n in root.childNodes()), [n.visible() for n in root.childNodes()])
        new_view = krita_doc.document_view(krita_doc.doc_key(doc), krita_doc.node_id(obj), True, None)
        nb = png_pixel(new_view["below"]["pngBase64"], int(178 * s), int(188 * s))
        check("a new layer's 'below' includes the active layer", nb[:3] in ((40, 80, 230), (255, 0, 0)), nb)

        # ---- update with a different resolution: left, top and width stay
        png2, content2 = render(512, (230, 200, 20, 255))
        krita_doc.update_render(krita_doc.doc_key(doc), placed["layerId"], png2, 512, 512, content2, {**state, "updatedAt": 2})
        b2 = node.bounds()
        check("update keeps the place", abs(b2.x() - b.x()) <= 2 and abs(b2.width() - b.width()) <= 2, ((b.x(), b.width()), (b2.x(), b2.width())))
        check("update replaced the pixels", pixel(doc, 178, 188)[:3] == (230, 200, 20), pixel(doc, 178, 188))

        # ---- the user moves the layer; the next update follows it
        node.move(node.position().x() + 100, node.position().y() + 50)
        doc.refreshProjection()
        doc.waitForDone()
        moved = node.bounds()
        st2 = krita_doc.layer_state(doc, placed["layerId"])
        cf = krita_doc.current_frame(doc, node, st2)
        check("move detected", abs(cf["left"] - (frame["left"] + (moved.x() - b2.x()))) <= 2, (cf, moved.x(), b2.x()))
        krita_doc.update_render(krita_doc.doc_key(doc), placed["layerId"], png, 256, 256, content, {**state, "updatedAt": 3})
        b3 = node.bounds()
        check("update after a move stays where the layer was moved", abs(b3.x() - moved.x()) <= 2 and abs(b3.y() - moved.y()) <= 2, ((moved.x(), moved.y()), (b3.x(), b3.y())))

        # ---- save, reopen: the 3D state is in the .kra
        path = os.path.join(tempfile.mkdtemp(), "g3d.kra")
        doc.setBatchmode(True)
        check("save", doc.saveAs(path))
        uuid = placed["layerId"]
        doc.close()
        doc2 = app.openDocument(path)
        st3 = krita_doc.layer_state(doc2, uuid)
        check("state survives save and reopen", st3 is not None and st3.get("modelName") == "Ball", st3)
        doc2.close()

        # ---- a 16-bit image
        d16 = app.createDocument(300, 300, "g3d-16", "RGBA", "U16", "", 72.0)
        p16 = krita_doc.place_render(krita_doc.doc_key(d16), png, 256, content, {"left": 0, "top": 0, "right": 256, "bottom": 256}, state, "Ball16 (3D)", None)
        n16 = krita_doc.find_node(d16, p16["layerId"])
        check("16-bit image keeps its colour space", (n16.colorModel(), n16.colorDepth()) == ("RGBA", "U16"), (n16.colorModel(), n16.colorDepth()))
        d16.refreshProjection()
        d16.waitForDone()
        th = d16.thumbnail(300, 300).pixelColor(128, 128)
        check("16-bit pixels", (th.red(), th.green(), th.blue()) == (40, 80, 230), th.name())
        d16.close()

        # ---- a 32-bit float image (linear profile): read a layer and place a render
        df = app.createDocument(300, 300, "g3d-f32", "RGBA", "F32", "", 72.0)
        krita_doc.active_doc = lambda: df
        fl = df.createNode("f", "paintlayer")
        df.rootNode().addChildNode(fl, None)
        pf = krita_doc.place_render(krita_doc.doc_key(df), png, 256, content, {"left": 0, "top": 0, "right": 256, "bottom": 256}, state, "BallF (3D)", None)
        nf = krita_doc.find_node(df, pf["layerId"])
        check("float image keeps its colour space", (nf.colorModel(), nf.colorDepth()) == ("RGBA", "F32"), (nf.colorModel(), nf.colorDepth()))
        df.refreshProjection()
        df.waitForDone()
        cf = df.projection(0, 0, 300, 300).pixelColor(128, 128)
        check("float pixels come out as the render's colours", max(abs(cf.red() - 40), abs(cf.green() - 80), abs(cf.blue() - 230)) <= 2, cf.name())
        current["node"] = nf
        srcf = krita_doc.read_source("layer", 2048)
        imgf = QImage.fromData(srcf["png"], "PNG").pixelColor(srcf["width"] // 2, srcf["height"] // 2)
        check("float layer is read as sRGB", max(abs(imgf.red() - 40), abs(imgf.green() - 80), abs(imgf.blue() - 230)) <= 2, imgf.name())
        df.close()
    except Exception:
        check("no exception", False, traceback.format_exc())
    with open(out_path, "w") as fh:
        json.dump(results, fh, indent=1)
