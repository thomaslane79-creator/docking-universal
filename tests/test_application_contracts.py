import json
import tempfile
import unittest
from pathlib import Path

from docking_universal.application import ActiveStageError, ExplicitApprovalRequired, StudyController
from docking_universal.automation import AutomationPolicy, AutomationRule
from docking_universal.decisions import DecisionOption, DecisionRequired
from docking_universal.events import ScientificDetail
from docking_universal.models import (
    CompletionStatus,
    DockingRequest,
    EngineCapabilities,
    FlexibleResidueSelection,
    Job,
    JobStatus,
    PocketCandidate,
    ReceptorComponent,
    ReceptorConfiguration,
    ScientificAuthority,
)
from docking_universal.state import JsonStudyStore


def candidates():
    return [
        PocketCandidate("pocket-1", "Pocket 1", 1, "box-1", "Highest-ranked geometric candidate", {"score": 0.72}),
        PocketCandidate("pocket-2", "Pocket 2", 2, "box-2", "Alternative candidate near the active-site residues", {"score": 0.68}),
    ]


class ApplicationContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = JsonStudyStore(Path(self.temporary.name))
        self.controller = StudyController(self.store)
        self.controller.create_study("study-1", "Example study")

    def tearDown(self):
        self.temporary.cleanup()

    def test_decision_pauses_and_resumes_after_controller_restart(self):
        decision = self.controller.start_simulated_pocket_review("study-1", candidates())
        waiting = self.controller.get_study("study-1")
        self.assertEqual(waiting.completion_status, CompletionStatus.WAITING_FOR_DECISION)
        self.assertEqual(waiting.active_job.status, JobStatus.WAITING_FOR_DECISION)

        restarted = StudyController(JsonStudyStore(Path(self.temporary.name)))
        approval = restarted.resolve_decision(
            "study-1", decision.id, ("pocket-1", "pocket-2"), actor="scientist", rationale="Review retained both sites"
        )
        completed = restarted.get_study("study-1")
        self.assertEqual(approval.method, "explicit_user")
        self.assertEqual(completed.selected_pocket_ids, ["pocket-1", "pocket-2"])
        self.assertEqual(completed.completion_status, CompletionStatus.COMPLETED)
        self.assertEqual(completed.scientific_authority, ScientificAuthority.EXPLORATORY_NO_CONTROL)
        self.assertIsNone(completed.active_job)

    def test_two_controllers_observe_one_persisted_run(self):
        second_window = StudyController(JsonStudyStore(Path(self.temporary.name)))
        decision = self.controller.start_simulated_pocket_review("study-1", candidates())
        self.assertEqual(second_window.get_study("study-1").pending_decisions[0].id, decision.id)
        second_window.resolve_decision("study-1", decision.id, ("pocket-2",), actor="scientist")
        self.assertEqual(self.controller.get_study("study-1").selected_pocket_ids, ["pocket-2"])

    def test_only_one_stage_can_be_active(self):
        self.controller.start_simulated_pocket_review("study-1", candidates())
        with self.assertRaises(ActiveStageError):
            self.controller.start_simulated_pocket_review("study-1", candidates())

    def test_presentation_detail_never_deletes_retained_evidence(self):
        self.controller.start_simulated_pocket_review("study-1", candidates())
        concise = self.controller.event_view("study-1", ScientificDetail.CONCISE)
        technical = self.controller.event_view("study-1", ScientificDetail.TECHNICAL)
        self.assertNotIn("data", concise[-1])
        self.assertIn("changes what molecular space", concise[-1]["explanation"])
        self.assertIn("decision", technical[-1]["data"])
        persisted = json.loads(self.store.path_for("study-1").read_text())
        self.assertEqual(len(persisted["events"][-1]["data"]["decision"]["options"]), 2)

    def test_eligible_automation_is_visible_and_audited(self):
        policy = AutomationPolicy(
            id="policy-1",
            name="Documented pocket policy",
            enabled=True,
            rules=(AutomationRule("select_pockets", ("pocket-1",)),),
        )
        self.controller.start_simulated_pocket_review("study-1", candidates(), automation=policy)
        state = self.controller.get_study("study-1")
        self.assertEqual(state.approvals[0].method, "automated_policy")
        self.assertEqual(state.approvals[0].policy_id, "policy-1")
        self.assertEqual(
            state.workflow_data["active_automation_policy"]["warning"],
            "AUTOMATED SCIENTIFIC DECISIONS",
        )
        self.assertTrue(any(event.message == "AUTOMATED SCIENTIFIC DECISIONS" for event in state.events))
        resolved = [event for event in state.events if event.type.value == "decision_resolved"]
        self.assertTrue(resolved[0].mandatory)

    def test_automation_cannot_bypass_explicit_decision(self):
        state = self.controller.get_study("study-1")
        state.decisions.append(
            DecisionRequired(
                id="model-change",
                kind="remove_receptor_component",
                prompt="Approve receptor modification",
                detected="An unmatched component remains",
                why_stopped="Removal changes the receptor model",
                consequences=("The receptor coordinates used for docking will change",),
                options=(DecisionOption("remove", "Remove", "Changes the molecular model"),),
                changes_molecular_model=True,
                automation_eligible=True,
            )
        )
        state.completion_status = CompletionStatus.WAITING_FOR_DECISION
        state.jobs.append(Job(
            id="job-model", stage="receptor_preparation", status=JobStatus.WAITING_FOR_DECISION
        ))
        self.store.save(state)
        with self.assertRaises(ExplicitApprovalRequired):
            self.controller.resolve_decision(
                "study-1", "model-change", ("remove",), actor="policy", policy_id="policy-unsafe"
            )

    def test_receptor_contract_supports_rigid_now_and_flexible_later(self):
        rigid = ReceptorConfiguration(ReceptorComponent("receptor-pdbqt", "rigid_receptor"))
        request = DockingRequest(
            receptor=rigid,
            ligand_artifact_ids=("ligand-pdbqt",),
            region_artifact_id="box-conf",
            engine=EngineCapabilities("vina", "1.2", supports_selected_side_chains=False),
        )
        request.validate()
        flexible = ReceptorConfiguration(
            ReceptorComponent("rigid-pdbqt", "rigid_receptor"),
            ReceptorComponent("flex-pdbqt", "flexible_receptor"),
            (FlexibleResidueSelection("A", "TYR", 42, evidence_artifact_id="flex-evidence"),),
        )
        unsupported = DockingRequest(
            receptor=flexible,
            ligand_artifact_ids=("ligand-pdbqt",),
            region_artifact_id="box-conf",
            engine=EngineCapabilities("engine-without-probe", "unknown"),
        )
        with self.assertRaisesRegex(ValueError, "has not declared"):
            unsupported.validate()


if __name__ == "__main__":
    unittest.main()
