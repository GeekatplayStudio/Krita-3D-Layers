Geekatplay 3D Layers for Krita
by Geekatplay Studio - https://www.geekatplay.com

Turn any layer into a 3D model, pose it and light it in a 3D editor, and place it in your
image as a layer you can change any time.

INSTALL (pick one)

  Windows:  close Krita, then double-click "Install on Windows.cmd".
  macOS:    close Krita, then double-click "Install on macOS.command"
            (if macOS says it cannot check the file: right-click it, choose Open, then Open).
  Linux:    close Krita, then run:  sh "Install on Linux.sh"

  Or, from inside Krita: Tools > Scripts > Import Python Plugin from File..., choose this ZIP,
  answer Yes to enable it, and restart Krita.

START

  1. Open Krita and an image.
  2. Settings > Dockers > 3D Layers shows the panel.
  3. On its Create tab, click "Try the sample model". The 3D editor opens in its own window.
     Pose and light the model, then click "Place in Document".

To make your own models, add a key for Meshy, Tripo or Hitem3D (or the address of your
ComfyUI) on the panel's Settings tab, select a layer, and click "Generate 3D model".

The 3D editor opens in Microsoft Edge or Google Chrome (as its own window) because Krita
plugins cannot show 3D. It talks only to Krita, on this computer.

Requires Krita 5.2 or newer (Krita 6 too).

UNINSTALL

  Windows: double-click "Uninstall on Windows.cmd".  macOS/Linux: sh install/install-unix.sh --uninstall
  Your model library and keys stay in the "Geekatplay/3D Layers" data folder.

Free and open source (MIT license).
