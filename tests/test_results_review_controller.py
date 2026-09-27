import tempfile
import unittest
from pathlib import Path

from docking_universal.gui.results_controller import ResultsReviewController
from docking_universal.models import ArtifactRecord
from docking_universal.state import StudyState


class ResultsReviewControllerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.analysis = Path(self.temporary.name) / "pose_analysis"
        self.analysis.mkdir()
        self.controller = ResultsReviewController()

    def tearDown(self):
        self.temporary.cleanup()

    def decide(self, **changes):
        values = dict(
            compound="ligand", site="primary", analysis_root=self.analysis,
            pose_id=4, mirrored=False, host_available=True,
            renderer_available=True,
        )
        values.update(changes)
        return self.controller.select_pose(**values)

    def test_cache_hit_never_requests_scientific_work(self):
        cache = self.analysis / "pose_interactions/pose_0004"
        cache.mkdir(parents=True)
        diagram = cache / "interaction_diagram.png"
        diagram.write_bytes(b"png")
        decision = self.decide()
        self.assertEqual(decision.action, "cached")
        self.assertEqual(decision.diagram, diagram)

    def test_mirrored_cache_miss_waits_instead_of_requesting(self):
        self.assertEqual(self.decide(mirrored=True).action, "wait")
        self.assertEqual(self.decide(host_available=False).action, "host_unavailable")
        self.assertEqual(self.decide(renderer_available=False).action, "renderer_unavailable")
        self.assertEqual(self.decide().action, "request")

    def test_stale_completion_is_rejected_and_matching_artifact_is_found(self):
        decision = self.decide()
        stale = ("ligand", "primary", 3)
        self.assertFalse(self.controller.accepts(stale))
        self.assertTrue(self.controller.accepts(decision.key))
        diagram = self.analysis / "pose.png"
        diagram.write_bytes(b"png")
        state = StudyState("study", "Study", "screening")
        state.artifacts.append(ArtifactRecord(
            "pose", "pose_interaction_diagram", str(diagram), metadata={
                "pose_id": 4, "analysis_root": str(self.analysis.resolve()),
            },
        ))
        self.assertEqual(self.controller.completed_artifact(state).path, str(diagram))


if __name__ == "__main__":
    unittest.main()
