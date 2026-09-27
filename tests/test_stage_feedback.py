import tempfile
import unittest
from pathlib import Path

from docking_universal.stage_feedback import (
    control_feedback, finalization_feedback, preparation_feedback, screening_feedback,
)


class StageFeedbackTests(unittest.TestCase):
    def test_preparation_and_finalization_milestones_follow_real_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdb = root / "receptor" / "target.pdb"
            pdbqt = root / "receptor" / "target.pdbqt"
            self.assertEqual(preparation_feedback(root, pdb, pdbqt)[0], "input")
            pdb.parent.mkdir()
            pdb.write_text("ATOM\n")
            self.assertEqual(preparation_feedback(root, pdb, pdbqt)[0], "coordinates")
            pdbqt.write_text("ATOM\n")
            self.assertEqual(preparation_feedback(root, pdb, pdbqt)[0], "receptor")
            cavity = root / "cavity"
            cavity.mkdir()
            (cavity / "target_pocket1.conf").write_text("center_x = 1\n")
            self.assertEqual(preparation_feedback(root, pdb, pdbqt)[0], "pockets")

            protocol = root / "protocol.json"
            report = root / "report.pdf"
            bundle = root / "protocol.duprotocol"
            self.assertEqual(finalization_feedback(protocol, report, bundle)[0], "setup")
            protocol.write_text("{}")
            self.assertEqual(finalization_feedback(protocol, report, bundle)[0], "protocol")
            report.write_text("%PDF")
            self.assertEqual(finalization_feedback(protocol, report, bundle)[0], "report")
            bundle.write_text("bundle")
            self.assertEqual(finalization_feedback(protocol, report, bundle)[0], "bundle")

    def test_screening_distinguishes_docking_from_analysis_and_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(screening_feedback(root, 2)[0], "ligands")
            docking = root / "compounds" / "ligand" / "seed_1" / "docking"
            docking.mkdir(parents=True)
            (docking / "independent_ensemble_1_vina.pdbqt").write_text("MODEL\n")
            self.assertEqual(screening_feedback(root, 2)[2:], (1, 2))
            (docking / "independent_ensemble_2_vina.pdbqt").write_text("MODEL\n")
            self.assertEqual(screening_feedback(root, 2)[0], "analysis")
            (root / "report").mkdir()
            (root / "report" / "screen.pdf").write_text("%PDF")
            self.assertEqual(screening_feedback(root, 2)[0], "report")

    def test_control_bundle_presence_is_only_a_verification_milestone(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(control_feedback(root)[0], "preparation")
            (root / "study_manifest.json").write_text("{}")
            self.assertEqual(control_feedback(root)[0], "assessment")
            (root / "unverified.duprotocol").write_bytes(b"not a bundle")
            self.assertIn("verifying", control_feedback(root)[1])
