# Geekatplay 3D Layers for Krita: user guide

Version 0.1.1. Turn a Krita layer into a 3D model, pose and light it in a 3D editor, and place it in your image as a layer you can change any time.

- [1. What you need](#1-what-you-need)
- [2. Install the plugin](#2-install-the-plugin)
- [3. Open the 3D Layers docker](#3-open-the-3d-layers-docker)
- [4. Try it with the sample model](#4-try-it-with-the-sample-model)
- [5. Set up a 3D service](#5-set-up-a-3d-service)
- [6. Make a 3D model from a layer](#6-make-a-3d-model-from-a-layer)
- [7. The 3D editor](#7-the-3d-editor)
- [8. Change a 3D layer later](#8-change-a-3d-layer-later)
- [9. The library](#9-the-library)
- [10. Settings](#10-settings)
- [11. Update or uninstall](#11-update-or-uninstall)
- [12. Files the plugin uses](#12-files-the-plugin-uses)
- [13. Troubleshooting](#13-troubleshooting)

---

## 1. What you need

- **Krita 5.2 or newer**, on Windows 10/11, macOS or Linux. Free from [krita.org](https://krita.org). (Tested with Krita 5.3.4; Krita 6 is supported too.)
- **Microsoft Edge or Google Chrome.** The 3D editor opens in its own window of one of these browsers. Windows already has Edge. Brave and Chromium work too; without any of them, the editor opens in your default browser.
- **To make your own models:** an account with Meshy, Tripo or Hitem3D, or ComfyUI on your computer (see [section 5](#5-set-up-a-3d-service)). Not needed to try the plugin with the sample model.

---

## 2. Install the plugin

### Step 1: Download

Download **[Geekatplay-3D-Layers-Krita.zip](https://github.com/GeekatplayStudio/Krita-3D-Layers/releases/latest/download/Geekatplay-3D-Layers-Krita.zip)** (the newest version). All versions are on the [Releases page](https://github.com/GeekatplayStudio/Krita-3D-Layers/releases).

### Step 2: Close Krita

Close Krita completely before installing (save your work first). Krita saves its settings when it closes, so an install done while it is open would be undone.

### Step 3: Run the installer

Pick your computer:

#### Windows
1. Open your **Downloads** folder, right-click **Geekatplay-3D-Layers-Krita.zip** and choose **Extract All…**, then **Extract**.
2. In the folder that opens, double-click **Install on Windows.cmd**.
3. If Windows warns about a file from the internet, choose **Run** (or **More info** › **Run anyway**).
4. A black window shows **Installed.** Press any key to close it.

#### macOS
1. Double-click the downloaded ZIP to unzip it.
2. In the unzipped folder, double-click **Install on macOS.command**.
3. If macOS says it can't check the file for malicious software: right-click (or Control-click) **Install on macOS.command**, choose **Open**, then **Open** again.
4. The Terminal window shows **Installed.** Press Enter to close it.

#### Linux
1. Unzip the download.
2. Open a terminal in the unzipped folder and run:
   ```bash
   sh "Install on Linux.sh"
   ```
   It works for Krita from your distribution, the AppImage, and Flatpak (`org.kde.krita`).

The installer copies the plugin into Krita's plugin folder and switches it on. It doesn't change anything else, and it never touches your images.

### Other way: install from inside Krita

Krita can install plugins from a ZIP itself:

1. Open Krita.
2. Choose **Tools › Scripts › Import Python Plugin from File…**
3. Pick the downloaded **Geekatplay-3D-Layers-Krita.zip** (no need to unzip it).
4. If the plugin was installed before, Krita asks whether to overwrite it: choose **Yes**.
5. Krita lists the imported plugin and asks **Enable plugins now? (Requires restart)**: choose **Yes**.
6. **Close Krita and open it again.**

Use **Import Python Plugin from File…**, not *from Web…*: given this project's address, the web option downloads the project's source code, which doesn't include the built 3D editor.

### Step 4: Check that it worked

1. Open Krita.
2. Choose **Settings › Configure Krita…** and click **Python Plugin Manager** at the bottom of the list on the left.
3. **Geekatplay 3D Layers** is in the list with a tick in front of it. (If it has no tick, tick it, click **OK** and restart Krita.)
4. Click **Cancel** to close the window.

Then open the docker as described next.

---

## 3. Open the 3D Layers docker

1. Open or create an image (**File › New** or **File › Open**).
2. Choose **Settings › Dockers › 3D Layers**.

The **3D Layers** docker appears on the right. Like any Krita docker you can drag it to another place, make it float, or put it in a tab with other dockers. Krita remembers where you put it.

![The 3D Layers docker: Create, Library and Settings tabs](images/krita-docker.png)

The docker has three tabs:

| Tab | What it's for |
|---|---|
| **Create** | Turn the active layer or selection into a 3D model and follow the jobs. When the active layer is a 3D layer, a box at the top offers **Edit pose & light** and **Detach**. |
| **Library** | Every 3D model on this computer, with previews. Double-click one to place it in your image. |
| **Settings** | Keys and options for each 3D service, the 3D editor, and the plugin's files. |

A blue line at the top of the docker says what just happened (for example "Placed Rocket (3D)"); a red one explains a problem.

---

## 4. Try it with the sample model

No account needed:

1. Open an image. Select the layer that the 3D model should go on top of.
2. In the docker's **Create** tab, click **Try the sample model**.
3. The 3D editor opens in its own window and shows your image around a toy rocket.
4. Drag in the picture to turn the view, click a light preset such as **Golden Hour**, and drag the orange sun to move the light.
5. Click **Place in Document**. The rocket is now a new layer in your image, exactly where you saw it. The editor window closes (if it doesn't, close it yourself).

---

## 5. Set up a 3D service

You need one service to make models from your own layers. All of them return a textured 3D model.

### Meshy
1. Sign in at [meshy.ai](https://www.meshy.ai) and open [API keys](https://www.meshy.ai/developers/keys). API access needs a paid Meshy plan.
2. Create a key. It starts with `msy_`.
3. In the docker: **Settings** tab › **Meshy** › paste the key into **API key** › **Save**.
4. Click **Test connection**. It shows **Connected** and your credit balance.

Options: **Model** (`latest` always uses Meshy's newest; `meshy-t2` makes clean low-poly models), **Texture**, **PBR materials**, **Content moderation** (Meshy checks the picture before generating; on by default).

### Tripo
1. Sign in at [platform.tripo3d.ai](https://platform.tripo3d.ai) and open [API keys](https://platform.tripo3d.ai/api-keys).
2. Create a key. It starts with `tsk_`.
3. **Settings** tab › **Tripo** › **API key** › **Save** › **Test connection**.

Options: **Model** (v3.1 is the newest; P1 and P2 make low-poly models), **Texture**, **PBR materials**.

### Hitem3D (hi3d.ai)
1. Sign in at [platform.hi3d.ai](https://platform.hi3d.ai) and open [API Keys](https://platform.hi3d.ai/console/apiKey).
2. Create an **Access Key** and a **Secret Key**.
3. **Settings** tab › **Hitem3D** › paste both › **Save** each › **Test connection**.

Options: **Model**, **Resolution** (the choices depend on the model), **Face count** (0 means Hitem3D's default), **PBR materials**.

### ComfyUI

ComfyUI is free and runs on your own computer (or another computer on your network). It needs a strong graphics card; a model takes about five minutes on an RTX 3090. The plugin comes with a workflow for **TRELLIS.2**:

1. Install [ComfyUI](https://www.comfy.org), version 0.34 or newer, which includes the TRELLIS.2 nodes.
2. Get the TRELLIS.2 model files. The easiest way: in ComfyUI, open the template **"Pixal3D & TRELLIS.2: Image to Model"**; ComfyUI offers to download what is missing. The files are:
   - `trellis_2_int8_convrot.safetensors` (in `models/diffusion_models`)
   - `trellis_2_shape_vae_bf16.safetensors` and `trellis_2_texture_vae_bf16.safetensors` (in `models/vae`)
   - `dino_v3_L_naf_fp32.safetensors` (in `models/clip_vision`)
   - `birefnet.safetensors`, for background removal; only needed for pictures without a transparent background
3. Start ComfyUI.
4. In the docker: **Settings** tab › **ComfyUI** › **Address**: `http://127.0.0.1:8188` for ComfyUI on this computer. For another computer, use its address (that ComfyUI must be started with `--listen`).
5. Click **Test connection**. It shows ComfyUI's version and graphics card, and lists any TRELLIS.2 node or model file that is missing.

Options: **Texture size**, **Face count**.

**Your own workflow:** any image-to-3D workflow works. In ComfyUI, choose **Workflow › Export (API)** and save the file. In the docker, click **Load a workflow…** and choose that file. The workflow needs a **Load Image** node (the plugin puts your layer there; if there are several, name the right one "Krita", "input" or "source") and a node that saves a `.glb` file (such as **Save GLB**). **Use TRELLIS.2 (built in)** switches back.

---

## 6. Make a 3D model from a layer

1. Select the layer. The best results come from **one object on a transparent background**, so cut the object out first.
2. In the **Create** tab, choose the **Source**:
   - **Selection if any, else layer** (default): what you see inside your selection, or the active layer when nothing is selected;
   - **Active layer**: the layer's own pixels;
   - **Selection**: what you see inside the selection (soft selection edges stay soft).
3. Choose the **3D service** and, if you like, type a **Name**.
4. Click **Generate 3D model**.
5. The job appears under **Jobs** with its progress. You can keep working, hide the docker, or even close and reopen Krita: the job continues.
6. When it says **Ready**, the model is already saved in your library. Click **Pose & place** to open it in the 3D editor.

Big layers are made smaller before they are sent (**Settings › Generation › Max image size**, 2048 pixels by default), because the services have size limits.

If a job fails, the reason is shown in red. **Retry** sends it again (or downloads it again, if the service had finished). **Cancel** stops a running job; Meshy and ComfyUI also stop it on their side. **Remove** takes it off the list; the model stays in the library.

---

## 7. The 3D editor

The editor opens in its own window (Edge or Chrome without tabs) and shows the model over your image.

![The 3D editor](images/krita-editor.jpg)

| Part | What you can do |
|---|---|
| The picture | Drag to turn the view, right-drag to move it, scroll to zoom. Drag the **sun** (the orange ball) to light the model from another side. The picture has the same shape as the result, so what you frame is what you get. |
| Document | **Show document**: your image around the model (layers below behind it, layers above in front). **Layers above**: on or off. **Above opacity**: see the model through the layers above. |
| Light presets | Studio, Golden Hour, Noon, Dramatic, Rim, Soft, Moonlight |
| Light | Sun on/off, intensity, distance, ambient light, colour (swatches, colour temperature, hex) |
| Environment | Ten lighting environments, their strength, and *Show as background* (otherwise the background stays transparent) |
| Shadows | Cast shadow and contact shadow, each with blur and strength |
| Pose | Turn, tilt, roll, scale, and reset |
| Camera | Front, ¾ left, ¾ right, side, top, reset, and field of view |
| Export resolution | Width and height up to 8192 pixels, quick sizes, and **Match document** |

**Place in Document** puts the model in your image as a new paint layer named `<model> (3D)`, **above the layer that was selected**:
- with **Show document** on, exactly where you saw it;
- **Match document** makes the result the same size as your image, pixel for pixel; if the editor says the render is *enlarged*, choose a bigger export resolution so the layer stays sharp;
- with **Show document** off, the model is fitted into the area you sent it from (or the middle of the image).

**Cancel**, or closing the window, changes nothing. While the editor is open, the docker says **3D editor open**; its **Stop** button ends the session from Krita's side.

Light you set for a new model is used again for the next one (**Settings › 3D editor › Remember lighting for new models**).

---

## 8. Change a 3D layer later

1. Select the 3D layer in Krita's **Layers** docker. The **Create** tab shows a box: **3D layer · <model name>**.
2. Click **Edit pose & light**. The editor opens with the layer's pose and light.
3. Change anything and click **Update Layer**.

You can also use **Tools › Scripts › Edit 3D Layer (Pose & Light)…** and give it a keyboard shortcut in **Settings › Configure Krita › Keyboard Shortcuts** (search for "Edit 3D Layer").

Good to know:
- The layer stays where it is, also after you moved it with the **Move** tool or scaled it evenly with the **Transform** tool.
- The pose and light are saved inside your `.kra` file, so this works after closing and reopening it.
- **Update Layer** replaces the layer's pixels. To paint on top of a 3D layer, use a new layer above it.
- **Detach** removes the 3D data; the layer stays as an ordinary paint layer.
- A duplicated 3D layer is an ordinary copy; only the original can be changed.
- On another computer, the model must be in that computer's library (import its GLB file first).

---

## 9. The library

The **Library** tab shows every model on this computer, newest first, starred ones at the top.

- **Place a model:** double-click it.
- **Right-click a model:** **Place in the image**, **Rename**, **Star**, **Show the file**, **Move to folder**, **Remove from the library**. Select several with Ctrl-click or Shift-click to move or remove them together.
- **Folders:** the list above the models shows **All models**, the top level, or one folder (with its subfolders). The **⋯** button has **New folder**, **Rename this folder** and **Delete this folder**. Deleting a folder moves its models up one level; it never deletes models.
- **Search** looks in every folder.
- **Import your own 3D files:** **Import › Import files…** or **Import a folder…** (a folder keeps its subfolders), or drag files and folders from your file manager onto the models. Supported: GLB, glTF, FBX, OBJ (with its .mtl and textures), DAE, USDZ, 3DS, STL, PLY, 3MF, AMF, VRML, VOX. Files other than GLB are converted in a small browser window that closes by itself.
- **⋯ › Make missing previews** draws previews for models that have none.
- **⋯ › Show the library folder** opens it in your file manager.
- **Remove** deletes the model's files from your computer. Layers already placed in images keep their pixels.

If you also use Geekatplay 3D Layers for Photoshop, it uses this same library and the same keys.

---

## 10. Settings

| Group | Setting |
|---|---|
| 3D service | The service the Create tab starts with |
| Meshy, Tripo, Hitem3D, ComfyUI | Keys or address, model and options, **Test connection** |
| Generation | **Max image size**: the longest side of the picture sent to a service |
| 3D editor | **Export size** for new models; **Remember lighting for new models**; **Open the editor in** its own window (Edge or Chrome) or a browser tab |
| Files | **Show data folder**, **Open log** |

Saved keys show only as `msy_…1234`. The **✕** next to a key removes it from your computer.

---

## 11. Update or uninstall

**Update:** download the newest ZIP and install it the same way (section 2). Your models, keys and settings stay.

**Uninstall:**
- Windows: close Krita and double-click **Uninstall on Windows.cmd** in the unzipped folder.
- macOS and Linux: close Krita and run `sh install/install-unix.sh --uninstall` in the unzipped folder.
- Or, in Krita: **Settings › Configure Krita… › Python Plugin Manager**, untick **Geekatplay 3D Layers**, **OK**, restart Krita. (This switches it off but leaves its files.)

Your models and keys are kept in the data folder (section 12). Delete that folder too if you want them gone.

---

## 12. Files the plugin uses

| What | Windows | macOS | Linux |
|---|---|---|---|
| The plugin | `%APPDATA%\krita\pykrita\` | `~/Library/Application Support/krita/pykrita/` | `~/.local/share/krita/pykrita/` |
| Data folder | `%APPDATA%\Geekatplay\3D Layers\` | `~/Library/Application Support/Geekatplay/3D Layers/` | `~/.local/share/Geekatplay/3D Layers/` |

In the data folder:
- `library/`: your models, one folder each, and `index.json`, the list of them;
- `credentials.json`: your API keys (readable only by your user account on macOS and Linux);
- `krita/`: the plugin's settings and jobs;
- `logs/krita3d.log`: what the plugin did (keys are never written there).

Each 3D layer's model, pose and light are saved inside your `.kra` file.

---

## 13. Troubleshooting

| Problem | What to do |
|---|---|
| **3D Layers is not in Settings › Dockers** | Close Krita completely and open it again; Krita loads plugins only when it starts. Then check **Settings › Configure Krita… › Python Plugin Manager**: **Geekatplay 3D Layers** must be ticked (tick it, **OK**, restart Krita). |
| **Geekatplay 3D Layers is not in the Python Plugin Manager at all** | The plugin files are not in Krita's plugin folder. Close Krita and run the installer again (section 2). |
| **It is in the list but greyed out** | Hover over it to see why, and send us the reason (see the last line of this guide). |
| The installer says Krita is open | Close Krita (also any Krita windows in the background), then press Enter in the installer window. |
| The editor window doesn't open | **Settings › 3D editor › Open the editor in: A browser tab**. If still nothing opens, **Settings › Files › Open log** says which browser it tried. |
| The editor says "Krita is not reachable" | Krita was closed or restarted. Open the model again from Krita. |
| The editor says "This 3D editor session has ended" | **Stop** was clicked in the docker, or another model was opened. Open the model again from Krita. |
| A job fails with "cannot reach" | Check your internet connection. For ComfyUI: is ComfyUI running, and is the address in Settings right? |
| A service says the key is wrong | Paste the key again in **Settings**, click **Save**, then **Test connection**. |
| "The model is not in this computer's library" | The `.kra` came from another computer. Import the model's GLB on the **Library** tab, then try again. |
| "This 3D layer is no longer a paint layer" | The layer was converted (for example into a group). Place the model again. |

**Still stuck?** **Settings › Files › Open log** shows everything the plugin did. Please include it when you [report a problem](https://github.com/GeekatplayStudio/Krita-3D-Layers/issues).
