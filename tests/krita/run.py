"""
Runs tests/krita/g3d_integration.py inside Krita with kritarunner (no window opens).

    python tests/krita/run.py [path to kritarunner]

Exit code 0 when every check passed.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent.parent / "plugin"


def kritarunner() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    for candidate in (r"C:\Program Files\Krita (x64)\bin\kritarunner.com", "/Applications/krita.app/Contents/MacOS/kritarunner", shutil.which("kritarunner") or ""):
        if candidate and os.path.exists(candidate):
            return candidate
    sys.exit("kritarunner not found; pass its path")


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="g3d-krita-"))
    shutil.copy(HERE / "g3d_integration.py", work / "g3d_integration.py")
    out = work / "results.json"
    env = dict(os.environ, G3D_PLUGIN_DIR=str(PLUGIN))
    # kritarunner imports the script from the working folder.
    proc = subprocess.run([kritarunner(), "-s", "g3d_integration", str(out)], cwd=work, env=env, capture_output=True, text=True, timeout=300)
    if not out.exists():
        print(proc.stdout[-3000:], proc.stderr[-3000:])
        print("The script did not run inside Krita.")
        return 1
    results = json.loads(out.read_text())
    failed = [r for r in results if not r["ok"]]
    for r in results:
        print(("  ok    " if r["ok"] else "  FAIL  ") + r["name"] + ("" if r["ok"] else f"\n        {r['detail']}"))
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed inside Krita.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
