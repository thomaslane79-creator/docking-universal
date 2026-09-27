import hashlib
import tempfile
import unittest
from pathlib import Path

from docking_universal.models import ArtifactRecord
from docking_universal.state import StudyState
from docking_universal.gui.study_viewer import StudyViewerCoordinator


class FakeAdapter:
    backend_kind = "embedded"
    backend_name = "Embedded PyMOL"

    def __init__(self):
        self.calls = []
        self.report_session = None

    def launch(self):
        self.calls.append(("launch",))

    def set_structure_context(self, identity):
        self.context = identity

    def register_structure(self, structure):
        self.calls.append(("structure", structure))

    def show_pocket(self, path, name, color):
        self.calls.append(("pocket", path, name, color))

    def show_box(self, center, size, color="red", source_object_name=None,
                 redundant_object_names=(), visible_associated_object_names=()):
        self.calls.append((
            "box", center, size, color, source_object_name, redundant_object_names,
            visible_associated_object_names,
        ))

    def capture_view(self):
        self.calls.append(("view",))

    def load_report_session(self, path):
        self.calls.append(("report_session", path))
        self.report_session = Path(path)

    def reconnect(self):
        self.calls.append(("reconnect",))

    def reset_report_view(self):
        self.calls.append(("reset_report_view",))

    def show_review_pose(self, path):
        self.calls.append(("review_pose", path))

    def close(self):
        self.calls.append(("close",))

    def is_alive(self):
        return True


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
        self.assertEqual(self.viewer.backend_kind, "embedded")
        self.assertEqual(self.viewer.backend_name, "Embedded PyMOL")
        self.viewer.open(self.state)
        self.assertEqual(self.adapter.context, "a" * 64)
        self.assertTrue(self.viewer.connected)
        self.assertEqual([call[0] for call in self.adapter.calls], ["launch", "structure", "pocket", "box", "view"])
        self.assertEqual(self.adapter.calls[3], (
            "box", [1, 2, 3], [20, 22, 24], "red", "candidate_box_P1", (), (),
        ))

    def test_candidate_highlight_keeps_the_report_palette_color(self):
        self.state.workflow_data["pocket_candidates"].append({
            "id": "P2", "rank": 2, "evidence": {"geometry": {
                "center_x": 4, "center_y": 5, "center_z": 6,
                "size_x": 20, "size_y": 22, "size_z": 24,
            }},
        })

        self.viewer.show_candidate(self.state, "P2")

        self.assertEqual(self.adapter.calls[-1], (
            "box", [4, 5, 6], [20, 22, 24], "marine", "candidate_box_P2", (), (),
        ))

    def test_candidate_with_corresponding_ligand_evidence_hides_legacy_evidence_box(self):
        candidate = self.state.workflow_data["pocket_candidates"][0]
        candidate["evidence"]["experimental_ligand_evidence"] = {"observation_count": 4}

        self.viewer.show_candidate(self.state, "P1")

        self.assertEqual(self.adapter.calls[-1][-2], ("ligand_site_box",))
        self.assertEqual(self.adapter.calls[-1][-1], ("ligand_site_representative",))

    def test_missing_receptor_is_an_explicit_visual_review_failure(self):
        self.state.artifacts = []
        with self.assertRaisesRegex(ValueError, "Required prepared-receptor"):
            self.viewer.open(self.state)

    def test_report_session_is_the_primary_live_view_and_can_be_reset(self):
        session = Path(self.temporary.name) / "cavity_selected_box.pse"
        session.write_bytes(b"retained report view")
        self.state.artifacts.append(ArtifactRecord(
            "report-view", "report_view_session", str(session),
            hashlib.sha256(session.read_bytes()).hexdigest(),
        ))
        self.viewer.open(self.state)
        self.assertTrue(self.viewer.connected)
        self.assertTrue(self.viewer.report_view_available)
        self.assertEqual(self.adapter.calls, [("launch",), ("report_session", str(session))])
        self.viewer.reset_report_view()
        self.assertEqual(self.adapter.calls[-1], ("reset_report_view",))

    def test_changed_report_session_is_rejected_before_pymol_loads_it(self):
        session = Path(self.temporary.name) / "cavity_selected_box.pse"
        session.write_bytes(b"registered view")
        self.state.artifacts.append(ArtifactRecord(
            "report-view", "report_view_session", str(session),
            hashlib.sha256(session.read_bytes()).hexdigest(),
        ))
        session.write_bytes(b"changed after registration")
        with self.assertRaisesRegex(ValueError, "artifact hash"):
            self.viewer.open(self.state)
        self.assertEqual(self.adapter.calls, [])

    def test_exact_materialized_pose_is_synchronized_to_live_viewer(self):
        cache = Path(self.temporary.name) / "analysis/pose_interactions/pose_0002"
        cache.mkdir(parents=True)
        pose = cache / "pose.sdf"
        pose.write_text("pose\n")
        self.viewer.connected = True
        self.assertEqual(self.viewer.show_pose(cache.parent.parent, 2), pose.resolve())
        self.assertEqual(self.adapter.calls[-1], ("review_pose", pose.resolve()))

    def test_failed_open_has_explicit_lifecycle_and_can_reconnect(self):
        class FailingOnceAdapter(FakeAdapter):
            def __init__(self):
                super().__init__()
                self.fail = True

            def launch(self):
                self.calls.append(("launch",))
                if self.fail:
                    self.fail = False
                    raise RuntimeError("viewer process exited")

        self.viewer.adapter = FailingOnceAdapter()
        with self.assertRaisesRegex(RuntimeError, "viewer process exited"):
            self.viewer.open(self.state)
        self.assertEqual(self.viewer.status, "failed")
        self.assertFalse(self.viewer.connected)
        self.assertIn("viewer process exited", self.viewer.last_error)

        self.viewer.reconnect(self.state)
        self.assertEqual(self.viewer.status, "connected")
        self.assertTrue(self.viewer.connected)
        self.assertEqual(self.viewer.adapter.calls[-1], ("reconnect",))

    def test_exited_viewer_is_detected_without_waiting_for_user_action(self):
        self.viewer.open(self.state)
        self.adapter.is_alive = lambda: False
        self.assertFalse(self.viewer.refresh_health())
        self.assertFalse(self.viewer.connected)
        self.assertEqual(self.viewer.status, "failed")
        self.assertIn("Embedded PyMOL stopped unexpectedly", self.viewer.last_error)


if __name__ == "__main__":
    unittest.main()
