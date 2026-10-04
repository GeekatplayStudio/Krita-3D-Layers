#!/bin/sh
# Geekatplay 3D Layers for Krita - installs the plugin (double-click in Finder)
cd "$(dirname "$0")" && sh install/install-unix.sh
echo "Press Enter to close this window."; read -r _
