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
        self.assertEqual(result.scoring_function, "Not recorded")
        self.assertEqual(self.state.to_dict(), before)

    def test_scoring_identity_comes_from_each_retained_manifest_not_current_settings(self):
        manifest = self.compound / "screen_manifest.json"
        for engine, expected in (("vina", "Vina"), ("qvinaw", "Vina"),
                                 ("adgpu", "AD4"), ("unknown", "Not recorded")):
            with self.subTest(engine=engine):
                manifest.write_text(json.dumps({"engine": engine}))
                before = manifest.read_bytes()
                self.state.workflow_data['study_setup'] = {'engine': 'adgpu' if engine != 'adgpu' else 'vina'}
                result = ResultsReviewModel.compounds(self.state)[0]
                self.assertEqual(result.scoring_function, expected)
                self.assertEqual(result.best_score, -8.4)
                self.assertEqual(manifest.read_bytes(), before)

    def test_real_collector_energy_column_for_every_engine(self):
        manifest = self.compound / "screen_manifest.json"
        scores = self.compound / "all_scores.csv"
        for engine, label in (("vina", "Vina"), ("qvinaw", "Vina"), ("adgpu", "AD4")):
            with self.subTest(engine=engine):
                manifest.write_text(json.dumps({"engine": engine}))
                scores.write_text(
                    "site,seed,score_format,affinity_kcal_per_mol,rmsd_lower_bound,rmsd_upper_bound\n"
                    f"1,123,{engine},-7.25,0,0\n1,123,{engine},-6.50,1,2\n"
                )
                before = scores.read_bytes()
                result = ResultsReviewModel.compounds(self.state)[0]
                self.assertEqual(result.best_score, -7.25)
                self.assertEqual(result.scoring_function, label)
                self.assertEqual(scores.read_bytes(), before)

    def test_canonical_energy_precedes_legacy_aliases(self):
        (self.compound / "all_scores.csv").write_text(
            "affinity_kcal_per_mol,affinity,score\n-6.1,-9,-10\n"
        )
        self.assertEqual(ResultsReviewModel.compounds(self.state)[0].best_score, -6.1)

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
