"""
The "3D Layers" docker: Create (send a layer to a 3D service, follow the jobs), Library
(every model on this computer, shared with the Photoshop plugin) and Settings.

Krita makes one docker per window; they all show the same plugin state (ui/app.py).
"""
from __future__ import annotations

import base64
import os
from typing import Any, Callable, Dict, List, Optional

from krita import DockWidget  # type: ignore

from ..core.importer import MODEL_EXTENSIONS, SUPPORTED_FORMATS_TEXT, is_model_file
from ..core.jobs import is_active
from ..core.library import folder_name, is_in_folder
from ..core.providers.base import PROVIDER_IDS, PROVIDER_LABELS
from ..core.secrets import preview
from ..core.settings import HITEM3D_MODELS, HITEM3D_RESOLUTIONS, MESHY_AI_MODELS, TRIPO_MODEL_VERSIONS
from . import krita_doc
from .qt import (
    E, QAbstractItemView, QCheckBox, QColor, QComboBox, QDesktopServices, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QIcon, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPainter, QPixmap, QProgressBar, QPushButton, QScrollArea, QSize, QSizePolicy, QSpinBox, QTabWidget, Qt, QTimer,
    QToolButton, QUrl, QVBoxLayout, QWidget, exec_,
)

USER_ROLE = E(Qt, "ItemDataRole", "UserRole")
SMOOTH = E(Qt, "TransformationMode", "SmoothTransformation")
KEEP = E(Qt, "AspectRatioMode", "KeepAspectRatio")
ALIGN_TOP = E(Qt, "AlignmentFlag", "AlignTop")
SOURCES = [("auto", "Selection if any, else layer"), ("layer", "Active layer"), ("selection", "Selection")]
KEY_LINKS = {
    "meshy": "https://www.meshy.ai/developers/keys",
    "tripo": "https://platform.tripo3d.ai/api-keys",
    "hitem3d": "https://platform.hi3d.ai/console/apiKey",
}


def _plugin():
    from .app import Plugin

    return Plugin.get()


def _pixmap_from_data_url(url: str, size: int) -> QPixmap:
    pm = QPixmap()
    try:
        pm.loadFromData(base64.b64decode(url.split(",", 1)[1]))
    except (IndexError, ValueError):
        return QPixmap()
    return pm.scaled(size, size, KEEP, SMOOTH)


def _placeholder(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setPen(QColor(150, 150, 160))
    font = p.font()
    font.setPointSize(max(8, size // 6))
    font.setBold(True)
    p.setFont(font)
    p.drawRect(2, 2, size - 5, size - 5)
    p.drawText(pm.rect(), E(Qt, "AlignmentFlag", "AlignCenter"), "3D")
    p.end()
    return pm


def _label(text: str = "", wrap: bool = True, small: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(wrap)
    if small:
        f = lab.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() * 0.9))
        lab.setFont(f)
    return lab


def _button(text: str, fn: Callable[[], None], tip: str = "") -> QPushButton:
    b = QPushButton(text)
    b.clicked.connect(lambda _=False: fn())
    if tip:
        b.setToolTip(tip)
    return b


class Guard:
    """Runs a user action and shows a problem as a message instead of a stack trace."""

    def __init__(self, parent: QWidget):
        self.parent = parent

    def __call__(self, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except (krita_doc.DocError, ValueError, KeyError, PermissionError, FileNotFoundError) as err:
            QMessageBox.warning(self.parent, "3D Layers", err.args[0] if isinstance(err, KeyError) and err.args else str(err))
        except Exception as err:  # noqa: BLE001
            try:
                _plugin().log.error("Action failed", err)
            except Exception:  # noqa: BLE001
                pass
            QMessageBox.critical(self.parent, "3D Layers", f"Something went wrong: {err}\n\nDetails are in the log (Settings › Files › Open log).")
        return None


# ---------------------------------------------------------------- Create


class JobRow(QFrame):
    def __init__(self, docker: "ThreeDLayersDocker", job: Dict[str, Any]):
        super().__init__()
        self.docker = docker
        self.job_id = job["id"]
        self.setFrameShape(E(QFrame, "Shape", "StyledPanel"))
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 6, 6, 6)
        self.thumb = QLabel()
        self.thumb.setFixedSize(40, 40)
        row.addWidget(self.thumb, 0, ALIGN_TOP)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = _label()
        f = self.title.font()
        f.setBold(True)
        self.title.setFont(f)
        self.status = _label(small=True)
        self.bar = QProgressBar()
        self.bar.setMaximumHeight(6)
        self.bar.setTextVisible(False)
        self.error = _label(small=True)
        self.error.setStyleSheet("color: #e5534b;")
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(4)
        for w in (self.title, self.status, self.bar, self.error):
            col.addWidget(w)
        col.addLayout(self.buttons)
        row.addLayout(col, 1)
        self.shown_status = None
        pm = _pixmap_from_data_url(job["sourcePreview"], 40) if job.get("sourcePreview") else QPixmap()
        self.thumb.setPixmap(pm if not pm.isNull() else _placeholder(40))
        self.update_job(job)

    def update_job(self, job: Dict[str, Any]) -> None:
        self.title.setText(job.get("name", ""))
        label = PROVIDER_LABELS.get(job.get("providerId"), job.get("providerId"))
        status = job.get("status", "")
        text = {"queued": "Waiting", "submitting": "Sending", "running": "Generating", "downloading": "Downloading", "succeeded": "Ready", "failed": "Failed", "cancelled": "Cancelled"}.get(status, status)
        pct = f" · {job.get('progress', 0)}%" if is_active(job) and job.get("progress") else ""
        msg = f" — {job['message']}" if job.get("message") and status != "succeeded" else ""
        self.status.setText(f"{label} · {text}{pct}{msg}")
        self.bar.setVisible(is_active(job))
        self.bar.setValue(int(job.get("progress") or 0))
        self.error.setText(job.get("error", ""))
        self.error.setVisible(bool(job.get("error")))
        if status != self.shown_status:
            self.shown_status = status
            while self.buttons.count():
                w = self.buttons.takeAt(0).widget()
                if w:
                    w.deleteLater()
            d, jid = self.docker, self.job_id
            if status == "succeeded" and job.get("libraryId"):
                self.buttons.addWidget(_button("Pose && place", lambda: d.guard(lambda: _plugin().place_model(job["libraryId"], jid)), "Open the model in the 3D editor and place it in the image"))
            if status in ("failed", "cancelled"):
                self.buttons.addWidget(_button("Retry", lambda: d.guard(lambda: _plugin().jobs.retry(jid))))
            if is_active(job):
                self.buttons.addWidget(_button("Cancel", lambda: d.guard(lambda: _plugin().jobs.cancel(jid))))
            else:
                self.buttons.addWidget(_button("Remove", lambda: d.guard(lambda: _plugin().jobs.dismiss(jid)), "Remove from this list (the model stays in the library)"))
            self.buttons.addStretch(1)


class CreateTab(QWidget):
    def __init__(self, docker: "ThreeDLayersDocker"):
        super().__init__()
        self.docker = docker
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)

        # 3D layer banner
        self.layer_box = QFrame()
        self.layer_box.setFrameShape(E(QFrame, "Shape", "StyledPanel"))
        lb = QVBoxLayout(self.layer_box)
        self.layer_text = _label()
        lb.addWidget(self.layer_text)
        lrow = QHBoxLayout()
        lrow.addWidget(_button("Edit pose && light", lambda: docker.guard(_plugin().edit_active_layer), "Open this 3D layer in the 3D editor"))
        lrow.addWidget(_button("Detach", self.detach, "Remove the 3D data; the layer becomes an ordinary paint layer"))
        lrow.addStretch(1)
        lb.addLayout(lrow)
        outer.addWidget(self.layer_box)

        # Make a 3D model
        make = QGroupBox("Make a 3D model")
        form = QVBoxLayout(make)
        top = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(56, 56)
        top.addWidget(self.preview, 0, ALIGN_TOP)
        self.source_info = _label(small=True)
        top.addWidget(self.source_info, 1)
        form.addLayout(top)
        fl = QFormLayout()
        self.source = QComboBox()
        for value, text in SOURCES:
            self.source.addItem(text, value)
        self.source.currentIndexChanged.connect(lambda _i: docker.guard(lambda: _plugin().update_settings({"send": {"source": self.source.currentData()}}, quiet=True)))
        fl.addRow("Source", self.source)
        self.service = QComboBox()
        self.service.currentIndexChanged.connect(self._service_changed)
        fl.addRow("3D service", self.service)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name (optional)")
        fl.addRow("Name", self.name)
        form.addLayout(fl)
        self.hint = _label(small=True)
        self.hint.setStyleSheet("color: #d29922;")
        form.addWidget(self.hint)
        self.generate_btn = _button("Generate 3D model", self.generate, "Send the layer or selection to the 3D service")
        form.addWidget(self.generate_btn)
        outer.addWidget(make)

        # Getting started
        self.start_box = QGroupBox("Getting started")
        sb = QVBoxLayout(self.start_box)
        sb.addWidget(_label("No 3D service set up yet? Try the sample model: pose it, light it and place it in your image. Add a service key in Settings to generate your own models.", small=True))
        sb.addWidget(_button("Try the sample model", self.try_sample))
        outer.addWidget(self.start_box)

        # Jobs: the list takes the remaining height; the boxes above keep their natural size.
        for box in (self.layer_box, make, self.start_box):
            box.setSizePolicy(E(QSizePolicy, "Policy", "Preferred"), E(QSizePolicy, "Policy", "Maximum"))
        outer.addWidget(_label("<b>Jobs</b>"))
        self.jobs_area = QScrollArea()
        self.jobs_area.setWidgetResizable(True)
        self.jobs_area.setFrameShape(E(QFrame, "Shape", "NoFrame"))
        self.jobs_host = QWidget()
        self.jobs_layout = QVBoxLayout(self.jobs_host)
        self.jobs_layout.setContentsMargins(0, 0, 0, 0)
        self.jobs_layout.setSpacing(4)
        self.jobs_empty = _label("Models you generate appear here. They are saved in the Library when they are ready.", small=True)
        self.jobs_layout.addWidget(self.jobs_empty)
        self.jobs_layout.addStretch(1)
        self.jobs_area.setWidget(self.jobs_host)
        outer.addWidget(self.jobs_area, 1)
        self.rows: Dict[str, JobRow] = {}
        self.ctx: Dict[str, Any] = {}

    def refresh_settings(self) -> None:
        p = _plugin()
        self.source.blockSignals(True)
        self.source.setCurrentIndex(max(0, [v for v, _ in SOURCES].index(p.settings["send"]["source"])))
        self.source.blockSignals(False)
        self.service.blockSignals(True)
        current = self.service.currentData() or p.settings["defaultProvider"]
        self.service.clear()
        self.status = {s["id"]: s for s in p.provider_status()}
        for pid in PROVIDER_IDS:
            s = self.status[pid]
            self.service.addItem(s["label"] + ("" if s["configured"] else "  (not set up)"), pid)
        self.service.setCurrentIndex(max(0, list(PROVIDER_IDS).index(current)))
        self.service.blockSignals(False)
        self._service_changed()
        self.start_box.setVisible(not p.jobs.jobs)

    def _service_changed(self, *_: Any) -> None:
        pid = self.service.currentData()
        s = getattr(self, "status", {}).get(pid)
        self.hint.setText((s.get("hint") or f"{s['label']} is not set up yet: add it in Settings.") if s and not s["configured"] else "")
        self.hint.setVisible(bool(s and not s["configured"]))
        self._update_button()

    def _update_button(self) -> None:
        s = getattr(self, "status", {}).get(self.service.currentData())
        self.generate_btn.setEnabled(bool(self.ctx.get("hasDocument")) and bool(s and s["configured"]))

    def refresh_context(self, ctx: Dict[str, Any]) -> None:
        self.ctx = ctx
        if not ctx.get("hasDocument"):
            self.source_info.setText("Open an image, then select a layer (or make a selection).")
            self.preview.setPixmap(_placeholder(56))
            self.layer_box.setVisible(False)
        else:
            what = "Selection" if ctx.get("hasSelection") and self.source.currentData() != "layer" else f"Layer: {ctx.get('layerName') or '—'}"
            self.source_info.setText(f"<b>{what}</b><br>{ctx.get('docTitle')} · {ctx.get('docWidth')}×{ctx.get('docHeight')} px<br>Tip: a cut-out object on a transparent background gives the cleanest model.")
            self.layer_box.setVisible(bool(ctx.get("is3DLayer")))
            self.layer_text.setText(f"<b>3D layer</b> · {ctx.get('modelName') or ''}<br>Change the pose or the light any time.")
        self._update_button()

    def refresh_preview(self) -> None:
        """A small picture of what would be sent (the active layer)."""
        doc = krita_doc.active_doc()
        node = krita_doc.active_node(doc) if doc is not None else None
        if node is None:
            return
        rect = node.bounds()
        if rect.width() <= 0 or rect.height() <= 0:
            self.preview.setPixmap(_placeholder(56))
            return
        s = 56 / max(rect.width(), rect.height())
        img = node.thumbnail(max(1, round(rect.width() * s)), max(1, round(rect.height() * s)))
        self.preview.setPixmap(QPixmap.fromImage(img))

    def refresh_jobs(self) -> None:
        jobs = _plugin().jobs.list()
        ids = [j["id"] for j in jobs]
        for jid in list(self.rows):
            if jid not in ids:
                self.rows.pop(jid).deleteLater()
        for i, job in enumerate(jobs):
            row = self.rows.get(job["id"])
            if row is None:
                row = self.rows[job["id"]] = JobRow(self.docker, job)
                self.jobs_layout.insertWidget(i, row)
            else:
                row.update_job(job)
        self.jobs_empty.setVisible(not jobs)
        self.start_box.setVisible(not jobs)

    def generate(self) -> None:
        def run():
            job = _plugin().generate(self.service.currentData(), self.source.currentData(), self.name.text())
            self.name.clear()
            self.docker.toast(f"Sent “{job['name']}” to {PROVIDER_LABELS.get(job['providerId'])}.")

        self.docker.guard(run)

    def try_sample(self) -> None:
        def run():
            item = _plugin().add_sample()
            _plugin().place_model(item["id"])

        self.docker.guard(run)

    def detach(self) -> None:
        ctx = self.ctx
        if ctx.get("is3DLayer") and QMessageBox.question(self, "3D Layers", f"Remove the 3D data from “{ctx.get('layerName')}”? It stays in the image as an ordinary layer, but it can no longer be re-posed.") == E(QMessageBox, "StandardButton", "Yes"):
            self.docker.guard(lambda: krita_doc.detach(ctx["docKey"], ctx["layerId"]))
            self.docker.on_context()


# ---------------------------------------------------------------- Library


class ModelList(QListWidget):
    """The library grid; accepts 3D files dropped from the file manager."""

    def __init__(self, on_drop: Callable[[List[str]], None]):
        super().__init__()
        self.on_drop = on_drop
        self.setAcceptDrops(True)

    def _paths(self, event) -> List[str]:
        md = event.mimeData()
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile()] if md.hasUrls() else []

    def dragEnterEvent(self, event):  # noqa: N802 - Qt API
        if self._paths(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):  # noqa: N802
        if self._paths(event):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):  # noqa: N802
        paths = self._paths(event)
        if paths:
            event.acceptProposedAction()
            self.on_drop(paths)
        else:
            super().dropEvent(event)


class LibraryTab(QWidget):
    ALL = "\x00all"

    def __init__(self, docker: "ThreeDLayersDocker"):
        super().__init__()
        self.docker = docker
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search all models")
        self.search.textChanged.connect(lambda _t: self.refresh())
        bar.addWidget(self.search, 1)
        imp = QToolButton()
        imp.setText("Import")
        imp.setPopupMode(E(QToolButton, "ToolButtonPopupMode", "InstantPopup"))
        menu = QMenu(imp)
        menu.addAction("Import files…", self.import_files)
        menu.addAction("Import a folder…", self.import_folder)
        menu.addSeparator()
        menu.addAction("Add the sample model", lambda: docker.guard(_plugin().add_sample))
        imp.setMenu(menu)
        bar.addWidget(imp)
        more = QToolButton()
        more.setText("⋯")
        more.setPopupMode(E(QToolButton, "ToolButtonPopupMode", "InstantPopup"))
        mm = QMenu(more)
        mm.addAction("New folder…", self.new_folder)
        mm.addAction("Rename this folder…", self.rename_folder)
        mm.addAction("Delete this folder", self.delete_folder)
        mm.addSeparator()
        mm.addAction("Make missing previews", lambda: docker.guard(_plugin().make_previews))
        mm.addAction("Show the library folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(_plugin().library.dir))))
        more.setMenu(mm)
        bar.addWidget(more)
        outer.addLayout(bar)
        self.folder = QComboBox()
        self.folder.currentIndexChanged.connect(lambda _i: self.refresh(keep_folders=True))
        outer.addWidget(self.folder)
        self.list = ModelList(self.dropped)
        self.list.setViewMode(E(QListWidget, "ViewMode", "IconMode"))
        self.list.setResizeMode(E(QListWidget, "ResizeMode", "Adjust"))
        self.list.setMovement(E(QListWidget, "Movement", "Static"))
        self.list.setIconSize(QSize(88, 88))
        self.list.setGridSize(QSize(104, 124))
        self.list.setWordWrap(True)
        self.list.setSelectionMode(E(QAbstractItemView, "SelectionMode", "ExtendedSelection"))
        self.list.setContextMenuPolicy(E(Qt, "ContextMenuPolicy", "CustomContextMenu"))
        self.list.customContextMenuRequested.connect(self.menu)
        self.list.itemDoubleClicked.connect(lambda it: docker.guard(lambda: _plugin().place_model(it.data(USER_ROLE))))
        outer.addWidget(self.list, 1)
        self.footer = _label(small=True)
        outer.addWidget(self.footer)
        self._icons: Dict[str, Any] = {}

    def current_folder(self) -> Optional[str]:
        data = self.folder.currentData()
        return None if data in (None, self.ALL) else data

    def refresh(self, keep_folders: bool = False) -> None:
        lib = _plugin().library
        if not keep_folders:
            current = self.folder.currentData()
            self.folder.blockSignals(True)
            self.folder.clear()
            self.folder.addItem("All models", self.ALL)
            self.folder.addItem("Library (top level)", "")
            for f in lib.folders():
                self.folder.addItem("    " * f.count("/") + "📁 " + folder_name(f), f)
            idx = self.folder.findData(current) if current is not None else 0
            self.folder.setCurrentIndex(max(0, idx))
            self.folder.blockSignals(False)
        folder = self.current_folder()
        q = self.search.text().strip().lower()
        items = lib.list()
        shown = [i for i in items if (folder is None or (folder == "" and not i.get("folder")) or (folder and is_in_folder(i.get("folder") or "", folder))) and (not q or q in i["name"].lower())]
        selected = {it.data(USER_ROLE) for it in self.list.selectedItems()}
        self.list.clear()
        for item in shown:
            w = QListWidgetItem(self.icon_for(item), ("★ " if item.get("favorite") else "") + item["name"])
            w.setData(USER_ROLE, item["id"])
            w.setToolTip(f"{item['name']}\n{PROVIDER_LABELS.get(item.get('origin'), item.get('origin'))} · {round((item.get('sizeBytes') or 0) / 1e6, 1)} MB" + (f"\nFolder: {item['folder']}" if item.get("folder") else "") + "\nDouble-click to place it in the image.")
            self.list.addItem(w)
            if item["id"] in selected:
                w.setSelected(True)
        self.footer.setText(f"{len(shown)} of {len(items)} models. Shared with Geekatplay 3D Layers for Photoshop. Drop 3D files here to import them ({SUPPORTED_FORMATS_TEXT}).")

    def icon_for(self, item: Dict[str, Any]) -> QIcon:
        thumb = item.get("thumbFile")
        key = f"{item['id']}:{thumb}"
        if key not in self._icons:
            pm = QPixmap(str(_plugin().library.dir / thumb)) if thumb else QPixmap()
            self._icons[key] = QIcon(pm.scaled(88, 88, KEEP, SMOOTH) if not pm.isNull() else _placeholder(88))
        return self._icons[key]

    def selected_ids(self) -> List[str]:
        return [it.data(USER_ROLE) for it in self.list.selectedItems()]

    def menu(self, pos) -> None:
        it = self.list.itemAt(pos)
        if it is None:
            return
        if not it.isSelected():
            self.list.clearSelection()
            it.setSelected(True)
        ids = self.selected_ids()
        lib = _plugin().library
        first = lib.get(ids[0])
        m = QMenu(self)
        d = self.docker
        if len(ids) == 1:
            m.addAction("Place in the image…", lambda: d.guard(lambda: _plugin().place_model(ids[0])))
            m.addAction("Rename…", lambda: self.rename(ids[0]))
            m.addAction("Remove star" if first.get("favorite") else "Star (keep at the top)", lambda: d.guard(lambda: lib.update(ids[0], favorite=not first.get("favorite"))))
            m.addAction("Show the file", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(lib.path(first["modelFile"]).parent))))
        move = m.addMenu("Move to folder")
        move.addAction("Library (top level)", lambda: d.guard(lambda: lib.move(ids, "")))
        for f in lib.folders():
            move.addAction("    " * f.count("/") + folder_name(f), lambda f=f: d.guard(lambda: lib.move(ids, f)))
        move.addSeparator()
        move.addAction("New folder…", lambda: self.new_folder(move_ids=ids))
        m.addSeparator()
        m.addAction(f"Remove {len(ids)} models from the library…" if len(ids) > 1 else "Remove from the library…", lambda: self.remove(ids))
        exec_(m, self.list.mapToGlobal(pos))

    def rename(self, item_id: str) -> None:
        item = _plugin().library.get(item_id)
        name, ok = QInputDialog.getText(self, "Rename model", "Name:", text=item["name"])
        if ok and name.strip():
            self.docker.guard(lambda: _plugin().library.update(item_id, name=name))

    def remove(self, ids: List[str]) -> None:
        what = f"these {len(ids)} models" if len(ids) > 1 else f"“{_plugin().library.get(ids[0])['name']}”"
        if QMessageBox.question(self, "Remove from library", f"Remove {what} from the library? Their files are deleted from this computer. Layers already placed in images are not affected.") == E(QMessageBox, "StandardButton", "Yes"):
            self.docker.guard(lambda: _plugin().library.remove_many(ids))

    def new_folder(self, move_ids: Optional[List[str]] = None) -> None:
        parent = self.current_folder() or ""
        name, ok = QInputDialog.getText(self, "New folder", f"Folder name (inside {parent or 'the top level'}):")
        if ok and name.strip():
            def run():
                lib = _plugin().library
                lib.create_folder(parent, name)
                if move_ids:
                    from ..core.library import join_folder

                    lib.move(move_ids, join_folder(parent, name))

            self.docker.guard(run)

    def rename_folder(self) -> None:
        folder = self.current_folder()
        if not folder:
            QMessageBox.information(self, "3D Layers", "Choose a folder in the list above first.")
            return
        name, ok = QInputDialog.getText(self, "Rename folder", "New name:", text=folder_name(folder))
        if ok and name.strip():
            self.docker.guard(lambda: _plugin().library.rename_folder(folder, name))

    def delete_folder(self) -> None:
        folder = self.current_folder()
        if not folder:
            QMessageBox.information(self, "3D Layers", "Choose a folder in the list above first.")
            return
        if QMessageBox.question(self, "Delete folder", f"Delete the folder “{folder}”? Its models and subfolders move up one level; no model is deleted.") == E(QMessageBox, "StandardButton", "Yes"):
            self.docker.guard(lambda: _plugin().library.delete_folder(folder))

    def import_files(self) -> None:
        patterns = " ".join(f"*.{e}" for e in MODEL_EXTENSIONS)
        paths, _ = QFileDialog.getOpenFileNames(self, "Import 3D files", "", f"3D models ({patterns});;All files (*)")
        if paths:
            self.docker.guard(lambda: _plugin().import_files(paths, self.current_folder() or ""))

    def import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Import a folder of 3D files")
        if folder:
            self.docker.guard(lambda: _plugin().import_files([folder], self.current_folder() or "", folder=True))

    def dropped(self, paths: List[str]) -> None:
        folders = [p for p in paths if os.path.isdir(p)]
        files = [p for p in paths if os.path.isfile(p) and is_model_file(p)]
        into = self.current_folder() or ""
        for f in folders:
            self.docker.guard(lambda f=f: _plugin().import_files([f], into, folder=True))
        if files:
            self.docker.guard(lambda: _plugin().import_files(files, into))
        if not folders and not files:
            self.docker.toast(f"Those are not 3D files. Supported: {SUPPORTED_FORMATS_TEXT}.", "error")


# ---------------------------------------------------------------- Settings


class KeyField(QWidget):
    """A secret: typed once, saved to credentials.json, shown only as a short preview."""

    def __init__(self, docker: "ThreeDLayersDocker", key: str, placeholder: str):
        super().__init__()
        self.docker = docker
        self.key = key
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setEchoMode(E(QLineEdit, "EchoMode", "Password"))
        self.edit.setMinimumWidth(40)
        self.edit.setPlaceholderText(placeholder)
        self.edit.returnPressed.connect(self.save)
        row.addWidget(self.edit, 1)
        row.addWidget(_button("Save", self.save))
        self.clear = QToolButton()
        self.clear.setText("✕")
        self.clear.setToolTip("Remove the saved key from this computer")
        self.clear.clicked.connect(lambda _=False: self.remove())
        row.addWidget(self.clear)

    def refresh(self) -> None:
        value = _plugin().secrets.get(self.key)
        self.edit.clear()
        self.edit.setPlaceholderText(f"Saved: {preview(value)}" if value else "Paste your key here")
        self.clear.setEnabled(bool(value))

    def save(self) -> None:
        if self.edit.text().strip():
            self.docker.guard(lambda: _plugin().secrets.set(self.key, self.edit.text()))
            self.docker.on_settings()

    def remove(self) -> None:
        self.docker.guard(lambda: _plugin().secrets.set(self.key, ""))
        self.docker.on_settings()


class SettingsTab(QScrollArea):
    def __init__(self, docker: "ThreeDLayersDocker"):
        super().__init__()
        self.docker = docker
        self.setWidgetResizable(True)
        host = QWidget()
        self.col = QVBoxLayout(host)
        self.col.setContentsMargins(4, 4, 4, 4)
        self.setWidget(host)
        self.fields: List[Callable[[], None]] = []
        self.keys: List[KeyField] = []

        g, f = self._group("3D service")
        self.default = self._combo(f, "Default service", [(pid, PROVIDER_LABELS[pid]) for pid in PROVIDER_IDS], lambda s: s["defaultProvider"], lambda v: {"defaultProvider": v})

        g, f = self._group("Meshy")
        self._key(f, "API key", "meshy.apiKey", "msy_…", "meshy")
        self._combo(f, "Model", [(m, m) for m in MESHY_AI_MODELS], lambda s: s["meshy"]["aiModel"], lambda v: {"meshy": {"aiModel": v}}, editable=True)
        self._check(f, "Texture", lambda s: s["meshy"]["shouldTexture"], lambda v: {"meshy": {"shouldTexture": v}})
        self._check(f, "PBR materials", lambda s: s["meshy"]["enablePbr"], lambda v: {"meshy": {"enablePbr": v}})
        self._check(f, "Content moderation", lambda s: s["meshy"]["moderation"], lambda v: {"meshy": {"moderation": v}})
        self._test(f, "meshy")

        g, f = self._group("Tripo")
        self._key(f, "API key", "tripo.apiKey", "tsk_…", "tripo")
        self._combo(f, "Model", [(m, m) for m in TRIPO_MODEL_VERSIONS], lambda s: s["tripo"]["model"], lambda v: {"tripo": {"model": v}}, editable=True)
        self._check(f, "Texture", lambda s: s["tripo"]["texture"], lambda v: {"tripo": {"texture": v}})
        self._check(f, "PBR materials", lambda s: s["tripo"]["pbr"], lambda v: {"tripo": {"pbr": v}})
        self._test(f, "tripo")

        g, f = self._group("Hitem3D")
        self._key(f, "Access key", "hitem3d.accessKey", "Access key", "hitem3d")
        self._key(f, "Secret key", "hitem3d.secretKey", "Secret key", None)
        self._combo(f, "Model", [(m, m) for m in HITEM3D_MODELS], lambda s: s["hitem3d"]["model"], lambda v: {"hitem3d": {"model": v}})
        self.h_res = self._combo(f, "Resolution", [], lambda s: s["hitem3d"]["resolution"], lambda v: {"hitem3d": {"resolution": v}}, options=lambda s: [(r, r) for r in HITEM3D_RESOLUTIONS[s["hitem3d"]["model"]]])
        self._spin(f, "Face count", 0, 5_000_000, 50_000, lambda s: s["hitem3d"]["face"], lambda v: {"hitem3d": {"face": v}}, "0 = Hitem3D's default")
        self._check(f, "PBR materials", lambda s: s["hitem3d"]["pbr"], lambda v: {"hitem3d": {"pbr": v}})
        self._test(f, "hitem3d")

        g, f = self._group("ComfyUI (on your computer or network)")
        self._text(f, "Address", lambda s: s["comfyui"]["url"], lambda v: {"comfyui": {"url": v}}, "http://127.0.0.1:8188")
        self.workflow_label = _label(small=True)
        f.addRow("Workflow", self.workflow_label)
        wrow = QHBoxLayout()
        wrow.addWidget(_button("Use TRELLIS.2 (built in)", lambda: self._set({"comfyui": {"workflow": "trellis2"}})))
        wrow.addWidget(_button("Load a workflow…", self.load_workflow, "A workflow saved with Workflow › Export (API) in ComfyUI"))
        f.addRow("", self._wrap(wrow))
        self._spin(f, "Texture size", 512, 8192, 512, lambda s: s["comfyui"]["textureSize"], lambda v: {"comfyui": {"textureSize": v}})
        self._spin(f, "Face count", 10_000, 5_000_000, 50_000, lambda s: s["comfyui"]["faceCount"], lambda v: {"comfyui": {"faceCount": v}})
        self._test(f, "comfyui")

        g, f = self._group("Generation")
        self._spin(f, "Max image size", 256, 4096, 256, lambda s: s["send"]["maxEdge"], lambda v: {"send": {"maxEdge": v}}, "Longest side of the image sent; larger layers are scaled down")

        g, f = self._group("3D editor")
        self._combo(f, "Export size", [(str(n), f"{n} px") for n in (1024, 2048, 3072, 4096)], lambda s: str(s["editor"]["defaultResolution"]), lambda v: {"editor": {"defaultResolution": int(v)}})
        self._check(f, "Remember lighting for new models", lambda s: s["editor"]["rememberLighting"], lambda v: {"editor": {"rememberLighting": v}})
        self._combo(f, "Open the editor in", [("app", "Its own window (Edge or Chrome)"), ("browser", "A browser tab")], lambda s: s["editor"]["window"], lambda v: {"editor": {"window": v}})

        g, f = self._group("Files")
        frow = QHBoxLayout()
        frow.addWidget(_button("Show data folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(_plugin().root)))))
        frow.addWidget(_button("Open log", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(_plugin().log.path)))))
        f.addRow(self._wrap(frow))
        from .. import __version__

        f.addRow(_label(f"Geekatplay 3D Layers for Krita {__version__} · Geekatplay Studio · MIT license.<br>Keys are kept in credentials.json in the data folder (shared with the Photoshop plugin) and sent only to their own service.", small=True))
        self.col.addStretch(1)

    # ---- building blocks

    def _wrap(self, layout) -> QWidget:
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    def _group(self, title: str):
        g = QGroupBox(title)
        f = QFormLayout(g)
        # Dockers are narrow: labels go above their field when there is no room beside it.
        f.setRowWrapPolicy(E(QFormLayout, "RowWrapPolicy", "WrapLongRows"))
        f.setFieldGrowthPolicy(E(QFormLayout, "FieldGrowthPolicy", "AllNonFixedFieldsGrow"))
        self.col.addWidget(g)
        return g, f

    def _set(self, patch: Dict[str, Any]) -> None:
        self.docker.guard(lambda: _plugin().update_settings(patch))

    def _combo(self, form, label, items, get, put, editable=False, options=None):
        box = QComboBox()
        box.setEditable(editable)

        def refresh():
            s = _plugin().settings
            box.blockSignals(True)
            box.clear()
            for value, text in options(s) if options else items:
                box.addItem(text, value)
            current = get(s)
            idx = box.findData(current)
            if idx < 0 and editable:
                box.addItem(current, current)
                idx = box.count() - 1
            box.setCurrentIndex(max(0, idx))
            box.blockSignals(False)

        def changed(*_):
            value = box.currentData() if box.currentData() is not None and box.currentText() == box.itemText(box.currentIndex()) else box.currentText().strip()
            if value and value != get(_plugin().settings):
                self._set(put(value))

        box.currentIndexChanged.connect(changed)
        if editable:
            box.lineEdit().editingFinished.connect(changed)
        form.addRow(label, box)
        self.fields.append(refresh)
        return box

    def _check(self, form, label, get, put):
        box = QCheckBox(label)
        box.toggled.connect(lambda v: self._set(put(bool(v))) if bool(v) != get(_plugin().settings) else None)
        form.addRow("", box)
        self.fields.append(lambda: (box.blockSignals(True), box.setChecked(bool(get(_plugin().settings))), box.blockSignals(False)))

    def _spin(self, form, label, lo, hi, step, get, put, tip=""):
        box = QSpinBox()
        box.setRange(lo, hi)
        box.setSingleStep(step)
        box.setToolTip(tip)
        box.editingFinished.connect(lambda: self._set(put(box.value())) if box.value() != get(_plugin().settings) else None)
        form.addRow(label, box)
        self.fields.append(lambda: (box.blockSignals(True), box.setValue(int(get(_plugin().settings))), box.blockSignals(False)))

    def _text(self, form, label, get, put, placeholder=""):
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.editingFinished.connect(lambda: self._set(put(edit.text())) if edit.text().strip() and edit.text().strip() != get(_plugin().settings) else None)
        form.addRow(label, edit)
        self.fields.append(lambda: edit.setText(get(_plugin().settings)))

    def _key(self, form, label, key, placeholder, link_provider):
        field = KeyField(self.docker, key, placeholder)
        form.addRow(label, field)
        self.keys.append(field)
        if link_provider and link_provider in KEY_LINKS:
            link = _label(f'<a href="{KEY_LINKS[link_provider]}">Get a key</a>', small=True)
            link.setOpenExternalLinks(True)
            form.addRow("", link)

    def _test(self, form, provider_id):
        result = _label(small=True)
        btn = QPushButton("Test connection")

        def run():
            btn.setEnabled(False)
            result.setStyleSheet("")
            result.setText("Testing…")

            def done(ok: bool, message: str):
                btn.setEnabled(True)
                result.setStyleSheet("color: #3fb950;" if ok else "color: #e5534b;")
                result.setText(message)

            _plugin().test_provider(provider_id, done)

        btn.clicked.connect(lambda _=False: run())
        form.addRow(btn, result)

    def load_workflow(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "ComfyUI workflow (API format)", "", "Workflow JSON (*.json)")
        if not path:
            return

        def run():
            import json

            from ..core.providers.comfy_workflows import is_api_workflow

            data = json.loads(open(path, encoding="utf-8").read())
            if not is_api_workflow(data):
                raise ValueError("This is not an API-format workflow. In ComfyUI use Workflow › Export (API), then load that file.")
            _plugin().update_settings({"comfyui": {"workflow": "custom", "customWorkflow": data, "customWorkflowName": os.path.basename(path)}})

        self.docker.guard(run)

    def refresh(self) -> None:
        for fn in self.fields:
            fn()
        for k in self.keys:
            k.refresh()
        c = _plugin().settings["comfyui"]
        self.workflow_label.setText("TRELLIS.2 (built in)" if c["workflow"] == "trellis2" else f"Custom: {c['customWorkflowName'] or 'workflow'}")


# ---------------------------------------------------------------- docker


class ThreeDLayersDocker(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("3D Layers")
        self.guard = Guard(self)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(2, 2, 2, 2)
        self.banner = _label()
        self.banner.setVisible(False)
        layout.addWidget(self.banner)
        self.editor_box = QFrame()
        self.editor_box.setFrameShape(E(QFrame, "Shape", "StyledPanel"))
        eb = QHBoxLayout(self.editor_box)
        self.editor_text = _label(small=True)
        eb.addWidget(self.editor_text, 1)
        eb.addWidget(_button("Stop", lambda: self.guard(_plugin().cancel_editor), "Close the 3D editor session without changing the image"))
        self.editor_box.setVisible(False)
        layout.addWidget(self.editor_box)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.setWidget(root)
        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.timeout.connect(lambda: self.banner.setVisible(False))
        self._last_ctx: Dict[str, Any] = {}
        try:
            plugin = _plugin()
        except Exception as err:  # noqa: BLE001 - show why instead of an empty docker
            layout.addWidget(_label(f"Geekatplay 3D Layers could not start: {err}"))
            return
        self.create = CreateTab(self)
        self.library = LibraryTab(self)
        self.settings = SettingsTab(self)
        self.tabs.addTab(self.create, "Create")
        self.tabs.addTab(self.library, "Library")
        self.tabs.addTab(self.settings, "Settings")
        self.tabs.setCurrentIndex({"create": 0, "library": 1, "settings": 2}.get(plugin.settings["ui"]["tab"], 0))
        self.tabs.currentChanged.connect(lambda i: plugin.update_settings({"ui": {"tab": ("create", "library", "settings")[i]}}, quiet=True))
        plugin.attach(self)
        self.destroyed.connect(lambda *_: plugin.detach(self))
        self.on_settings()
        self.on_jobs()
        self.on_library()
        self.on_context()
        self._ctx_timer = QTimer(self)
        self._ctx_timer.timeout.connect(self.on_context)
        self._ctx_timer.start(700)

    # Krita calls this when the active view changes.
    def canvasChanged(self, canvas):  # noqa: N802 - Krita API
        self.on_context()

    def on_context(self, *_: Any) -> None:
        if not hasattr(self, "create"):
            return
        try:
            ctx = krita_doc.context()
        except Exception:  # noqa: BLE001 - Krita can be mid-change (closing a document)
            return
        if ctx != self._last_ctx:
            self._last_ctx = ctx
            self.create.refresh_context(ctx)
            try:
                self.create.refresh_preview()
            except Exception:  # noqa: BLE001
                pass

    def on_jobs(self) -> None:
        self.create.refresh_jobs()

    def on_library(self) -> None:
        self.library.refresh()

    def on_settings(self) -> None:
        self.create.refresh_settings()
        self.settings.refresh()

    def on_editor(self, state: Dict[str, Any]) -> None:
        if state.get("open"):
            self.editor_text.setText(f"<b>3D editor open</b> · {state.get('name')}<br>Pose and light it in the editor window, then click {'Update Layer' if state.get('mode') == 'update' else 'Place in Document'}.")
            self.editor_box.setVisible(True)
        else:
            self.editor_box.setVisible(False)
            if state.get("message"):
                self.toast(state["message"])

    def on_toast(self, message: str, kind: str = "info") -> None:
        self.toast(message, kind)

    def toast(self, message: str, kind: str = "info") -> None:
        self.banner.setText(message)
        self.banner.setStyleSheet("padding: 6px; border-radius: 4px; background: %s; color: white;" % ("#8e1519" if kind == "error" else "#1f6feb"))
        self.banner.setVisible(True)
        self._banner_timer.start(9000 if kind == "error" else 6000)
