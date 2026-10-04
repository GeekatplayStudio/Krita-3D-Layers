"""
The local model library: <data folder>/library/ (shared with the Photoshop plugin).

    library/index.json        {"version": 1, "items": [LibraryItem...], "folders": [...]}
    library/<id>/model.glb    the model, exactly as downloaded
    library/<id>/thumb.png    preview (service render, or rendered by the 3D editor)
    library/<id>/source.png   the layer pixels that generated it (when made here)
    library/<id>/info.json    human-readable copy of the item

The format is the Photoshop plugin's (src/host/services/library.ts), field for field, so
both plugins read and write the same library. Folders are virtual: each item has a
`folder` path and the index keeps the folder list, so empty folders exist too. Before
every change the index is read again if another program changed it.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from .store import new_id, read_json, sniff_format, write_bytes, write_json

LIBRARY_DIR = "library"
IMPORT_DIR = "Import"
_THUMB_EXT = {"png": "png", "jpg": "jpg", "webp": "webp"}

# ------------------------------------------------------------- folder paths
# (a port of the Photoshop plugin's src/shared/libraryFolders.ts)

_BAD_NAME = re.compile(r'[/\\:*?"<>|\x00-\x1f]')
MAX_FOLDER_NAME = 60


def clean_folder_name(name: str) -> str:
    return re.sub(r"\s+", " ", _BAD_NAME.sub(" ", name)).strip()[:MAX_FOLDER_NAME].strip()


def normalize_folder(path: Any) -> str:
    if not isinstance(path, str):
        return ""
    return "/".join(p for p in (clean_folder_name(x) for x in re.split(r"[/\\]+", path)) if p)


def join_folder(parent: str, child: str) -> str:
    return normalize_folder(f"{parent}/{child}" if parent else child)


def parent_folder(path: str) -> str:
    return path[: path.rfind("/")] if "/" in path else ""


def folder_name(path: str) -> str:
    return path[path.rfind("/") + 1 :]


def is_in_folder(path: str, folder: str) -> bool:
    return not folder or path == folder or path.startswith(folder + "/")


def with_ancestors(path: str) -> List[str]:
    parts = [p for p in normalize_folder(path).split("/") if p]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def _sort_key(path: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path)]


def child_folders(folders: Iterable[str], parent: str) -> List[str]:
    return sorted((f for f in folders if parent_folder(f) == parent and f != parent), key=lambda f: _sort_key(folder_name(f)))


def rebase(path: str, src: str, dst: str) -> str:
    return dst if path == src else join_folder(dst, path[len(src) + 1 :])


def all_folders(stored: Iterable[str], items: Iterable[Dict[str, Any]]) -> List[str]:
    found = set()
    for f in list(stored) + [i.get("folder") or "" for i in items]:
        found.update(with_ancestors(f))
    return sorted(found, key=_sort_key)


def relocate_folder(stored: Iterable[str], items: List[Dict[str, Any]], src: str, dst: str) -> set:
    nxt = set()
    for f in stored:
        moved = rebase(f, src, dst) if is_in_folder(f, src) else f
        if moved:
            nxt.add(moved)
    for item in items:
        f = item.get("folder") or ""
        if not f or not is_in_folder(f, src):
            continue
        moved = rebase(f, src, dst)
        if moved:
            item["folder"] = moved
        else:
            item.pop("folder", None)
    if dst:
        nxt.update(with_ancestors(dst))
    return nxt


# ------------------------------------------------------------------ library


class Library:
    def __init__(self, root: Path, log: Any, now: Callable[[], float] = lambda: int(time.time() * 1000)):
        self.dir = root / LIBRARY_DIR
        self.index_path = self.dir / "index.json"
        self.log = log
        self.now = now
        self.items: List[Dict[str, Any]] = []
        self.folder_list: set = set()
        self._mtime = -1.0
        self._lock = threading.RLock()
        self.listeners: List[Callable[[], None]] = []

    # ---- loading and sharing with the Photoshop plugin

    def _index_mtime(self) -> float:
        try:
            return self.index_path.stat().st_mtime
        except OSError:
            return 0.0

    def load(self) -> None:
        with self._lock:
            data = read_json(self.index_path)
            items = data.get("items") if isinstance(data, dict) else None
            self.items = [i for i in (items or []) if isinstance(i, dict) and isinstance(i.get("id"), str) and isinstance(i.get("modelFile"), str)]
            for item in self.items:
                folder = normalize_folder(item.get("folder"))
                if folder:
                    item["folder"] = folder
                else:
                    item.pop("folder", None)
            folders = data.get("folders") if isinstance(data, dict) else None
            self.folder_list = {f for f in (normalize_folder(x) for x in (folders or [])) if f}
            present = [i for i in self.items if (self.dir / i["modelFile"]).exists()]
            if len(present) != len(self.items):
                for gone in (i for i in self.items if i not in present):
                    self.log.warn(f"Library: {gone.get('name')} ({gone['id']}) is missing its model file; removing it from the index")
                self.items = present
                self._persist()
            self._mtime = self._index_mtime()

    def refresh_if_changed(self) -> bool:
        """Reloads when another program (the Photoshop plugin) changed the index. True if it did."""
        with self._lock:
            if self._index_mtime() == self._mtime:
                return False
            self.load()
        self._notify()
        return True

    def _persist(self) -> None:
        write_json(self.index_path, {"version": 1, "items": self.items, "folders": sorted(self.folder_list)})
        self._mtime = self._index_mtime()

    def _changed(self) -> None:
        self._persist()
        self._notify()

    def _notify(self) -> None:
        for fn in list(self.listeners):
            try:
                fn()
            except Exception as err:  # noqa: BLE001 - a broken listener must not break the library
                self.log.error("Library listener failed", err)

    def _fresh(self) -> None:
        """Called under the lock before a change: pick up changes made elsewhere first."""
        if self._index_mtime() != self._mtime:
            self.load()

    # ---- reading

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return sorted(self.items, key=lambda i: (not i.get("favorite"), -(i.get("importedAt") or 0)))

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return next((i for i in self.items if i["id"] == item_id), None)

    def find_by_remote(self, origin: str, remote_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return next((i for i in self.items if i.get("origin") == origin and i.get("remoteId") == remote_id), None)

    def folders(self) -> List[str]:
        with self._lock:
            return all_folders(self.folder_list, self.items)

    def path(self, file: str) -> Path:
        """Library-relative path → absolute path (refuses anything outside the library)."""
        p = (self.dir / file).resolve()
        if self.dir.resolve() not in p.parents and p != self.dir.resolve():
            raise ValueError("Path outside the library")
        return p

    # ---- changing

    def add(
        self,
        name: str,
        origin: str,
        model: bytes,
        remote_id: Optional[str] = None,
        thumbnail: Optional[bytes] = None,
        source: Optional[bytes] = None,
        created_at: Optional[float] = None,
        meta: Optional[Dict[str, Any]] = None,
        folder: str = "",
    ) -> Dict[str, Any]:
        kind = sniff_format(model)
        if kind not in ("glb", "gltf"):
            raise ValueError(f"The file is not a glTF/GLB model (looks like {kind or 'unknown data'}).")
        with self._lock:
            self._fresh()
            item_id = new_id("lib")
            model_file = f"{item_id}/model.{kind}"
            write_bytes(self.dir / model_file, model)
            item: Dict[str, Any] = {"id": item_id, "name": (name or "").strip() or "3D model", "origin": origin}
            if remote_id:
                item["remoteId"] = remote_id
            item["modelFile"] = model_file
            if thumbnail and _THUMB_EXT.get(sniff_format(thumbnail) or ""):
                item["thumbFile"] = f"{item_id}/thumb.{_THUMB_EXT[sniff_format(thumbnail)]}"  # type: ignore[index]
                write_bytes(self.dir / item["thumbFile"], thumbnail)
            if source:
                item["sourceFile"] = f"{item_id}/source.png"
                write_bytes(self.dir / item["sourceFile"], source)
            now = self.now()
            item.update({"format": kind, "sizeBytes": len(model), "createdAt": created_at or now, "importedAt": now})
            if meta:
                item["meta"] = meta
            f = normalize_folder(folder)
            if f:
                item["folder"] = f
                self.folder_list.update(with_ancestors(f))
            write_bytes(self.dir / item_id / "info.json", json.dumps(item, indent=2).encode("utf-8"))
            self.items.append(item)
            self._changed()
        self.log.info(f"Library: added {item['name']} ({item_id}, {origin}{' ' + remote_id if remote_id else ''}, {len(model)} bytes)")
        return item

    def update(self, item_id: str, name: Optional[str] = None, favorite: Optional[bool] = None) -> Dict[str, Any]:
        with self._lock:
            self._fresh()
            item = self._must(item_id)
            if isinstance(name, str) and name.strip():
                item["name"] = name.strip()[:120]
            if isinstance(favorite, bool):
                item["favorite"] = favorite
            self._changed()
            return item

    def set_thumbnail(self, item_id: str, png: bytes) -> Dict[str, Any]:
        if sniff_format(png) != "png":
            raise ValueError("Thumbnail must be a PNG.")
        with self._lock:
            self._fresh()
            item = self._must(item_id)
            old = item.get("thumbFile")
            if old and not old.endswith(".png"):
                try:
                    (self.dir / old).unlink()
                except OSError:
                    pass
            item["thumbFile"] = f"{item_id}/thumb.png"
            write_bytes(self.dir / item["thumbFile"], png)
            self._changed()
            return item

    def remove_many(self, ids: Iterable[str]) -> None:
        """Deletes models and their files. Layers already placed keep their pixels."""
        ids = set(ids)
        with self._lock:
            self._fresh()
            gone = [i for i in self.items if i["id"] in ids]
            if not gone:
                return
            for item in gone:
                # Keep the folder, so removing its last model does not make it disappear.
                if item.get("folder"):
                    self.folder_list.update(with_ancestors(item["folder"]))
                shutil.rmtree(self.dir / item["id"], ignore_errors=True)
            self.items = [i for i in self.items if i["id"] not in ids]
            self._changed()
        self.log.info("Library: removed " + ", ".join(f"{i.get('name')} ({i['id']})" for i in gone))

    def move(self, ids: Iterable[str], folder: str) -> None:
        """Moves models into a folder ("" = top level); the folder is created if needed."""
        ids = set(ids)
        target = normalize_folder(folder)
        with self._lock:
            self._fresh()
            for item in self.items:
                if item["id"] in ids:
                    if target:
                        item["folder"] = target
                    else:
                        item.pop("folder", None)
            self.folder_list.update(with_ancestors(target))
            self._changed()

    def create_folder(self, parent: str, name: str) -> List[str]:
        clean = clean_folder_name(name)
        if not clean:
            raise ValueError("Type a folder name.")
        path = join_folder(normalize_folder(parent), clean)
        with self._lock:
            self._fresh()
            if any(f.lower() == path.lower() for f in self.folders()):
                raise ValueError(f'There is already a folder named "{clean}" here.')
            self.folder_list.update(with_ancestors(path))
            self._changed()
            return self.folders()

    def rename_folder(self, path: str, name: str) -> List[str]:
        src = normalize_folder(path)
        clean = clean_folder_name(name)
        if not src:
            raise ValueError("The top level of the library cannot be renamed.")
        if not clean:
            raise ValueError("Type a folder name.")
        dst = join_folder(parent_folder(src), clean)
        if dst == src:
            return self.folders()
        with self._lock:
            self._fresh()
            if any(f.lower() == dst.lower() and f.lower() != src.lower() for f in self.folders()):
                raise ValueError(f'There is already a folder named "{clean}" here.')
            self.folder_list = relocate_folder(self.folder_list, self.items, src, dst)
            self._changed()
            return self.folders()

    def delete_folder(self, path: str) -> List[str]:
        """Deletes a folder. Its models and subfolders move to its parent; no model is deleted."""
        folder = normalize_folder(path)
        if not folder:
            raise ValueError("The top level of the library cannot be deleted.")
        with self._lock:
            self._fresh()
            self.folder_list = relocate_folder(self.folder_list, self.items, folder, parent_folder(folder))
            self._changed()
            return self.folders()

    def _must(self, item_id: str) -> Dict[str, Any]:
        item = next((i for i in self.items if i["id"] == item_id), None)
        if not item:
            raise KeyError("That model is no longer in the library.")
        return item


def import_model_result(http: Any, library: Library, log: Any, result: Any, name: str, origin: str, remote_id: Optional[str] = None, source: Optional[bytes] = None, on_progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """
    A finished provider task → library entry. Downloads the model (and its preview, best
    effort) right away: provider links are signed and expire within hours.
    """
    progress = on_progress or (lambda _m: None)
    progress("Downloading model")
    model = http.download(result.model_url, headers=result.headers, label="Model download")
    kind = sniff_format(model)
    if kind == "zip":
        raise ValueError("The service returned a ZIP archive instead of a GLB. Choose GLB output for this service.")
    if kind == "gltf" and re.search(r'"uri"\s*:\s*"(?!data:)', model[:2_000_000].decode("utf-8", errors="replace")):
        raise ValueError("This .gltf references external files, which cannot be stored on their own. Use GLB output instead.")
    thumbnail = None
    if result.thumbnail_url:
        progress("Downloading preview")
        try:
            thumbnail = http.download(result.thumbnail_url, timeout=60, max_bytes=20 * 1024 * 1024, label="Preview download")
        except Exception as err:  # noqa: BLE001 - the preview is a convenience; the editor renders one instead
            log.warn("Preview could not be downloaded", str(err))
    progress("Saving to library")
    return library.add(name=name or result.name or "3D model", origin=origin, model=model, remote_id=remote_id, thumbnail=thumbnail, source=source, created_at=result.created_at, meta=result.meta or None)
