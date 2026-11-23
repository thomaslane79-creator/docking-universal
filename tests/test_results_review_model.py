import json
import tempfile
import unittest
from pathlib import Path

from docking_universal.gui.results_model import ResultsReviewModel
from docking_universal.models import ArtifactRecord
from docking_universal.state import StudyState


class ResultsReviewModelTests(unittest.TestCase):
    def test_unregistered_cache_is_used_only_when_manifest_matches(self):
        from unittest.mock import patch
        from docking_universal.services.pose_interactions import PoseReviewRecord
        record = PoseReviewRecord(42, 7, -8.0, None, '', None, True)
        cache = self.analysis / 'pose_interactions' / 'pose_0042'
        (cache / 'plip').mkdir(parents=True)
        (cache / 'interaction_diagram.png').write_bytes(b'png')
        (cache / 'plip' / 'report.xml').write_text('<report/>')
        manifest = cache / 'interaction_manifest.json'
        manifest.write_text(json.dumps({'pose_id': 42, 'cluster_id': 7,
                                        'renderer_policy': 'approved-poseedit-local-v1', 'network_used': False}))
        with patch.object(ResultsReviewModel, 'poses', return_value=((self.analysis, record),)):
            values = ResultsReviewModel.cluster_interactions(self.state, self.compound)
            self.assertEqual([(value.pose_id, int(value.cluster_id)) for value in values], [(42, 7)])
            manifest.write_text(json.dumps({'pose_id': 42, 'cluster_id': 8,
                                            'renderer_policy': 'approved-poseedit-local-v1', 'network_used': False}))
            self.assertEqual(ResultsReviewModel.cluster_interactions(self.state, self.compound), ())

    def test_cluster_comparison_includes_clusters_without_diagrams(self):
        with tempfile.TemporaryDirectory() as directory:
            compound = Path(directory) / 'compound'
            analysis = compound / 'pose_analysis'
            analysis.mkdir(parents=True)
            (analysis / 'cluster_summary.csv').write_text(
                'energy_rank,cluster_id,best_energy_kcal_per_mol,pose_count,seed_support,conformer_support\n'
                '2,3,-7.5,10,3,2\n1,8,-9.0,4,2,1\n')
            rows = ResultsReviewModel.cluster_comparison(compound)
            self.assertEqual([row['cluster_id'] for row in rows], ['8', '3'])
            self.assertEqual(rows[0]['site'], 'primary site')
            self.assertEqual(rows[1]['seed_support'], '3')

    def test_on_demand_interaction_is_listed_with_its_pose_and_cluster(self):
        cache = self.analysis / 'pose_interactions' / 'pose_0042'
        cache.mkdir(parents=True)
        diagram = cache / 'interaction_diagram.png'
        diagram.write_bytes(b'png')
        (self.analysis / 'cluster_summary.csv').write_text(
            'energy_rank,cluster_id,best_energy_kcal_per_mol,pose_count\n4,7,-8.0,18\n')
        self.state.artifacts.append(ArtifactRecord(
            'pose-42', 'pose_interaction_diagram', str(diagram),
            metadata={'analysis_root': str(self.analysis), 'pose_id': 42, 'cluster_id': 7, 'score': -8.0}))
        results = ResultsReviewModel.cluster_interactions(self.state, self.compound)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].analysis_root, self.analysis)
        self.assertIn('Cluster 007', results[0].label)
        self.assertIn('pose 42 (on demand)', results[0].label)

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

    def test_compound_projection_uses_retained_display_name(self):
        inputs = self.root / 'inputs'
        inputs.mkdir()
        (inputs / 'compound_library_inventory.json').write_text(json.dumps({'compounds': [
            {'compound_id': 'ligand_a', 'compound_name': 'Original name'}]}))
        self.assertEqual(ResultsReviewModel.compounds(self.state)[0].name, 'Original name')
        report = self.root / 'report'
        report.mkdir()
        (report / 'compound_display_names.json').write_text(json.dumps({'names': {'ligand_a': 'pyronaridine'}}))
        self.assertEqual(ResultsReviewModel.compounds(self.state)[0].name, 'pyronaridine')

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
