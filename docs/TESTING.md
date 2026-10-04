# Testing

## 1. Python tests: `npm test` (pytest, under a second)

No Krita needed. Every service client is tested against scripted HTTP answers (`tests/helpers.ScriptedTransport`), ported from the Photoshop plugin's TypeScript tests.

| File | Covers |
|---|---|
| `test_core_base.py` | HTTP errors (service message, code, request id, Retry-After), multipart, log redaction, settings validation |
| `test_provider_meshy.py`, `test_provider_tripo.py`, `test_provider_hitem3d.py`, `test_provider_comfyui.py`, `test_comfy_workflows.py` | Request bodies per model, auth, upload → task flows, Hitem3D token cache and expiry retry, status mapping, progress, balances, error messages, resolve and cancel, the TRELLIS.2 graph and custom workflows |
| `test_library_jobs.py` | The library in the Photoshop plugin's format (reading its index, picking up its changes), folders, the job queue (lifecycle, retries, rate limits, resume after restart, cancel, retry), shared credentials |
| `test_import_geometry_server.py` | Import batches (GLB stored, other formats handed to the browser, folders), placement geometry, the layer split, and the local server (token check, path escapes, foreign Host header, calls) |

## 2. Inside Krita: `python tests/krita/run.py`

Runs `tests/krita/g3d_integration.py` inside Krita with `kritarunner` (no window opens) against real documents: reading a layer and a selection, placing a render above the active layer, "Show document" (layers below and above, visibility restored), updating with another resolution, following a moved layer, saving and reopening the `.kra`, and 16-bit and float images. 28 checks.

## 3. The whole flow by hand, with the editor driven automatically

1. `npm run install:krita`.
2. Start Krita with `G3D_TEST_URL_FILE` set: the plugin then writes each browser page's address to that file instead of opening a browser. Add `GEEKATPLAY_3D_DATA` to use a separate data folder.
   ```powershell
   $env:G3D_TEST_URL_FILE = "$env:TEMP\g3d-urls.txt"; $env:GEEKATPLAY_3D_DATA = "$env:TEMP\g3d-demo"; & "C:\Program Files\Krita (x64)\bin\krita.exe"
   ```
3. In Krita, start something (Try the sample model, Pose & place, Edit pose & light, an import), then:
   ```bash
   MATCH=1 PRESET="Golden Hour" node tests/e2e/drive-editor.mjs "$TEMP/g3d-urls.txt" shot.png -30
   ```
   It opens the newest page in Chromium, waits for the model, applies the options, saves a screenshot and clicks **Place in Document** / **Update Layer** (or `--cancel`). For a task page it waits for the result.

## 4. Manual checklist

| # | Step | Expected |
|---|---|---|
| 1 | Install with **Install on Windows.cmd** (Krita closed), open Krita | **Settings › Dockers › 3D Layers** exists; the docker shows Create / Library / Settings |
| 2 | Library tab | The models of the shared library, with previews |
| 3 | Create › **Try the sample model** | The editor opens in an app window with the image around the model; **Place in Document** adds `Sample rocket (3D)` above the selected layer, where it was shown |
| 4 | Select the 3D layer › **Edit pose & light**, turn, **Update Layer** | Same place, new pose |
| 5 | Move the 3D layer with the Move tool, update again | The update stays where the layer was moved |
| 6 | Save, close, reopen the `.kra`, select the layer | The 3D banner is back; re-posing works |
| 7 | Settings › each service › key › **Test connection** | "Connected …" with the balance |
| 8 | Select a layer › **Generate 3D model** | A job with progress; **Ready** about a minute (services) or five (ComfyUI) later; the model is in the Library |
| 9 | Library › Import files… FBX and OBJ (or drop them on the list) | A small window converts them; both appear with previews |
| 10 | Close the editor window without OK | The docker's "3D editor open" goes away within a minute; nothing changed |

### Verified for 0.1.0 (2026-10-04, Krita 5.3.4, Windows 11)
- Steps 1–4, 9, and 7 for Tripo and Hitem3D (live: Tripo balance; Hitem3D sign-in and balance) by hand with the editor driven as in section 3.
- Step 8 up to the service: a job to a ComfyUI that was not running failed with "cannot reach 127.0.0.1:8188" and offered Retry. Generating with real keys costs credits and was left to the account owner.
- The library shared with the Photoshop plugin: 140 models made in Photoshop showed in Krita with their previews; models imported in Krita were added to the same index.
- Steps 5 and 6 and other colour depths by the integration test (section 2).
