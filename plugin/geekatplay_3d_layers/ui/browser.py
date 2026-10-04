"""
Opens the 3D editor's page in a browser window.

Preferred: an "app" window of a Chromium browser (Edge, which every Windows 10/11 has, or
Chrome, Brave, Chromium): no tabs or address bar, so it looks like part of the plugin, and
the page may close itself when you click Place or Cancel. Otherwise the default browser.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import List, Optional

from .qt import QDesktopServices, QUrl


def _candidates() -> List[str]:
    if sys.platform == "win32":
        roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        rels = [
            r"Microsoft\Edge\Application\msedge.exe",
            r"Google\Chrome\Application\chrome.exe",
            r"BraveSoftware\Brave-Browser\Application\brave.exe",
            r"Chromium\Application\chrome.exe",
        ]
        return [os.path.join(r, rel) for rel in rels for r in roots if r]
    if sys.platform == "darwin":
        apps = ["Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium"]
        return [f"/Applications/{a}.app/Contents/MacOS/{a}" for a in apps] + [os.path.expanduser(f"~/Applications/{a}.app/Contents/MacOS/{a}") for a in apps]
    return [p for p in (shutil.which(n) for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "brave-browser")) if p]


def chromium() -> Optional[str]:
    return next((p for p in _candidates() if p and os.path.isfile(p)), None)


def open_page(url: str, app_window: bool = True, size=(1280, 860), log=None) -> str:
    """Opens `url`; returns how ("app window (msedge.exe)" or "default browser")."""
    test_file = os.environ.get("G3D_TEST_URL_FILE")
    if test_file:
        # Automated tests (tests/e2e/krita.spec.ts) open the page themselves.
        with open(test_file, "a", encoding="utf-8") as fh:
            print(url, file=fh)
        return "test file"
    exe = chromium() if app_window else None
    if exe:
        try:
            flags = 0
            if sys.platform == "win32":
                flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen([exe, f"--app={url}", f"--window-size={size[0]},{size[1]}"], close_fds=True, creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"app window ({os.path.basename(exe)})"
        except OSError as err:
            if log:
                log.warn("Could not start the browser app window; using the default browser", str(err))
    QDesktopServices.openUrl(QUrl(url))
    return "default browser"
