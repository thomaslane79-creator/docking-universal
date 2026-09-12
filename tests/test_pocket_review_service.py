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
        self.evidence_path = evidence_root / "pdb_ligand_site_evidence.json"
        self.evidence = {
            "schema_name": "docking-universal-pocket-evidence",
            "structural_ensemble": {"manifest": "structural_ensemble/structural_ensemble_manifest.json"},
            "ligand_site_groups": [{
                "site_number": 1,
                "site_identity": {"canonical_label": "L1"},
                "fpocket_recovery": {"best_matching_pocket": None},
                "evidence_class_counts": {"close_structural_homolog": 2},
                "box": {
                    "center_x": 30, "center_y": 0, "center_z": 0,
                    "size_x": 26, "size_y": 26, "size_z": 26,
                },
            }],
        }
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

    def test_real_artifacts_become_persisted_candidates_and_review_evidence(self):
        decision = PocketReviewService(self.controller).start("real-review", self.inputs())
        self.assertEqual([option.value for option in decision.options], ["P1", "P2", "P1/P2", "L1"])
        state = self.controller.get_study("real-review")
        kinds = {artifact.kind for artifact in state.artifacts}
        self.assertTrue({"docking_box", "pocket_coordinates", "pocket_evidence", "structural_ensemble", "pymol_scene"} <= kinds)
        p1 = next(item for item in state.workflow_data["pocket_candidates"] if item["id"] == "P1")
        self.assertTrue(p1["evidence"]["viewer_artifact_ids"])
        self.assertTrue(all(artifact.sha256 for artifact in state.artifacts))
        self.assertEqual(state.workflow_data["pocket_review_source"]["candidate_count"], 4)
        self.assertFalse(next(option for option in decision.options if option.value == "L1").automation_eligible)

    def test_cli_and_service_use_identical_candidate_builder(self):
        shared = build_labeled_candidate_mappings("target", list(self.boxes), self.evidence, self.cavity)
        cli = CREATE.build_labeled_box_candidates("target", list(self.boxes), self.evidence, self.cavity)
        self.assertEqual(
            [(item["label"], Path(item["path"]).read_text()) for item in cli],
            [(item["label"], Path(item["path"]).read_text()) for item in shared],
        )

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

    def test_missing_required_box_fails_before_creating_a_job(self):
        self.boxes[0].unlink()
        with self.assertRaises(FileNotFoundError):
            PocketReviewService(self.controller).start("real-review", self.inputs())
        self.assertEqual(self.controller.get_study("real-review").jobs, [])


if __name__ == "__main__":
    unittest.main()
