import csv
import json
import tempfile
import unittest
from pathlib import Path

from docking_universal_reuse import compare_reuse_studies


class ReuseEquivalenceTests(unittest.TestCase):
    def make_study(self, root, label, score="-7.000"):
        compound = root / label / "compounds" / "ligand"
        (compound / "ligand_preparation/pdbqt_ligands").mkdir(parents=True)
        (compound / "pose_analysis").mkdir()
        (compound / "seed_41001/docking").mkdir(parents=True)
        manifest = {
            "workflow": "target_locked_unknown_docking", "completion_status": "CONTROL_APPROVED",
            "protocol_type": "control-validated", "protocol_sha256": "protocol",
            "ligand_sha256": "ligand", "receptor": "receptor.pdbqt", "box": "box.conf",
            "engine": "vina", "seeds": [41001], "ensemble_parameters": {"ph": 7.4},
            "docking_job_count": 1,
        }
        (compound / "screen_manifest.json").write_text(json.dumps(manifest))
        (compound / "independent_ensemble.sdf").write_text("ensemble\n")
        (compound / "ligand_preparation/pdbqt_ligands/independent_ensemble_1.pdbqt").write_text("ligand\n")
        (compound / "seed_41001/docking/ligand_vina.pdbqt").write_text("poses\n")
        (compound / "pose_analysis/cluster_summary.csv").write_text("cluster_id,count\n1,1\n")
        with (compound / "all_scores.csv").open("w", newline="") as handle:
            writer = csv.writer(handle); writer.writerow(("file_path", "affinity")); writer.writerow((f"/{label}/pose", score))
        with (compound / "pose_analysis/pose_inventory.csv").open("w", newline="") as handle:
            writer = csv.writer(handle); writer.writerow(("pose_id", "cluster_id", "source")); writer.writerow((1, 1, f"/{label}/pose"))
        return root / label

    def test_paths_may_differ_but_scientific_outputs_must_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.make_study(root, "immediate")
            second = self.make_study(root, "restarted")
            self.assertEqual(compare_reuse_studies(first, second)["status"], "equivalent")

    def test_score_difference_fails_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.make_study(root, "immediate")
            second = self.make_study(root, "restarted", score="-6.000")
            with self.assertRaisesRegex(ValueError, "scores differ"):
                compare_reuse_studies(first, second)


if __name__ == "__main__":
    unittest.main()
