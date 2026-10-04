"""
Geekatplay 3D Layers for Krita: turn a layer into a 3D model with Meshy, Tripo, Hitem3D or
your own ComfyUI, pose and light it in the 3D editor, and place it as a layer you can
re-pose any time. By Geekatplay Studio (https://www.geekatplay.com), MIT license.

Krita loads this package from its pykrita folder (see the .desktop file next to it).
Outside Krita (the tests) only the core package is used, so nothing here may fail there.
"""
import os

__version__ = "0.1.0"

try:
    from krita import DockWidgetFactory, DockWidgetFactoryBase, Krita  # type: ignore
except ImportError:  # not running inside Krita
    Krita = None

# G3D_NO_REGISTER: scripts run with kritarunner (tests/krita) import the modules without the UI.
if Krita is not None and not os.environ.get("G3D_NO_REGISTER"):
    from .ui.docker import ThreeDLayersDocker
    from .ui.extension import ThreeDLayersExtension

    _app = Krita.instance()
    _app.addExtension(ThreeDLayersExtension(_app))
    _app.addDockWidgetFactory(DockWidgetFactory("geekatplay_3d_layers", DockWidgetFactoryBase.DockRight, ThreeDLayersDocker))
