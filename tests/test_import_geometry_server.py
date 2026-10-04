import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from geekatplay_3d_layers.core.geometry import box, centered_target, frame_for_target, map_box, split_layers
from geekatplay_3d_layers.core.importer import ModelImporter, ext_of, is_self_contained_gltf
from geekatplay_3d_layers.core.library import Library
from geekatplay_3d_layers.core.log import MemoryLogger
from geekatplay_3d_layers.ui.server import LocalServer
from helpers import fake_glb

FIXTURES = Path(__file__).parent / "fixtures" / "public" / "samples" / "import"


# ----------------------------------------------------------------- geometry


def test_frame_for_target_fits_the_object_not_the_frame():
    # A 1000 px render whose object fills the middle 500 px, fitted into a 100 px box.
    f = frame_for_target(1000, 1000, box(250, 250, 750, 750), box(0, 0, 100, 100))
    assert f == box(-50, -50, 150, 150)
    assert centered_target(1000, 500) == box(200, 100, 800, 400)
    assert map_box(box(0, 0, 10, 10), box(0, 0, 100, 100), box(50, 50, 250, 250)) == box(50, 50, 70, 70)


def test_split_layers_matches_the_photoshop_plugin():
    doc = [
        {"id": "10", "visible": True},
        {"id": "20", "visible": True, "layers": [{"id": "21", "visible": True}, {"id": "22", "visible": True}, {"id": "23", "visible": True}]},
        {"id": "30", "visible": False},
        {"id": "40", "visible": True},
    ]
    assert split_layers(doc, "22", False) == {"hideForBelow": ["10", "21", "22"], "hideForAbove": ["22", "23", "40"], "found": True, "hasAbove": True, "hasBelow": True}
    assert split_layers(doc, "22", True) == {"hideForBelow": ["10", "21"], "hideForAbove": ["22", "23", "40"], "found": True, "hasAbove": True, "hasBelow": True}
    assert split_layers(doc, None, True)["hideForAbove"] == ["10", "20", "40"]
    assert split_layers(doc, "40", False)["hasBelow"] is False


# ------------------------------------------------------------------ import


def test_import_stores_glb_and_hands_other_formats_to_the_browser(tmp_path):
    src = tmp_path / "in"
    shutil.copytree(FIXTURES, src)
    (src / "rocket.glb").write_bytes(fake_glb())
    (src / "notes.txt").write_text("x")
    lib = Library(tmp_path / "data", MemoryLogger())
    lib.load()
    imp = ModelImporter(lib, MemoryLogger(), file_url=lambda i, n: f"./import-file/{i}/{n}")
    batch = imp.import_files([str(src / "rocket.glb"), str(src / "cube.fbx"), str(src / "cube.obj"), str(src / "notes.txt")], into="Props")
    assert [i["name"] for i in batch["imported"]] == ["rocket"] and batch["imported"][0]["folder"] == "Props"
    assert [s["ext"] for s in batch["toConvert"]] == ["fbx", "obj"]
    assert batch["failed"][0]["name"] == "notes.txt" and "not a supported 3D format" in batch["failed"][0]["error"]
    obj = batch["toConvert"][1]
    names = {r["name"] for r in obj["resources"]}
    assert "cube.mtl" in names and any(n.startswith("textures/") for n in names)
    assert obj["url"] == f"./import-file/{obj['id']}/0"
    # The page may read only this import's files.
    assert imp.file_of(obj["id"], 0) == str(src / "cube.obj") and imp.file_of(obj["id"], 999) is None
    with pytest.raises(PermissionError):
        imp.read_file(obj["id"], str(src / "rocket.glb"))
    item = imp.add_converted(obj["id"], "cube", fake_glb(), "obj", ["note"])
    assert item["folder"] == "Props" and item["meta"]["convertedToGlb"] and item["meta"]["notes"] == ["note"]
    with pytest.raises(KeyError):
        imp.add_converted(obj["id"], "again", fake_glb(), "obj")


def test_import_folder_keeps_its_subfolders(tmp_path):
    src = tmp_path / "Kit"
    (src / "Chairs").mkdir(parents=True)
    (src / "a.glb").write_bytes(fake_glb())
    (src / "Chairs" / "b.glb").write_bytes(fake_glb())
    lib = Library(tmp_path / "data", MemoryLogger())
    lib.load()
    batch = ModelImporter(lib, MemoryLogger(), file_url=lambda i, n: "").import_folder(str(src), into="Imports")
    assert sorted((i["name"], i["folder"]) for i in batch["imported"]) == [("a", "Imports/Kit"), ("b", "Imports/Kit/Chairs")]
    assert ext_of("x/Y.FBX") == "fbx"
    assert is_self_contained_gltf({"buffers": [{"uri": "data:application/octet-stream;base64,AA=="}]}) and not is_self_contained_gltf({"buffers": [{"uri": "a.bin"}]})


# ------------------------------------------------------------------ server


@pytest.fixture()
def server(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "editor.html").write_text("<html>editor</html>")
    lib = tmp_path / "library"
    (lib / "lib_a").mkdir(parents=True)
    (lib / "lib_a" / "model.glb").write_bytes(fake_glb())
    (tmp_path / "secret.txt").write_text("private")
    calls = []

    def rpc(session, method, params):
        calls.append((session.kind, method, params))
        if method == "boom":
            raise ValueError("Nope")
        return {"echo": params}

    srv = LocalServer(web, lambda: lib, lambda i, n: None, rpc, MemoryLogger())
    session = srv.open_session("editor", {})
    yield srv, session, calls
    srv.stop()


def _get(url, host=None):
    req = urllib.request.Request(url, headers={"Host": host} if host else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def test_server_serves_session_files_only(server):
    srv, session, _ = server
    base = srv.url(session, "")
    assert _get(base + "editor.html") == (200, b"<html>editor</html>")
    assert _get(base + "library/lib_a/model.glb")[1][:4] == b"glTF"
    assert _get(base + "library/.reachable") == (200, b"ok")
    # Wrong token, escaping the folder, or another host name: nothing.
    assert _get(f"http://127.0.0.1:{srv.port}/s/{'x' * 32}/editor.html")[0] == 404
    assert _get(base + "library/../secret.txt")[0] == 404
    assert _get(base + "..%2F..%2Fsecret.txt")[0] == 404
    assert _get(base + "editor.html", host=f"evil.example:{srv.port}")[0] == 404
    srv.close_session(session)
    assert _get(base + "editor.html")[0] == 404


def test_server_rpc(server):
    srv, session, calls = server

    def post(method, params):
        body = json.dumps({"method": method, "params": params}).encode()
        req = urllib.request.Request(srv.url(session, "rpc"), data=body, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as res:
            return json.loads(res.read())

    assert post("app.info", {"a": 1}) == {"ok": True, "result": {"echo": {"a": 1}}}
    assert post("boom", None) == {"ok": False, "error": "Nope"}
    assert calls[0] == ("editor", "app.info", {"a": 1})
