import os
import subprocess
import sys
import unittest
import shutil
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "libexec/docking-universal-render-poseedit.py"
PACKAGE = ROOT / "libexec/docking_universal/poseedit_renderer"


class PoseEditRendererPackagingTests(unittest.TestCase):
    def test_required_local_assets_are_packaged_without_private_paths(self):
        required = {
            "interaction-drawer.js", "d3.min.js", "fraction.min.js",
            "smiles-drawer.min.js", "pack-scene.js", "LICENSE-InteractionDrawer.txt",
            "residue-scale.js",
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

    @unittest.skipUnless(shutil.which('node'), 'Local Node required for drawing-scale test')
    def test_residue_bonds_are_seventy_percent_without_changing_ligand_or_chemistry(self):
        program = """
global.window={}; require(process.argv[1]);
const make=n=>({atoms:[{id:1,element:'C',coordinates:{x:0,y:0},additionalInformation:{poseCoordinates:[1,2,3]}},
                       {id:2,element:'O',coordinates:{x:n,y:0}}],bonds:[{from:1,to:2,type:'double'}]});
const ligand=make(37.5), residue=make(15), original=JSON.stringify(ligand), bonds=JSON.stringify(residue.bonds);
window.matchResidueBondScale(residue,ligand);
console.log(JSON.stringify({length:residue.atoms[1].coordinates.x-residue.atoms[0].coordinates.x,
                           ligandUnchanged:original===JSON.stringify(ligand),
                           bondsUnchanged:bonds===JSON.stringify(residue.bonds),
                           source:residue.atoms[0].additionalInformation.poseCoordinates,
                           style:window.poseDiagramStyle}));
"""
        result = subprocess.run([shutil.which('node'), '-e', program, str(PACKAGE/'assets/residue-scale.js')],
                                check=True, capture_output=True, text=True)
        record = json.loads(result.stdout)
        self.assertAlmostEqual(record['length'], 26.25)
        self.assertTrue(record['ligandUnchanged'])
        self.assertTrue(record['bondsUnchanged'])
        self.assertEqual(record['source'], [1,2,3])
        self.assertEqual(record['style'], {'textSize':10, 'lineWidth':0.9})
        builder = (PACKAGE/'build_page.mjs').read_text()
        self.assertEqual(builder.count('window.matchResidueBondScale(structure, scene.structures[0])'), 2)
        self.assertIn("allowedStructureRepresentations:{default:['default']}", builder)

    def test_static_renderer_rejects_partial_contact_or_annotation_loads(self):
        builder = (PACKAGE/'build_page.mjs').read_text()
        renderer = (PACKAGE/'render.cjs').read_text()
        self.assertIn('window.__expectedSceneCounts',builder)
        self.assertIn('Object.entries(expectedCounts)',renderer)
        self.assertIn('Incomplete interaction diagram',renderer)
        self.assertLess(renderer.index('Incomplete interaction diagram'),renderer.index('await page.screenshot'))


if __name__ == "__main__":
    unittest.main()
