"""
Menu actions under Tools › Scripts. "Edit 3D Layer (Pose & Light)" can get a keyboard
shortcut in Settings › Configure Krita › Keyboard Shortcuts: Krita has no way for a plugin
to take over double-clicking a layer, so this is the quickest way back into the editor.
"""
from __future__ import annotations

from krita import Extension, Krita  # type: ignore

from .qt import QMessageBox


class ThreeDLayersExtension(Extension):
    def __init__(self, parent):
        super().__init__(parent)

    def setup(self):
        Krita.instance().notifier().applicationClosing.connect(self._closing)

    def createActions(self, window):  # noqa: N802 - Krita API
        edit = window.createAction("geekatplay_3d_edit_layer", "Edit 3D Layer (Pose && Light)…", "tools/scripts")
        edit.triggered.connect(self._edit)

    def _edit(self):
        from . import krita_doc
        from .app import Plugin

        try:
            Plugin.get().edit_active_layer()
        except krita_doc.DocError as err:
            QMessageBox.information(Krita.instance().activeWindow().qwindow(), "3D Layers", str(err))

    def _closing(self):
        from .app import Plugin

        if Plugin._instance is not None:
            Plugin._instance.shutdown()
