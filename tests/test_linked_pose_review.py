import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from docking_universal.gui.linked_pose_review import (
    pose_view, control_view, interaction_contacts, comparison_summary, write_comparison_report,
)


class LinkedIdentityTests(unittest.TestCase):
    def test_cluster_and_exact_pose_use_their_own_coordinates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "receptor.pdb").write_text("receptor")
            cluster = root / "cluster_031"
            (cluster / "interactions").mkdir(parents=True)
            image = cluster / "interactions" / "representative_plip2d.png"
            image.write_bytes(b"image")
            (cluster / "representative.sdf").write_text("representative")
            self.assertEqual(pose_view(image).ligand, (cluster / "representative.sdf").resolve())
            cache = root / "pose_interactions" / "pose_0099"
            cache.mkdir(parents=True)
            exact = cache / "interaction_diagram.png"
            exact.write_bytes(b"image")
            self.assertIsNone(pose_view(exact))
            (cache / "pose.sdf").write_text("different exact pose")
            self.assertEqual(pose_view(exact).ligand, (cache / "pose.sdf").resolve())

    def test_comparison_keeps_chain_and_contact_class_distinct(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            def write(name, chain):
                path = root / name
                path.write_text(f"<report><bindingsite><interactions><hydrogen_bonds><hydrogen_bond>"
                                f"<restype>TYR</restype><reschain>{chain}</reschain><resnr>181</resnr>"
                                "</hydrogen_bond></hydrogen_bonds></interactions></bindingsite></report>")
                return SimpleNamespace(interactions=path, diagram=path)
            query, reference = write("query.xml", "A"), write("reference.xml", "B")
            summary = comparison_summary(query, reference)
            self.assertIn("Shared: none", summary)
            self.assertIn("Control only: TYR B:181", summary)
            self.assertIn("Docked only: TYR A:181", summary)
            output = root / "report.html"
            write_comparison_report(output, query, reference, query.diagram, reference.diagram)
            self.assertIn("data:image/png;base64,", output.read_text())
            self.assertIn("chemically valid atom correspondence", output.read_text())
            query.interactions.write_text("<report><bindingsite/><bindingsite/></report>")
            with self.assertRaises(ValueError):
                interaction_contacts(query.interactions)

    def test_control_requires_experimental_coordinates_and_specific_retained_layout(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            state = SimpleNamespace(workflow_data={"latest_control_output": str(root)})
            self.assertIsNone(control_view(state))
            (root / "00_inputs").mkdir()
            (root / "00_inputs" / "LIG_experimental.sdf").write_text("experimental")
            (root / "report" / "control_pose_analysis").mkdir(parents=True)
            (root / "report" / "control_pose_analysis" / "receptor.pdb").write_text("receptor")
            (root / "report" / "control_experimental_plip2d.png").write_bytes(b"image")
            self.assertEqual(control_view(state).label, "Experimental control ligand")
            (root / "00_inputs" / "OTHER_experimental.sdf").write_text("ambiguous")
            self.assertIsNone(control_view(state))
