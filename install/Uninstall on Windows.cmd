@echo off
rem Geekatplay 3D Layers for Krita - removes the plugin (your model library and keys stay)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\install-windows.ps1" -Uninstall
pause
