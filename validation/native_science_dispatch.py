"""CI-only native stage dispatcher; not installed or a scientific approval UI."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
STAGES = {
    "_screen-stage": "docking-universal-screen.py",
    "depict2d": "docking-universal-depict2d.py",
    "ligands": "docking_universal_ligands.py",
    "dock": "docking_universal_dock.py",
    "collect": "docking-universal-collect.py",
    "cluster-poses": "docking-universal-cluster-poses.py",
    "render3d": "docking-universal-render3d.py",
    "interactions": "docking-universal-interactions.py",
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in STAGES:
        raise SystemExit("Unsupported native validation stage; no shell fallback")
    raise SystemExit(subprocess.call([sys.executable, str(ROOT / "libexec" / STAGES[sys.argv[1]]), *sys.argv[2:]], shell=False))
