import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from docking_universal.application import StudyController
from docking_universal.automation import AutomationPolicy, AutomationRule
from docking_universal.decisions import DecisionStatus
from docking_universal.services.pocket_review import (
    PocketReviewInputs,
    PocketReviewService,
    build_labeled_candidate_mappings,
    input_ligand_candidate,
)
from docking_universal.state import JsonStudyStore


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "create_protocol_for_service_test", ROOT / "libexec" / "docking-universal-create-protocol.py"
)
CREATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CREATE)


def box_text(center):
    return (
        f"center_x = {center}\ncenter_y = 0\ncenter_z = 0\n"
        "size_x = 26\nsize_y = 26\nsize_z = 26\n"
    )


class PocketReviewServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.cavity = self.root / "cavity"
        self.cavity.mkdir()
        self.boxes = tuple(self.cavity / f"target_pocket{number}.conf" for number in (1, 2))
        for number, path in enumerate(self.boxes, 1):
            path.write_text(box_text((number - 1) * 3))
        frozen = self.cavity / "frozen_pockets"
        frozen.mkdir()
        for number in (1, 2):
            x = (number - 1) * 3
            (frozen / f"pocket{number}_atm.pdb").write_text(
                f"{'ATOM':<6}{1:5d} {'C':^4} {'STP':>3} A{1:4d}    "
                f"{x:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00           C\n"
            )
        (self.cavity / "pocket_selection_diagnostics.tsv").write_text(
            "rank_order\tpocket_file\tscore\tdecision\n"
            "1\tpocket1_atm.pdb\t0.50\tselected\n"
            "2\tpocket2_atm.pdb\t0.48\tselected\n"
        )
        evidence_root = self.cavity / "pdb_site_evidence"
        ensemble = evidence_root / "structural_ensemble"
        ensemble.mkdir(parents=True)
        (ensemble / "structural_ensemble_manifest.json").write_text(
            '{"schema_name":"docking-universal-structural-ensemble"}\n'
        )
        (ensemble / "conformational_evidence.json").write_text(json.dumps({
            "observations": [{
                "residue": {"chain": "A", "name": "TYR", "number": "77"},
                "entry": "1ABC", "alignment_id": "1ABC_A_to_A",
                "maximum_chi_difference_degrees": 81.0,
                "side_chain_rmsd_angstrom": 2.1, "backbone_rmsd_angstrom": 0.2,
                "known_ligand_accessibility": [{
                    "source_ligand_id": "1ABC/LIG/B/1",
                    "consistent_with_side_chain_occlusion": True,
                }],
            }],
        }))
        self.evidence_path = evidence_root / "pdb_ligand_site_evidence.json"
        self.evidence = {
            "schema_name": "docking-universal-pocket-evidence",
            "evidence": [{
                "source_ligand_id": "1ABC/LIG/B/1", "entry": "1ABC", "ligand": "LIG",
                "evidence_class": "close_structural_homolog", "sequence_identity": 0.96,
                "query_coverage": 0.99, "ca_rmsd_angstrom": 0.72,
                "aligned_ligand_pdb": "aligned_ligands/1ABC_LIG_B_1.pdb",
            }],
            "structural_ensemble": {
                "manifest": "structural_ensemble/structural_ensemble_manifest.json",
                "conformational_evidence": "structural_ensemble/conformational_evidence.json",
            },
            "ligand_site_groups": [{
                "site_number": 1,
                "site_identity": {"canonical_label": "L1"},
                "fpocket_recovery": {"best_matching_pocket": None},
                "evidence_class_counts": {"close_structural_homolog": 2},
                "members": [{"source_ligand_id": "1ABC/LIG/B/1"}],
                "box": {
                    "center_x": 30, "center_y": 0, "center_z": 0,
                    "size_x": 26, "size_y": 26, "size_z": 26,
                },
            }],
        }
        aligned = evidence_root / "aligned_ligands"
        aligned.mkdir()
        (aligned / "1ABC_LIG_B_1.pdb").write_text("HETATM    1  C1  LIG B   1       0.000   0.000   0.000\n")
        self.evidence_path.write_text(json.dumps(self.evidence))
        self.scene = self.cavity / "review.pml"
        self.scene.write_text("# review\n")
        self.store = JsonStudyStore(self.root / "runs")
        self.controller = StudyController(self.store)
        self.controller.create_study("real-review", "Real artifact review")

    def tearDown(self):
        self.temporary.cleanup()

    def inputs(self):
        return PocketReviewInputs(
            target="target",
            cavity_directory=self.cavity,
            boxes=self.boxes,
            pocket_evidence_record=self.evidence_path,
            review_scene=self.scene,
        )

    def bound_setup(self, x=40.):
        source = self.root / "input.pdb"
        source.write_text("".join(
            f"HETATM{i:5d}  C{i:<2} LIG B 601    {x + i:8.3f}{0:8.3f}{0:8.3f}  1.00 20.00           C\n"
            for i in range(1, 7)) +
            "HETATM   10  C1  LIG C 601     -90.000   0.000   0.000  1.00 20.00           C\n")
        return {"input_pdb": str(source), "ligand_resname": "LIG", "ligand_chain_id": "B",
                "ligand_residue_number": "601", "predict_pockets_with_ligand": True}

    def test_offline_bound_site_survives_prediction_without_an_invented_score(self):
        from dataclasses import replace
        inputs = replace(self.inputs(), pocket_evidence_record=None, bound_ligand_setup=self.bound_setup())
        PocketReviewService(self.controller).start("real-review", inputs)
        state = self.store.load("real-review")
        bound = next(row for row in state.workflow_data["pocket_candidates"] if row["id"] == "B1")
        self.assertEqual(bound["evidence"]["geometry"]["center_x"], 43.5)
        self.assertNotIn("score", bound["evidence"])
        self.assertNotIn("detector", bound["evidence"])
        self.assertEqual(bound["evidence"]["source"], "input_bound_ligand")
        self.assertNotIn("experimental_ligand_evidence", bound["evidence"])
        self.assertIn("not independent", bound["evidence"]["evidence_role"])
        self.assertTrue(any(a.kind == "bound_ligand" and Path(a.path).is_file() for a in state.artifacts))

    def test_bound_candidate_does_not_duplicate_an_identical_predicted_box(self):
        from dataclasses import replace
        setup = self.bound_setup(x=-3.5)
        inputs = replace(self.inputs(), pocket_evidence_record=None, bound_ligand_setup=setup)
        PocketReviewService(self.controller).start("real-review", inputs)
        state = self.store.load("real-review")
        self.assertNotIn("B1", [row["id"] for row in state.workflow_data["pocket_candidates"]])
        p1 = next(row for row in state.workflow_data["pocket_candidates"] if row["id"] == "P1")
        self.assertEqual(p1["evidence"]["input_bound_ligand"]["source"], "input_bound_ligand")

    def test_large_input_ligand_box_expands_and_missing_exact_instance_is_refused(self):
        setup = self.bound_setup()
        path = Path(setup["input_pdb"])
        path.write_text(path.read_text().replace("  46.000", "  90.000"))
        item = input_ligand_candidate("target", self.cavity, setup)
        self.assertGreater(__import__('docking_universal_box_candidates').config_geometry(item['path'])['size_x'], 26.)
        with self.assertRaisesRegex(ValueError, "exact selected"):
            input_ligand_candidate("target", self.cavity, dict(setup, ligand_chain_id="X"))

    def test_real_artifacts_become_persisted_candidates_and_review_evidence(self):
        decision = PocketReviewService(self.controller).start("real-review", self.inputs())
        self.assertEqual([option.value for option in decision.options], ["P1", "P2", "P1/P2", "L1"])
        state = self.controller.get_study("real-review")
        kinds = {artifact.kind for artifact in state.artifacts}
        self.assertTrue({"docking_box", "pocket_coordinates", "pocket_evidence", "structural_ensemble", "conformational_evidence", "pymol_scene"} <= kinds)
        p1 = next(item for item in state.workflow_data["pocket_candidates"] if item["id"] == "P1")
        self.assertTrue(p1["evidence"]["viewer_artifact_ids"])
        self.assertTrue(all(artifact.sha256 for artifact in state.artifacts))
        self.assertEqual(state.workflow_data["pocket_review_source"]["candidate_count"], 4)
        self.assertFalse(next(option for option in decision.options if option.value == "L1").automation_eligible)
        ligand_site = next(item for item in state.workflow_data["pocket_candidates"] if item["id"] == "L1")
        conformation = ligand_site["evidence"]["conformational_site_evidence"]
        self.assertEqual(conformation["status"], "conformationally_incompatible")
        self.assertEqual(conformation["occluding_residues"][0]["name"], "TYR")
        self.assertEqual(conformation["decision_role"], "evidence_for_box_review_only")
        experimental = ligand_site["evidence"]["experimental_ligand_evidence"]
        self.assertEqual(experimental["observation_count"], 1)
        self.assertEqual(experimental["evidence_class_counts"], {"close_structural_homolog": 1})
        self.assertEqual(experimental["minimum_ca_rmsd_angstrom"], 0.72)
        self.assertTrue(Path(experimental["observations"][0]["aligned_ligand_pdb"]).is_file())

    def test_stale_unselected_pocket_config_is_not_presented_as_candidate(self):
        (self.cavity / "target_pocket4.conf").write_text(
            "center_x = 1\ncenter_y = 1\ncenter_z = 1\nsize_x = 26\nsize_y = 26\nsize_z = 26\n"
        )
        (self.cavity / "selected_pocket_records.txt").write_text(
            "2.0|frozen_pockets/pocket1_atm.pdb|0|0|0|2.0\n"
            "1.0|frozen_pockets/pocket4_atm.pdb|1|1|1|1.0\n"
        )
        mappings = build_labeled_candidate_mappings("target", list(self.boxes) + [self.cavity / "target_pocket4.conf"], self.evidence, self.cavity)
        self.assertEqual([item["label"] for item in mappings if item["label"] in {"P1", "P2", "P3", "P4"}], ["P1", "P4"])

    def test_cli_and_service_use_identical_candidate_builder(self):
        shared = build_labeled_candidate_mappings("target", list(self.boxes), self.evidence, self.cavity)
        cli = CREATE.build_labeled_box_candidates("target", list(self.boxes), self.evidence, self.cavity)
        self.assertEqual(
            [(item["label"], Path(item["path"]).read_text()) for item in cli],
            [(item["label"], Path(item["path"]).read_text()) for item in shared],
        )

    def test_p2rank_unmatched_ligand_site_remains_an_unscored_selectable_box(self):
        (self.cavity / "pocket_detection_provenance.json").write_text(json.dumps({
            "engine": "p2rank",
            "pocket_equivalences": [{
                "pockets": [1, 2],
                "fitted_pocket_atom_rmsd_angstrom": 0.42,
                "automatic_removal": False,
            }],
        }))
        self.evidence["pocket_engine"] = "p2rank"
        group = self.evidence["ligand_site_groups"][0]
        group["pocket_recovery"] = group.pop("fpocket_recovery")
        group["site_identity"]["is_separate_from_predicted_pocket"] = True
        self.evidence_path.write_text(json.dumps(self.evidence))

        decision = PocketReviewService(self.controller).start("real-review", self.inputs())
        ligand_option = next(option for option in decision.options if option.value == "L1")
        self.assertIn("without a corresponding p2rank cavity", ligand_option.consequence)
        state = self.controller.get_study("real-review")
        ligand_candidate = next(
            item for item in state.workflow_data["pocket_candidates"] if item["id"] == "L1"
        )
        self.assertEqual(ligand_candidate["evidence"]["kind"], "ligand_defined")
        self.assertNotIn("score", ligand_candidate["evidence"])
        p1 = next(item for item in state.workflow_data["pocket_candidates"] if item["id"] == "P1")
        self.assertTrue(p1["evidence"]["symmetry_equivalence_shown_in_box_selection"])
        self.assertIn("probable symmetry-related pocket copy of P2", p1["summary"])
        self.assertIn("fitted pocket RMSD 0.42 Å", p1["summary"])
        self.assertIn("both sites may be relevant", p1["summary"])

    def test_homolog_only_candidate_cannot_be_selected_by_automation(self):
        policy = AutomationPolicy(
            id="homolog-policy",
            name="Unsafe homolog policy",
            enabled=True,
            rules=(AutomationRule("select_pockets", ("L1",)),),
        )
        decision = PocketReviewService(self.controller).start(
            "real-review", self.inputs(), automation=policy,
        )
        self.assertEqual(decision.status, DecisionStatus.PENDING)
        state = self.controller.get_study("real-review")
        self.assertEqual(state.approvals, [])
        self.assertEqual(state.pending_decisions[0].id, decision.id)

    def test_selected_real_candidate_resumes_after_restart(self):
        decision = PocketReviewService(self.controller).start("real-review", self.inputs())
        restarted = StudyController(JsonStudyStore(self.root / "runs"))
        restarted.resolve_decision(
            "real-review", decision.id, ("P2", "L1"), actor="scientist",
            rationale="Retain the geometric and homolog-supported alternatives",
        )
        state = restarted.get_study("real-review")
        self.assertEqual(state.selected_pocket_ids, ["P2", "L1"])
        self.assertEqual(state.approvals[0].evidence["artifact_ids"], list(decision.artifact_ids))
        snapshots = state.approvals[0].evidence["artifacts"]
        self.assertTrue(snapshots)
        self.assertTrue(all(item["sha256"] for item in snapshots))
        self.assertGreaterEqual(state.approvals[0].evidence["study_revision"], 1)

    def test_missing_required_box_fails_before_creating_a_job(self):
        self.boxes[0].unlink()
        with self.assertRaises(FileNotFoundError):
            PocketReviewService(self.controller).start("real-review", self.inputs())
        self.assertEqual(self.controller.get_study("real-review").jobs, [])

    def test_p2rank_candidates_use_same_review_pipeline_with_true_provenance(self):
        (self.cavity / "pocket_detection_provenance.json").write_text(json.dumps({
            "schema_name": "docking-universal-pocket-detection", "engine": "p2rank",
        }))
        PocketReviewService(self.controller).start("real-review", self.inputs())
        state = self.controller.get_study("real-review")
        p1 = next(item for item in state.workflow_data["pocket_candidates"] if item["id"] == "P1")
        self.assertEqual(p1["evidence"]["detector"], "p2rank")
        self.assertIn("individual p2rank pocket box", p1["summary"])


if __name__ == "__main__":
    unittest.main()
