# Development

## Setup

- **Krita 5.3** (or 5.2/6) to run the plugin; `kritarunner` comes with it.
- **Python 3.8+** with `pytest` for the tests (`pip install pytest`).
- **Node.js 20.19+** for the web editor (`npm install`).
- Optional: the [Photoshop plugin](https://github.com/GeekatplayStudio/Photoshop-3D) checked out next to this folder (`../Photoshop-3D-plugin`) to update the shared web code.

## Commands

| Command | What it does |
|---|---|
| `npm run build` | Builds the editor and the task page into `plugin/geekatplay_3d_layers/web` |
| `npm run dev` | Serves the editor at http://localhost:5318/editor.html against the mock host (same as the Photoshop plugin's dev mode) |
| `npm test` | Python tests (`python -m pytest -q`) |
| `npm run test:krita` | The document operations inside real Krita, headless (`python tests/krita/run.py`) |
| `npm run typecheck` | TypeScript check of the web code |
| `npm run install:krita` | Builds and copies the plugin into Krita's `pykrita` folder and enables it (close Krita first) |
| `node scripts/install-dev.mjs --remove` | Removes it again |
| `npm run dist` | Builds and packs `dist/Geekatplay-3D-Layers-Krita-<version>.zip` (+ `.sha256`) |
| `npm run sync-web [path]` | Copies the editor, converter and shared code from the Photoshop plugin |

## Working on the plugin

1. `npm run install:krita`, then start Krita. Krita loads Python plugins at start, so restart it after changing Python code.
2. The log is in the data folder: `logs/krita3d.log`. Python errors raised in Krita also show in **Settings › Dockers › Log Viewer**.
3. To try things without touching your real library, start Krita with a separate data folder:
   ```bash
   GEEKATPLAY_3D_DATA=/tmp/g3d-demo krita
   ```

### Python rules
- Everything in `core/` runs without Krita or Qt (the tests import it under plain CPython). Krita and Qt code goes in `ui/`.
- Qt comes from `ui/qt.py` only, and enums are written scoped (`E(Qt, "AlignmentFlag", "AlignTop")`), so the code runs on PyQt5 (Krita 5) and PyQt6 (Krita 6).
- Krita API calls happen on the UI thread. Network calls happen on the job workers; never block the UI thread on the network.
- Code must run on Python 3.8+: `from __future__ import annotations`, no `match`.
- Never pass keys to the logger; `redact` is only a safety net.

### Web code
`web/src` is a copy of the Photoshop plugin's web code. Change shared files there (in the Photoshop project) and run `npm run sync-web`. The Krita-owned files, which the sync never overwrites, are listed in `scripts/sync-web.mjs`: the HTTP transport (`bridge/httpTransport.ts`, `bridge/client.ts`), the editor's page entry (`editor/main.tsx`) and the task page (`tasks.html`, `tasks/main.tsx`).

## Releasing

1. Update the version in `plugin/geekatplay_3d_layers/__init__.py` and `package.json` (the build checks they match) and describe the changes in `CHANGELOG.md`.
2. `npm run verify` (typecheck, tests, build, package) and `python tests/krita/run.py`.
3. Attach `dist/Geekatplay-3D-Layers-Krita-<version>.zip` and its `.sha256` to a GitHub release.

## Demo assets

`tests/fixtures/public/samples` holds the demo models and the desk scene used for the screenshots; they come from the Photoshop plugin (`scripts/make-demo-models.py`, `scripts/make-demo-scene.py` there).
