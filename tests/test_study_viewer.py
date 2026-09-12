import tempfile
import unittest
from pathlib import Path

from docking_universal.models import ArtifactRecord
from docking_universal.state import StudyState
from docking_universal.gui.study_viewer import StudyViewerCoordinator


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def launch(self):
        self.calls.append(("launch",))

    def register_structure(self, structure):
        self.calls.append(("structure", structure))

    def show_pocket(self, path, name, color):
        self.calls.append(("pocket", path, name, color))

    def show_box(self, center, size):
        self.calls.append(("box", center, size))

    def capture_view(self):
        self.calls.append(("view",))

    def close(self):
        self.calls.append(("close",))


class StudyViewerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        receptor = root / "prepared.pdb"
        pocket = root / "pocket1_atm.pdb"
        receptor.write_text("END\n")
        pocket.write_text("END\n")
        self.state = StudyState("study", "Study", "site_guided_protocol")
        self.state.artifacts = [
            ArtifactRecord("receptor", "prepared_receptor_structure", str(receptor), "a" * 64),
            ArtifactRecord("pocket", "pocket_coordinates", str(pocket), "b" * 64),
        ]
        self.state.workflow_data["pocket_candidates"] = [{
            "id": "P1", "evidence": {"geometry": {
                "center_x": 1, "center_y": 2, "center_z": 3,
                "size_x": 20, "size_y": 22, "size_z": 24,
            }},
        }]
        self.adapter = FakeAdapter()
        self.viewer = StudyViewerCoordinator(self.adapter)

    def tearDown(self):
        self.temporary.cleanup()

    def test_open_uses_only_registered_retained_artifacts_and_geometry(self):
        self.viewer.open(self.state)
        self.assertTrue(self.viewer.connected)
        self.assertEqual([call[0] for call in self.adapter.calls], ["launch", "structure", "pocket", "box", "view"])
        self.assertEqual(self.adapter.calls[3], ("box", [1, 2, 3], [20, 22, 24]))

    def test_missing_receptor_is_an_explicit_visual_review_failure(self):
        self.state.artifacts = []
        with self.assertRaisesRegex(ValueError, "Required prepared-receptor"):
            self.viewer.open(self.state)


if __name__ == "__main__":
    unittest.main()
