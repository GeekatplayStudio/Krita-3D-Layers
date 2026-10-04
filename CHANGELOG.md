# Changelog

All notable changes. The format follows [Keep a Changelog](https://keepachangelog.com/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-04

First release: Geekatplay 3D Layers for Photoshop, brought to Krita.

### Added
- **3D Layers docker** with Create, Library and Settings tabs; Krita 5.2+ (PyQt5) and Krita 6 (PyQt6).
- **Generate a 3D model** from the active layer or the selection with Meshy, Tripo, Hitem3D or ComfyUI (TRELLIS.2 built in, or your own workflow). Jobs run in the background and continue after a restart.
- **The 3D pose & light editor** of the Photoshop plugin, in a browser app window: light presets, sun, environments, shadows, camera, export up to 8192 px, and **Show document** (the layers below behind the model, the layers above in front).
- **3D layers:** the render becomes a paint layer above the selected layer, exactly where the editor showed it. **Edit pose & light** re-poses it in place, also after moving the layer or reopening the `.kra` (the state is a document annotation). Works in 8-bit, 16-bit and float RGB images.
- **Library** shared with the Photoshop plugin (same folder, same format, same keys): previews, folders, search, stars, import of GLB, glTF, FBX, OBJ, DAE, USDZ, 3DS, STL, PLY, 3MF, AMF, VRML and VOX (also by dropping files), previews rendered for models without one.
- **Sample model** to try everything without an account.
- **Installers** for Windows, macOS and Linux in the release ZIP, which also works with Krita's *Import Python Plugin from File*.
- Tests: 89 Python tests (ported from the Photoshop plugin) and an integration test that runs inside Krita.
