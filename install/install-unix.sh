#!/bin/sh
# Geekatplay 3D Layers for Krita - installer for macOS and Linux
# by Geekatplay Studio - https://www.geekatplay.com
#
# Copies the plugin into Krita's plugin folder and switches it on.
#   sh install-unix.sh            install
#   sh install-unix.sh --uninstall
# Your 3D model library and keys (Geekatplay/3D Layers in your user data folder) are never touched.
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
NAME=geekatplay_3d_layers

if [ "$(uname)" = "Darwin" ]; then
    PYKRITA="$HOME/Library/Application Support/krita/pykrita"
    KRITARC="$HOME/Library/Preferences/kritarc"
    RUNNING="pgrep -x krita"
elif [ -d "$HOME/.var/app/org.kde.krita" ]; then
    # Krita from Flathub keeps its files inside the sandbox folder.
    PYKRITA="$HOME/.var/app/org.kde.krita/data/krita/pykrita"
    KRITARC="$HOME/.var/app/org.kde.krita/config/kritarc"
    RUNNING="pgrep -f org.kde.krita"
else
    PYKRITA="${XDG_DATA_HOME:-$HOME/.local/share}/krita/pykrita"
    KRITARC="${XDG_CONFIG_HOME:-$HOME/.config}/kritarc"
    RUNNING="pgrep -x krita"
fi

echo ""
echo "  Geekatplay 3D Layers for Krita"
echo ""
# Krita writes its settings when it closes, so it must not be running while we switch the plugin on.
while $RUNNING >/dev/null 2>&1; do
    echo "  Krita is open. Please close Krita (save your work first), then press Enter here."
    read -r _
done

rm -rf "$PYKRITA/$NAME" "$PYKRITA/$NAME.desktop"
touch "$KRITARC" 2>/dev/null || { mkdir -p "$(dirname "$KRITARC")"; touch "$KRITARC"; }
TMP="$(mktemp)"
grep -v "^enable_$NAME=" "$KRITARC" > "$TMP" || true

if [ "$1" = "--uninstall" ]; then
    cp "$TMP" "$KRITARC"; rm -f "$TMP"
    echo "  Removed. Your model library and keys are still there."
    exit 0
fi

if [ ! -f "$HERE/$NAME/__init__.py" ]; then
    echo "  The plugin files were not found next to this installer. Unzip the whole download first."
    exit 1
fi
mkdir -p "$PYKRITA"
cp -R "$HERE/$NAME" "$PYKRITA/$NAME"
cp "$HERE/$NAME.desktop" "$PYKRITA/$NAME.desktop"

# Switch it on: Krita keeps plugin switches in kritarc, section [python].
if grep -q '^\[python\]' "$TMP"; then
    awk -v line="enable_$NAME=true" '{ print } /^\[python\]$/ { print line }' "$TMP" > "$KRITARC"
else
    cp "$TMP" "$KRITARC"
    printf '\n[python]\nenable_%s=true\n' "$NAME" >> "$KRITARC"
fi
rm -f "$TMP"

echo "  Installed."
echo ""
echo "  Next:"
echo "  1. Open Krita."
echo "  2. Settings > Dockers > 3D Layers shows the panel."
echo "  3. On its Create tab, click 'Try the sample model'."
echo ""
