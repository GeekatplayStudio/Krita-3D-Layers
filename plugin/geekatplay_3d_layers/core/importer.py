"""
Importing 3D files from disk into the library (a port of the Photoshop plugin's
src/host/services/modelImport.ts, without the Import-folder inbox).

- GLB (and a .gltf with everything inline) is stored as it is.
- Every other format (FBX, OBJ, DAE, USDZ, STL, PLY, 3MF, 3DS, …) is converted to GLB by
  the task page in the browser (three.js loaders + GLTFExporter): this module returns an
  ImportSource with URLs for the file and the material/texture files found next to it,
  and the page converts it and calls add_converted (or import_failed).
- An imported folder becomes a library folder of the same name, with its subfolders.

Files are only served to the page if they belong to an import started here (`sessions`).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .library import Library, join_folder, normalize_folder, parent_folder
from .store import new_id

MODEL_EXTENSIONS = ("glb", "gltf", "fbx", "obj", "dae", "usdz", "usd", "usda", "usdc", "3ds", "stl", "ply", "3mf", "amf", "wrl", "vox")
RESOURCE_EXTENSIONS = ("mtl", "bin", "png", "jpg", "jpeg", "tga", "bmp", "gif", "webp", "tif", "tiff")
SUPPORTED_FORMATS_TEXT = ", ".join(e.upper() for e in MODEL_EXTENSIONS if e not in ("usda", "usdc"))
MAX_MODELS_PER_FOLDER = 500
MAX_RESOURCES = 1500
MAX_ENTRIES_VISITED = 20_000
FOLDER_DEPTH = 4
RESOURCE_DEPTH = 3


def ext_of(name: str) -> str:
    base = os.path.basename(name)
    dot = base.rfind(".")
    return base[dot + 1 :].lower() if dot > 0 else ""


def strip_ext(name: str) -> str:
    base = os.path.basename(name)
    dot = base.rfind(".")
    return base[:dot] if dot > 0 else base


def is_model_file(name: str) -> bool:
    return ext_of(name) in MODEL_EXTENSIONS


def is_resource_file(name: str) -> bool:
    return ext_of(name) in RESOURCE_EXTENSIONS


def is_self_contained_gltf(data: Any) -> bool:
    if not isinstance(data, dict):
        return False

    def inline(uri: Any) -> bool:
        return uri is None or (isinstance(uri, str) and uri.startswith("data:"))

    return all(inline(b.get("uri")) for b in data.get("buffers") or [] if isinstance(b, dict)) and all(inline(i.get("uri")) for i in data.get("images") or [] if isinstance(i, dict))


def walk(root: str, depth: int) -> List[Tuple[str, str]]:
    """(path, relative path) of files under `root`, breadth first, up to `depth` levels of subfolders."""
    out: List[Tuple[str, str]] = []
    visited = 0
    level = [(root, "")]
    for d in range(depth + 1):
        if not level:
            break
        nxt = []
        for folder, rel in level:
            try:
                entries = sorted(os.scandir(folder), key=lambda e: e.name.lower())
            except OSError:
                if d == 0:
                    raise
                continue
            for e in entries:
                visited += 1
                if visited > MAX_ENTRIES_VISITED:
                    return out
                if e.name.startswith("."):
                    continue
                relative = f"{rel}/{e.name}" if rel else e.name
                if e.is_dir():
                    nxt.append((e.path, relative))
                else:
                    out.append((e.path, relative))
        level = nxt
    return out


class ModelImporter:
    def __init__(self, library: Library, log: Any, file_url: Callable[[str, int], str]):
        """`file_url(import id, index)` is the URL the task page reads a session's file from."""
        self.library = library
        self.log = log
        self.file_url = file_url
        #: import id → {"path", "folder", "files": [paths the page may read]}
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def import_files(self, paths: List[str], into: str = "") -> Dict[str, Any]:
        """Imports picked files into a library folder ("" = top level)."""
        return self._import_placed([(p, normalize_folder(into)) for p in paths])

    def import_folder(self, folder: str, into: str = "") -> Dict[str, Any]:
        """Every model file in a folder and its subfolders; the folder becomes a library folder."""
        models = [(p, rel) for p, rel in walk(folder, FOLDER_DEPTH) if is_model_file(p)][:MAX_MODELS_PER_FOLDER]
        if not models:
            return {"imported": [], "toConvert": [], "failed": [{"name": folder, "error": "No 3D model files were found in this folder."}]}
        target = join_folder(normalize_folder(into), os.path.basename(folder.rstrip("\\/")))
        return self._import_placed([(p, join_folder(target, parent_folder(rel))) for p, rel in models])

    def _import_placed(self, files: List[Tuple[str, str]]) -> Dict[str, Any]:
        batch: Dict[str, Any] = {"imported": [], "toConvert": [], "failed": []}
        for path, folder in files:
            self._import_one(path, batch, folder)
        self.log.info(f"Import: {len(batch['imported'])} stored, {len(batch['toConvert'])} to convert, {len(batch['failed'])} failed", [p for p, _ in files])
        return batch

    def _import_one(self, path: str, batch: Dict[str, Any], folder: str) -> None:
        ext = ext_of(path)
        name = strip_ext(path)
        try:
            if ext not in MODEL_EXTENSIONS:
                raise ValueError(f"not a supported 3D format ({SUPPORTED_FORMATS_TEXT})")
            if ext == "glb":
                data = Path(path).read_bytes()
                batch["imported"].append(self.library.add(name=name, origin="local", model=data, folder=folder, meta={"importedFrom": path, "sourceFormat": ext}))
                return
            if ext == "gltf":
                data = Path(path).read_bytes()
                try:
                    parsed = json.loads(data.decode("utf-8-sig"))
                except ValueError:
                    raise ValueError("this .gltf file is not valid JSON") from None
                if is_self_contained_gltf(parsed):
                    batch["imported"].append(self.library.add(name=name, origin="local", model=data, folder=folder, meta={"importedFrom": path, "sourceFormat": ext}))
                    return
            import_id = new_id("imp")
            folder_of_file = os.path.dirname(path)
            resources = [(p, rel) for p, rel in walk(folder_of_file, RESOURCE_DEPTH) if is_resource_file(p)][:MAX_RESOURCES]
            files = [path] + [p for p, _ in resources]
            self.sessions[import_id] = {"path": path, "folder": folder, "files": files}
            batch["toConvert"].append(
                {
                    "id": import_id,
                    "name": name,
                    "ext": ext,
                    "url": self.file_url(import_id, 0),
                    "path": path,
                    "resources": [{"name": rel, "url": self.file_url(import_id, i + 1), "path": p} for i, (p, rel) in enumerate(resources)],
                }
            )
        except Exception as err:  # noqa: BLE001 - one bad file must not stop the others
            self.log.warn(f"Import of {path} failed", str(err))
            batch["failed"].append({"name": f"{name}.{ext}", "error": str(err)})

    def file_of(self, import_id: str, index: int) -> Optional[str]:
        session = self.sessions.get(import_id)
        if not session or not 0 <= index < len(session["files"]):
            return None
        return session["files"][index]

    def read_file(self, import_id: str, path: str) -> bytes:
        session = self.sessions.get(import_id)
        if not session or path not in session["files"]:
            raise PermissionError("That file is not part of this import.")
        return Path(path).read_bytes()

    def add_converted(self, import_id: str, name: str, glb: bytes, source_format: str, notes: Optional[List[str]] = None) -> Dict[str, Any]:
        session = self.sessions.get(import_id)
        if not session:
            raise KeyError("This import is no longer active. Import the file again.")
        meta: Dict[str, Any] = {"importedFrom": session["path"], "sourceFormat": source_format, "convertedToGlb": True}
        if notes:
            meta["notes"] = notes
        item = self.library.add(name=name.strip() or strip_ext(session["path"]), origin="local", model=glb, folder=session["folder"], meta=meta)
        del self.sessions[import_id]
        self.log.info(f"Imported {session['path']} ({source_format} → GLB, {len(glb)} bytes) as {item['id']}")
        return item

    def import_failed(self, import_id: str, error: str) -> None:
        session = self.sessions.pop(import_id, None)
        if session:
            self.log.warn(f"Import of {session['path']} failed", error)
