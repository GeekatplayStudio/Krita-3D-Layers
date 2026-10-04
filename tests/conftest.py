import sys
from pathlib import Path

# The plugin package lives in plugin/ (that folder is what Krita's pykrita folder receives).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugin"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
