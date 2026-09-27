import json
import tempfile
import unittest
from pathlib import Path

from docking_universal.gui.results_model import ResultsReviewModel
from docking_universal.models import ArtifactRecord
from docking_universal.state import StudyState


class ResultsReviewModelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.compound = self.root / "compounds/ligand_a"
        self.analysis = self.compound / "pose_analysis"
        self.analysis.mkdir(parents=True)
        manifest = self.compound / "screen_manifest.json"
        manifest.write_text(json.dumps({
            "completion_status": "retained", "docking_site_count": 2,
            "docking_job_count": 30,
        }))
        (self.compound / "all_scores.csv").write_text("affinity\n-7.1\n-8.4\n")
        (self.analysis / "cluster_summary.csv").write_text(
            "energy_rank,cluster_id,best_energy_kcal_per_mol,pose_count\n1,2,-8.4,5\n"
        )
        self.state = StudyState("study", "Study", "screening")
        self.state.artifacts.append(ArtifactRecord(
            "manifest", "screening_compound_manifest", str(manifest),
        ))

    def tearDown(self):
        self.temporary.cleanup()

    def test_compound_projection_is_read_only_and_uses_retained_files(self):
        before = self.state.to_dict()
        result = ResultsReviewModel.compounds(self.state)[0]
        self.assertEqual(result.name, "ligand_a")
        self.assertEqual(result.best_score, -8.4)
        self.assertEqual(result.cluster_count, 1)
        self.assertEqual(self.state.to_dict(), before)

    def test_cluster_projection_orders_by_energy_rank(self):
        diagrams = []
        for cluster_id in (3, 2):
            folder = self.analysis / f"cluster_{cluster_id:03d}/interactions"
            folder.mkdir(parents=True)
            diagram = folder / "representative_plip2d.png"
            diagram.write_bytes(b"png")
            diagrams.append(diagram)
            self.state.artifacts.append(ArtifactRecord(
                f"diagram-{cluster_id}", "screening_interaction_diagram", str(diagram),
            ))
        (self.analysis / "cluster_summary.csv").write_text(
            "energy_rank,cluster_id,best_energy_kcal_per_mol,pose_count\n"
            "2,3,-8.0,4\n1,2,-8.4,5\n"
        )
        values = ResultsReviewModel.cluster_interactions(self.state, self.compound)
        self.assertEqual([item.cluster_id for item in values], ["002", "003"])
        self.assertIn("Energy rank 1", values[0].label)

    def test_cached_pose_lookup_has_stable_precedence(self):
        cache = self.analysis / "pose_interactions/pose_0004"
        cache.mkdir(parents=True)
        fallback = cache / "pose_plip2d.png"
        preferred = cache / "interaction_diagram.png"
        fallback.write_bytes(b"fallback")
        preferred.write_bytes(b"preferred")
        self.assertEqual(
            ResultsReviewModel.cached_pose_diagram(self.analysis, 4), preferred,
        )


if __name__ == "__main__":
    unittest.main()
