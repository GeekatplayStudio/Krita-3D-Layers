"""
The plugin: builds every service once per Krita session and connects them to the dockers
(one per Krita window), the menu actions and the browser pages.

Threads: Krita's API and the dockers live on the UI thread. Provider calls run on the job
manager's worker threads; the local server answers the browser on its own threads and hands
every call to the UI thread through `MainThread.call`.
"""
from __future__ import annotations

import base64
import platform
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from krita import Krita  # type: ignore

from .. import __version__
from ..core.geometry import box, centered_target, frame_for_target
from ..core.http import Http
from ..core.importer import ModelImporter
from ..core.jobs import JobManager, is_active
from ..core.library import Library
from ..core.log import Logger
from ..core.providers.base import ProviderContext
from ..core.providers.registry import PROVIDERS, provider
from ..core.secrets import CREDENTIALS_FILE, SecretStore
from ..core.settings import lighting_of, merge, sanitize, settings_for_new_model
from ..core.store import data_root, read_json, write_json
from . import browser, krita_doc
from .qt import QApplication, QObject, QTimer, pyqtSignal
from .server import LocalServer, Session

PLUGIN_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = PLUGIN_DIR / "web"
SAMPLE = PLUGIN_DIR / "samples" / "sample-rocket.glb"
REPO_URL = "https://github.com/GeekatplayStudio/Krita-3D-Layers"
#: An editor window that has not been heard from for this long was closed (or crashed).
EDITOR_TIMEOUT_S = 45


class MainThread(QObject):
    """Runs callables on the Qt UI thread and waits for the result (for the server threads)."""

    request = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.request.connect(self._run)
        self.ui_thread = threading.current_thread()

    def _run(self, task: Callable[[], None]) -> None:
        task()

    def call(self, fn: Callable[[], Any], timeout: float = 600) -> Any:
        if threading.current_thread() is self.ui_thread:
            return fn()
        done = threading.Event()
        out: Dict[str, Any] = {}

        def task() -> None:
            try:
                out["result"] = fn()
            except BaseException as err:  # noqa: BLE001 - re-raised on the calling thread
                out["error"] = err
            finally:
                done.set()

        self.request.emit(task)
        if not done.wait(timeout):
            raise TimeoutError("Krita did not answer in time.")
        if "error" in out:
            raise out["error"]
        return out.get("result")


class Plugin:
    _instance: Optional["Plugin"] = None

    @classmethod
    def get(cls) -> "Plugin":
        if cls._instance is None:
            cls._instance = Plugin()
        return cls._instance

    def __init__(self) -> None:
        self.root = data_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.log = Logger(self.root / "logs" / "krita3d.log")
        self.log.info(f"Geekatplay 3D Layers for Krita {__version__} starting in Krita {Krita.instance().version()}, Python {sys.version.split()[0]}, {platform.system()} {platform.release()}")
        self.settings_path = self.root / "krita" / "settings.json"
        self.settings = sanitize(read_json(self.settings_path))
        self.secrets = SecretStore(self.root)
        self.http = Http(log=self.log)
        self.library = Library(self.root, self.log)
        self.library.load()
        self.jobs = JobManager(self.root, self.log, self.library, provider, self.provider_context)
        self.jobs.load()
        self.importer = ModelImporter(self.library, self.log, file_url=lambda import_id, n: f"./import-file/{import_id}/{n}")
        self.main = MainThread()
        self.server = LocalServer(WEB_DIR, lambda: self.library.dir, self.importer.file_of, self._rpc, self.log)
        self.editor: Optional[Session] = None
        self.views: List[Any] = []
        self._library_dirty = False
        self.library.listeners.append(self._library_changed)
        self.jobs.listeners.append(lambda: self._notify("jobs"))

        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._slow = QTimer()
        self._slow.timeout.connect(self._slow_tick)
        self._slow.start(2500)
        self.log.info(f"Ready: library {len(self.library.items)} models, {sum(1 for j in self.jobs.jobs if is_active(j))} active jobs, data in {self.root}")

    # ------------------------------------------------------------ plumbing

    def provider_context(self) -> ProviderContext:
        return ProviderContext(http=self.http, settings=self.settings, secret=self.secrets.get, log=self.log)

    def attach(self, view: Any) -> None:
        if view not in self.views:
            self.views.append(view)

    def detach(self, view: Any) -> None:
        if view in self.views:
            self.views.remove(view)

    def _notify(self, what: str, *args: Any) -> None:
        for view in list(self.views):
            fn = getattr(view, f"on_{what}", None)
            if fn:
                try:
                    fn(*args)
                except Exception as err:  # noqa: BLE001 - a broken view must not break the plugin
                    self.log.error(f"Docker update ({what}) failed", err)

    def toast(self, message: str, kind: str = "info") -> None:
        self._notify("toast", message, kind)

    def _library_changed(self) -> None:
        # May be called from a job worker thread; the UI thread picks it up in _tick.
        self._library_dirty = True

    def _tick(self) -> None:
        self.jobs.tick()
        if self._library_dirty:
            self._library_dirty = False
            self._notify("library")
        if self.editor and not self.editor.closed and time.time() - self.editor.last_seen > EDITOR_TIMEOUT_S:
            self.log.info("The 3D editor window stopped answering; the session is closed")
            self._end_editor("The 3D editor window was closed.")

    def _slow_tick(self) -> None:
        self.library.refresh_if_changed()  # the Photoshop plugin may have added models

    def update_settings(self, patch: Dict[str, Any], quiet: bool = False) -> None:
        self.settings = merge(self.settings, patch)
        write_json(self.settings_path, self.settings)
        if not quiet:
            self._notify("settings")

    def theme(self) -> str:
        color = QApplication.palette().window().color()
        return "light" if color.lightness() > 128 else "dark"

    # -------------------------------------------------------------- status

    def provider_status(self) -> List[Dict[str, Any]]:
        ctx = self.provider_context()
        out = []
        for pid, p in PROVIDERS.items():
            try:
                c = p.is_configured(ctx)
                out.append({"id": pid, "label": p.label, "configured": c.configured, "hint": c.hint})
            except Exception as err:  # noqa: BLE001
                out.append({"id": pid, "label": p.label, "configured": False, "hint": str(err)})
        return out

    def test_provider(self, provider_id: str, done: Callable[[bool, str], None]) -> None:
        """Runs a connection test on a worker thread; `done(ok, message)` on the UI thread."""
        p, ctx = provider(provider_id), self.provider_context()

        def work() -> None:
            try:
                r = p.test(ctx)
                ok, message = r.ok, r.message + (f" · {r.balance}" if r.balance else "")
            except Exception as err:  # noqa: BLE001
                ok, message = False, str(err)
            self.main.request.emit(lambda: done(ok, message))

        threading.Thread(target=work, name="g3d-test", daemon=True).start()

    # ------------------------------------------------------------- actions

    def generate(self, provider_id: str, source: str, name: str = "") -> Dict[str, Any]:
        img = krita_doc.read_source(source, self.settings["send"]["maxEdge"])
        job = self.jobs.start(provider_id, img["png"], img["width"], img["height"], img["hasAlpha"], name.strip() or img["name"], source_preview=img["preview"], source=img["target"])
        self.log.info(f"Generate: {img['name']} ({img['width']}×{img['height']}, alpha {img['hasAlpha']}) → {provider_id}")
        return job

    def add_sample(self) -> Dict[str, Any]:
        existing = next((i for i in self.library.items if (i.get("meta") or {}).get("sample")), None)
        if existing:
            return existing
        return self.library.add(name="Sample rocket", origin="local", model=SAMPLE.read_bytes(), meta={"sample": True})

    def import_files(self, paths: List[str], into: str = "", folder: bool = False) -> None:
        batch = self.importer.import_folder(paths[0], into) if folder else self.importer.import_files(paths, into)
        if batch["toConvert"]:
            self._open_tasks({"kind": "import", "batch": batch}, f"Converting {len(batch['toConvert'])} file{'s' if len(batch['toConvert']) != 1 else ''} in the browser…")
        else:
            failed = "; ".join(f"{f['name']}: {f['error']}" for f in batch["failed"])
            added = len(batch["imported"])
            self.toast((f"Added {added} model{'s' if added != 1 else ''} to the library." if added else "Nothing was imported.") + (f" Not imported: {failed}" if failed else ""), "error" if failed and not added else "info")
            if added and self.missing_previews():
                self.make_previews()

    def missing_previews(self) -> List[Dict[str, Any]]:
        return [{"id": i["id"], "name": i["name"], "modelFile": i["modelFile"]} for i in self.library.list() if not i.get("thumbFile")]

    def make_previews(self) -> None:
        if not self.missing_previews():
            self.toast("Every model already has a preview.")
            return
        self._open_tasks({"kind": "thumbnails"}, "Rendering previews in the browser…")

    def _open_tasks(self, task: Dict[str, Any], message: str) -> None:
        session = self.server.open_session("tasks", {"task": task})
        how = browser.open_page(self.server.url(session, "tasks.html"), self.settings["editor"]["window"] == "app", size=(520, 260), log=self.log)
        self.log.info(f"Task page ({task['kind']}) opened in the {how}")
        self.toast(message)

    # --------------------------------------------------------- 3D editor

    def _model_init(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {"libraryId": item["id"], "name": item["name"], "url": f"./library/{item['modelFile']}", "file": item["modelFile"], "sizeBytes": item.get("sizeBytes", 0)}

    def place_model(self, library_id: str, job_id: Optional[str] = None) -> None:
        """Opens the 3D editor for a library model; OK places it as a new layer."""
        item = self.library.get(library_id)
        if not item:
            raise krita_doc.DocError("That model is no longer in the library.")
        job = self.jobs.get(job_id) if job_id else None
        source = (job or {}).get("source") or {}
        doc = krita_doc.find_doc(source.get("docKey")) or krita_doc.active_doc()
        if doc is None:
            raise krita_doc.DocError("Open or create an image first: the model is placed into it.")
        node = krita_doc.active_node(doc)
        e = self.settings["editor"]
        init = {
            "mode": "new",
            "model": self._model_init(item),
            "settings": settings_for_new_model(e["lighting"] if e["rememberLighting"] else None, e["defaultResolution"]),
            "lighting": e["lighting"],
            "rememberLighting": e["rememberLighting"],
            "document": {"title": krita_doc.doc_title(doc), "width": doc.width(), "height": doc.height()},
            "view": e["view"],
            "makeThumbnail": not item.get("thumbFile"),
        }
        target = {"docKey": krita_doc.doc_key(doc), "splitId": krita_doc.node_id(node) if node is not None else None, "belowSplit": True, "source": source if source.get("docKey") == krita_doc.doc_key(doc) else None}
        self._open_editor(init, target, item)

    def edit_active_layer(self) -> None:
        doc = krita_doc.active_doc()
        node = krita_doc.active_node(doc) if doc is not None else None
        if node is None:
            raise krita_doc.DocError("Select a 3D layer first.")
        state = krita_doc.layer_state(doc, krita_doc.node_id(node))
        if not state:
            raise krita_doc.DocError(f'"{node.name()}" is not a 3D layer made by this plugin.')
        item = self.library.get(state.get("libraryId", "")) or (self.library.find_by_remote(state.get("origin", ""), state["remoteId"]) if state.get("remoteId") else None)
        if not item:
            raise krita_doc.DocError(f'The model "{state.get("modelName")}" is not in this computer\'s library. Import its GLB in the Library tab, then try again.')
        e = self.settings["editor"]
        init = {
            "mode": "update",
            "model": self._model_init(item),
            "settings": state.get("settings") or settings_for_new_model(e["lighting"], e["defaultResolution"]),
            "lighting": e["lighting"],
            "rememberLighting": e["rememberLighting"],
            "document": {"title": krita_doc.doc_title(doc), "width": doc.width(), "height": doc.height()},
            "view": e["view"],
            "makeThumbnail": not item.get("thumbFile"),
        }
        target = {"docKey": krita_doc.doc_key(doc), "splitId": krita_doc.node_id(node), "belowSplit": False, "layerId": krita_doc.node_id(node)}
        self._open_editor(init, target, item)

    def _open_editor(self, init: Dict[str, Any], target: Dict[str, Any], item: Dict[str, Any]) -> None:
        if self.editor and not self.editor.closed:
            self._end_editor("Another model was opened in the 3D editor.")
        session = self.server.open_session("editor", {"init": init, "target": target, "item": item})
        self.editor = session
        how = browser.open_page(self.server.url(session, "editor.html"), self.settings["editor"]["window"] == "app", log=self.log)
        self.log.info(f"3D editor ({init['mode']}) for {item['name']} opened in the {how}")
        self._notify("editor", {"open": True, "mode": init["mode"], "name": item["name"]})

    def _end_editor(self, message: Optional[str] = None) -> None:
        if self.editor:
            self.server.close_session(self.editor)
        self.editor = None
        self._notify("editor", {"open": False, "message": message})

    def cancel_editor(self) -> None:
        self._end_editor("The 3D editor was closed without changes.")

    def _state_for(self, item: Dict[str, Any], settings3d: Dict[str, Any]) -> Dict[str, Any]:
        state = {"v": 1, "libraryId": item["id"], "modelName": item["name"], "origin": item.get("origin"), "settings": settings3d, "updatedAt": int(time.time() * 1000)}
        if item.get("remoteId"):
            state["remoteId"] = item["remoteId"]
        return state

    def _complete(self, session: Session, result: Dict[str, Any]) -> Dict[str, Any]:
        init, target, item = session.data["init"], session.data["target"], session.data["item"]
        png = base64.b64decode(result["pngBase64"])
        rw, rh = int(result["width"]), int(result["height"])
        content = result.get("contentBounds")
        state = self._state_for(item, result["settings"])
        if init["mode"] == "update":
            placed = krita_doc.update_render(target["docKey"], target["layerId"], png, rw, rh, content, state)
            self.log.info(f"Updated 3D layer {placed['layerName']} ({rw}×{rh})")
            self.toast(f"Updated {placed['layerName']}.")
        else:
            frame = result.get("frame")
            if not frame:
                doc = krita_doc.find_doc(target["docKey"])
                src = (target.get("source") or {}).get("bounds")
                aim = box(src["left"], src["top"], src["right"], src["bottom"]) if src else centered_target(doc.width(), doc.height()) if doc else box(0, 0, rw, rh)
                frame = frame_for_target(rw, rh, content, aim)
            placed = krita_doc.place_render(target["docKey"], png, rw, content, frame, state, f"{item['name']} (3D)", target.get("splitId"))
            if self.settings["editor"]["rememberLighting"]:
                self.update_settings({"editor": {"lighting": lighting_of(result["settings"])}}, quiet=True)
            self.log.info(f"Placed 3D layer {placed['layerName']} ({rw}×{rh})")
            self.toast(f"Placed {placed['layerName']}.")
        session.data["done"] = True
        self._end_editor()
        self._notify("context")
        return placed

    def _document_view(self, session: Session) -> Any:
        if "documentView" not in session.data:
            target = session.data["target"]
            doc = krita_doc.find_doc(target["docKey"])
            if doc is None:
                return None
            frame = None
            if target.get("layerId"):
                node = krita_doc.find_node(doc, target["layerId"])
                state = krita_doc.layer_state(doc, target["layerId"]) or {}
                frame = krita_doc.current_frame(doc, node, state) if node is not None else None
            started = time.time()
            view = krita_doc.document_view(target["docKey"], target.get("splitId"), target["belowSplit"], frame)
            self.log.info(f"Read the document for the 3D editor in {int((time.time() - started) * 1000)} ms", {"below": bool(view["below"]), "above": bool(view["above"]), "frame": frame})
            session.data["documentView"] = view
        return session.data["documentView"]

    # ------------------------------------------------------------------ RPC

    def app_info(self) -> Dict[str, Any]:
        return {
            "pluginId": "geekatplay_3d_layers",
            "pluginVersion": __version__,
            "hostName": "Krita",
            "hostVersion": Krita.instance().version(),
            "uxpVersion": "",
            "platform": sys.platform,
            "dataFolder": str(self.root),
            "libraryFolder": str(self.library.dir),
            "importFolder": str(self.library.dir / "Import"),
            "logFile": str(self.log.path),
            "libraryBaseUrl": "./library/",
            "repoUrl": REPO_URL,
            "theme": self.theme(),
            "credentialsFile": str(self.root / CREDENTIALS_FILE),
            "buildStamp": __version__,
            "channel": "github",
        }

    def _rpc(self, session: Session, method: str, params: Any) -> Any:
        """Calls from the browser pages (server threads)."""
        p = params if isinstance(params, dict) else {}
        if method == "editor.ping":
            return None
        if method == "log.write":
            level = p.get("level") if p.get("level") in Logger.LEVELS else "info"
            getattr(self.log, level)(str(p.get("message", ""))[:2000], p.get("data"))
            return None
        if method == "app.info":
            return self.main.call(self.app_info)
        if method == "library.readFile":
            return {"base64": base64.b64encode(self.library.path(str(p.get("file", ""))).read_bytes()).decode("ascii")}
        if method == "library.saveThumbnail":
            item = self.library.set_thumbnail(str(p["id"]), base64.b64decode(p["pngBase64"]))
            return item
        if session.kind == "editor":
            if session is not self.editor:
                raise ValueError("This 3D editor session has ended. Open the model again from Krita.")
            if method == "editor.getInit":
                return session.data["init"]
            if method == "editor.documentView":
                return self.main.call(lambda: self._document_view(session))
            if method == "editor.complete":
                return self.main.call(lambda: self._complete(session, p), timeout=900)
            if method == "editor.cancel":
                self.main.call(self.cancel_editor)
                return None
            if method == "editor.rememberLighting":
                if self.settings["editor"]["rememberLighting"] and session.data["init"]["mode"] == "new":
                    self.main.call(lambda: self.update_settings({"editor": {"lighting": p}}, quiet=True))
                return None
            if method == "editor.rememberView":
                self.main.call(lambda: self.update_settings({"editor": {"view": p}}, quiet=True))
                return None
        if session.kind == "tasks":
            if method == "tasks.get":
                return session.data["task"]
            if method == "tasks.missingThumbnails":
                return self.missing_previews()
            if method == "library.readImportFile":
                return {"base64": base64.b64encode(self.importer.read_file(str(p["id"]), str(p["path"]))).decode("ascii")}
            if method == "library.addConverted":
                return self.importer.add_converted(str(p["id"]), str(p.get("name", "")), base64.b64decode(p["glbBase64"]), str(p.get("sourceFormat", "")), p.get("notes"))
            if method == "library.importFailed":
                self.importer.import_failed(str(p["id"]), str(p.get("error", "")))
                return None
            if method == "tasks.done":
                self.main.call(lambda: self._tasks_done(session, p))
                return None
        raise ValueError(f"Unknown call {method}")

    def _tasks_done(self, session: Session, report: Dict[str, Any]) -> None:
        self.server.close_session(session)
        added, previews = int(report.get("added") or 0), int(report.get("previews") or 0)
        failed = report.get("failed") or []
        parts = []
        if added:
            parts.append(f"Added {added} model{'s' if added != 1 else ''} to the library.")
        if previews:
            parts.append(f"Made {previews} preview{'s' if previews != 1 else ''}.")
        if failed:
            parts.append("Not imported: " + "; ".join(f"{f.get('name')}: {f.get('error')}" for f in failed))
        self.toast(" ".join(parts) or "Done.", "error" if failed else "info")
        self._notify("library")

    # ------------------------------------------------------------ shutdown

    def shutdown(self) -> None:
        self.log.info("Krita is closing")
        self._timer.stop()
        self._slow.stop()
        self.jobs.shutdown()
        self.server.stop()
