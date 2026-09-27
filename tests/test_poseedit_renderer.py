import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "libexec/docking-universal-render-poseedit.py"
PACKAGE = ROOT / "libexec/docking_universal/poseedit_renderer"


class PoseEditRendererPackagingTests(unittest.TestCase):
    def test_required_local_assets_are_packaged_without_private_paths(self):
        required = {
            "interaction-drawer.js", "d3.min.js", "fraction.min.js",
            "smiles-drawer.min.js", "pack-scene.js", "LICENSE-InteractionDrawer.txt",
        }
        self.assertTrue(required <= {path.name for path in (PACKAGE / "assets").iterdir()})
        for path in PACKAGE.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".js", ".mjs", ".cjs"}:
                text = path.read_text(errors="replace")
                self.assertNotIn("/private/tmp", text)
                self.assertNotIn("/Users/", text)

    def test_unapproved_renderer_policy_is_rejected_before_inputs_are_read(self):
        result = subprocess.run([
            sys.executable, str(RENDERER), "--ligand", "missing.sdf",
            "--receptor", "missing.pdb", "--plip-xml", "missing.xml",
            "--output", "missing.png", "--renderer-policy", "legacy",
        ], text=True, capture_output=True, env={**os.environ, "PYTHONPATH": str(ROOT / "libexec")})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported renderer policy", result.stderr)


if __name__ == "__main__":
    unittest.main()
