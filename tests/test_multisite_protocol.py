#!/usr/bin/env python3
"""Regression checks for reusable protocols containing multiple docking sites."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCREEN = ROOT / "libexec" / "docking-universal-screen.py"
LIGAND = ROOT / "tests" / "inputs" / "protein_ligand_complex" / "rilpivirine_pubchem.sdf"


class MultiSiteProtocolTests(unittest.TestCase):
    def test_check_only_verifies_every_locked_site(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receptor = root / "receptor.pdbqt"; receptor.write_text("RECEPTOR\n")
            boxes = [root / f"pocket{i}.conf" for i in (1, 2)]
            for index, box in enumerate(boxes, 1):
                box.write_text(f"center_x = {index}\ncenter_y = 0\ncenter_z = 0\n")
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            regions = [
                {"site_number": index, "box": str(box), "box_name": box.name,
                 "box_sha256": digest(box)}
                for index, box in enumerate(boxes, 1)
            ]
            protocol = root / "protocol.json"
            protocol.write_text(json.dumps({
                "schema_name": "docking-universal-protocol", "schema_version": 1,
                "protocol_type": "site-guided-exploratory",
                "control_status": "not_performed", "unknown_docking_allowed": False,
                "exploratory_screening_allowed": True,
                "screening_authority": "user-confirmed-exploratory-use",
                "engine": "vina",
                "parameters": {
                    "macrocycle_treatment": "flexible_meeko", "conformers_per_state": 1,
                    "seeds": [101], "ensemble_seed": 101, "ph": 7.4,
                    "forcefield": "mmff94", "rmsd_prune_angstrom": 0.75,
                    "tautomers_enumerated": True, "charge_model": "gasteiger",
                    "exhaustiveness": 1, "num_modes": 1,
                    "energy_range_kcal_per_mol": 3,
                },
                "locked_inputs": {
                    "receptor": str(receptor), "receptor_sha256": digest(receptor),
                    "box": str(boxes[0]), "box_sha256": digest(boxes[0]), "boxes": regions,
                },
            }))
            completed = subprocess.run([
                sys.executable, SCREEN, "--protocol", protocol, "--ligand", LIGAND,
                "--out", root / "out", "--check-only", "--non-interactive",
                "--accept-exploratory-protocol",
            ], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Docking sites: 2", completed.stdout)
            self.assertIn("Site 1: pocket1.conf", completed.stdout)
            self.assertIn("Site 2: pocket2.conf", completed.stdout)

    def test_two_sites_execute_independently_and_are_combined_with_site_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receptor = root / "receptor.pdbqt"; receptor.write_text("RECEPTOR\n")
            boxes = [root / f"pocket{i}.conf" for i in (1, 2)]
            for index, box in enumerate(boxes, 1):
                box.write_text(
                    f"center_x = {index}\ncenter_y = 0\ncenter_z = 0\n"
                    "size_x = 20\nsize_y = 20\nsize_z = 20\n"
                )
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            protocol = root / "protocol.json"
            protocol.write_text(json.dumps({
                "schema_name": "docking-universal-protocol", "schema_version": 1,
                "protocol_type": "site-guided-exploratory",
                "control_status": "not_performed", "unknown_docking_allowed": False,
                "exploratory_screening_allowed": True,
                "screening_authority": "user-confirmed-exploratory-use", "engine": "vina",
                "parameters": {
                    "macrocycle_treatment": "flexible_meeko", "conformers_per_state": 1,
                    "seeds": [101], "ensemble_seed": 101, "ph": 7.4,
                    "forcefield": "mmff94", "rmsd_prune_angstrom": 0.75,
                    "tautomers_enumerated": True, "charge_model": "gasteiger",
                    "exhaustiveness": 1, "num_modes": 1, "energy_range_kcal_per_mol": 3,
                },
                "locked_inputs": {
                    "receptor": str(receptor), "receptor_sha256": digest(receptor),
                    "box": str(boxes[0]), "box_sha256": digest(boxes[0]),
                    "boxes": [
                        {"site_number": index, "box": str(box), "box_name": box.name,
                         "box_sha256": digest(box)}
                        for index, box in enumerate(boxes, 1)
                    ],
                },
            }))
            fake_libexec = root / "libexec"; fake_libexec.mkdir()
            ensemble = fake_libexec / "docking-universal-ensemble.py"
            ensemble.write_text(
                "import shutil,sys\n"
                "shutil.copy2(sys.argv[1], sys.argv[sys.argv.index(\"--out\") + 1])\n"
            )
            mock_cli = root / "docking-universal"
            mock_cli.write_text("""#!/usr/bin/env python3
import csv,sys
from pathlib import Path
command=sys.argv[1]; args=sys.argv[2:]
def value(flag): return Path(args[args.index(flag)+1])
if command == 'depict2d':
    out=value('--out-dir'); out.mkdir(parents=True,exist_ok=True); (out/'ligand.png').write_bytes(b'png')
elif command == 'ligands':
    out=value('--out')/'pdbqt_ligands'; out.mkdir(parents=True,exist_ok=True); (out/'ligand.pdbqt').write_text('MODEL\\n')
elif command == 'dock':
    out=value('--out'); out.mkdir(parents=True,exist_ok=True); (out/'ligand_vina.pdbqt').write_text('MODEL 1\\nREMARK VINA RESULT: -7.0 0.0 0.0\\nENDMDL\\n')
elif command == 'collect':
    out=value('--out'); out.parent.mkdir(parents=True,exist_ok=True); out.write_text('file,best_affinity_kcal_per_mol\\nligand_vina.pdbqt,-7.0\\n')
elif command == 'cluster-poses':
    out=value('--out'); out.mkdir(parents=True,exist_ok=True); (out/'cluster_summary.csv').write_text('energy_rank,cluster_id,best_energy_kcal_per_mol,pose_count,seed_support,conformer_support\\n1,1,-7.0,1,1,1\\n')
else:
    raise SystemExit('unexpected mock command: '+command)
""")
            mock_cli.chmod(0o755)
            output = root / "out"
            environment = os.environ.copy()
            environment.update({
                "DOCKING_UNIVERSAL_CLI": str(mock_cli),
                "DOCKING_UNIVERSAL_LIBEXEC": str(fake_libexec),
            })
            completed = subprocess.run([
                sys.executable, SCREEN, "--protocol", protocol, "--ligand", LIGAND,
                "--out", output, "--analysis", "summary", "--non-interactive",
                "--accept-exploratory-protocol",
            ], capture_output=True, text=True, env=environment)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((output / "site_1/pose_analysis/cluster_summary.csv").is_file())
            self.assertTrue((output / "site_2/pose_analysis/cluster_summary.csv").is_file())
            with (output / "all_scores.csv").open(newline="") as handle:
                rows = list(__import__("csv").DictReader(handle))
            self.assertEqual([row["site"] for row in rows], ["1", "2"])
            manifest = json.loads((output / "screen_manifest.json").read_text())
            self.assertEqual(manifest["docking_site_count"], 2)
            self.assertEqual(manifest["docking_job_count"], 2)


if __name__ == "__main__":
    unittest.main()
