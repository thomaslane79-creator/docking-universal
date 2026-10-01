import os
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from docking_universal.application import StudyController
from docking_universal.host import CommandDispatcher
from docking_universal.models import JobStatus
from docking_universal.protocol_finalization import FinalizationSettings, request_from_study
from docking_universal.orchestration import ProtocolWorkflowRunner
from docking_universal.state import JsonStudyStore
from docking_universal.viewer.messages import Command


ROOT = Path(__file__).parents[1]


class ProtocolWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = JsonStudyStore(self.root / "runs")
        self.controller = StudyController(self.store)
        self.controller.create_study("workflow", "Workflow")
        self.input = self.root / "Target.pdb"
        self.input.write_text("ATOM      1  CA  GLY A   1       0.000   0.000   0.000  1.00 10.00           C\n")

    def tearDown(self):
        self.temporary.cleanup()

    def executable(self, *, slow=False, finalizer_target=None):
        directory = self.root / ("slow-bin" if slow else "bin")
        directory.mkdir(exist_ok=True)
        path = directory / "docking-universal-prepare"
        sleep = "sleep 10\n" if slow else ""
        path.write_text(
            "#!/usr/bin/env bash\nset -eu\n"
            + sleep
            + "name=$(basename \"$1\" .pdb)\n"
            + "root=\"$PWD/${name}_receptor_prep\"\n"
            + "mkdir -p \"$root/receptor\" \"$root/cavity/frozen_pockets\" \"$root/cavity/pdb_site_evidence/structural_ensemble\"\n"
            + "cp \"$1\" \"$root/receptor/${name}.pdb\"\n"
            + "printf 'RECEPTOR\\n' > \"$root/receptor/${name}.pdbqt\"\n"
            + "printf '%s\\n' \"${MEEKO_ADD_TEMPLATES:-}\" > \"$root/receptor/meeko-template-environment.txt\"\n"
            + "printf 'complete\\n' > \"$root/run.log\"\n"
            + "printf 'unchanged preliminary report\\n' > \"$root/preliminary-pocket-review.pdf\"\n"
            + "printf 'retained static image\\n' > \"$root/pocket-overview.png\"\n"
            + "printf 'retained report view\\n' > \"$root/cavity_selected_box.pse\"\n"
            + "printf 'center_x = 1\\ncenter_y = 2\\ncenter_z = 3\\nsize_x = 20\\nsize_y = 20\\nsize_z = 20\\n' > \"$root/cavity/${name}_pocket1.conf\"\n"
            + "printf 'ATOM      1  C   STP Z   1       1.000   2.000   3.000  1.00  1.00           C\\n' > \"$root/cavity/frozen_pockets/pocket1_atm.pdb\"\n"
            + "printf '# review\\n' > \"$root/cavity/${name}_all_retained_pockets_review.pml\"\n"
            + "printf '{\"structural_ensemble\":{\"manifest\":\"structural_ensemble/structural_ensemble_manifest.json\"}}\\n' > \"$root/cavity/pdb_site_evidence/pdb_ligand_site_evidence.json\"\n"
            + "printf '{\"schema_name\":\"docking-universal-structural-ensemble\"}\\n' > \"$root/cavity/pdb_site_evidence/structural_ensemble/structural_ensemble_manifest.json\"\n"
        )
        path.chmod(0o755)
        finalizer = directory / "docking-universal-finalize-protocol.py"
        if not finalizer.exists():
            finalizer.symlink_to(
                finalizer_target or ROOT / "libexec" / "docking-universal-finalize-protocol.py"
            )
        return path

    def intervention_executable(self):
        path = self.executable()
        original = path.read_text()
        path.write_text(
            "#!/usr/bin/env bash\nset -eu\n"
            "name=$(basename \"$1\" .pdb)\n"
            "root=\"$PWD/${name}_receptor_prep\"\n"
            "if [ -z \"${MEEKO_SET_TEMPLATE:-}\" ]; then\n"
            "  mkdir -p \"$root/receptor\"\n"
            "  printf '%s\\n' '{\"schema_name\":\"docking-universal-preparation-intervention\",\"schema_version\":1,\"kind\":\"histidine_template\",\"category\":\"Ambiguous histidine protonation\",\"scientific_concern\":\"Template choice changes the receptor model.\",\"residue\":\"A:57\",\"eligible_histidines\":[\"A:57\"]}' > \"$root/receptor/preparation_intervention.json\"\n"
            "  exit 1\n"
            "fi\n"
            + original.split("\n", 2)[2]
        )
        path.chmod(0o755)
        return path

    def start_command(self, dispatcher, request_id="prepare"):
        state = self.store.load("workflow")
        return Command(
            "workflow", "session", request_id, "start_receptor_preparation",
            {
                "input_pdb": str(self.input), "working_directory": str(self.root / "work"),
                "site_mode": "pockets", "feedback_level": "guided",
                "cavity_mode": 1, "max_pockets": 3,
                "center_mode": "deepest", "centroid_mode": 1,
            },
            state.revision,
        )

    def wait_for(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.store.load("workflow")
            if predicate(state):
                return state
            time.sleep(0.02)
        self.fail("Timed out waiting for asynchronous workflow state")

    def test_preparation_discovers_artifacts_and_pauses_for_pocket_review(self):
        dispatcher = CommandDispatcher(self.controller, "session", self.executable())
        response = dispatcher.dispatch(self.start_command(dispatcher))
        self.assertEqual(response.status, "applied")
        state = self.wait_for(lambda item: bool(item.pending_decisions))
        self.assertEqual(state.pending_decisions[0].kind, "select_pockets")
        self.assertEqual([option.value for option in state.pending_decisions[0].options], ["P1"])
        kinds = {artifact.kind for artifact in state.artifacts}
        self.assertTrue({
            "prepared_receptor_structure", "prepared_receptor", "preliminary_report",
            "scientific_image", "report_view_session", "pocket_coordinates", "docking_box",
        } <= kinds)
        preliminary = next(artifact for artifact in state.artifacts if artifact.kind == "preliminary_report")
        self.assertEqual(Path(preliminary.path).read_text(), "unchanged preliminary report\n")
        self.assertEqual(state.jobs[0].status, JobStatus.COMPLETED)
        self.assertIsNotNone(state.jobs[0].process_id)
        duplicate_stage = dispatcher.dispatch(self.start_command(dispatcher, "second-preparation"))
        self.assertEqual(duplicate_stage.status, "rejected")
        self.assertIn("already complete", duplicate_stage.error)

        decision = state.pending_decisions[0]
        self.controller.resolve_decision(
            "workflow", decision.id, ("P1",), actor="scientist",
            expected_revision=state.revision,
        )
        request = request_from_study(
            self.store.load("workflow"), FinalizationSettings(), self.root / "final",
            exploratory_use_approved=True,
        )
        self.assertEqual(request.approval_id, self.store.load("workflow").approvals[0].id)
        self.assertEqual(request.regions[0]["box_label"], "P1")
        self.assertEqual(request.source_structure.resolve(), self.input.resolve())
        self.assertIsNotNone(request.source_structure_sha256)
        self.assertIsNotNone(request.receptor_pdb_sha256)
        self.assertIsNotNone(request.receptor_pdbqt_sha256)

    def test_ligand_guided_preparation_collects_related_pdb_evidence(self):
        self.controller.create_study("ligand-workflow", "Ligand workflow")
        runner = ProtocolWorkflowRunner(self.controller, self.executable())
        state = self.store.load("ligand-workflow")
        runner.start_preparation(
            "ligand-workflow",
            {
                "input_pdb": str(self.input),
                "working_directory": str(self.root / "ligand-work"),
                "site_mode": "ligand",
                "ligand_resname": "LIG",
                "ligand_chain_id": "A",
                "ligand_residue_number": "101",
                "pdb_pocket_evidence": "related-structures",
            },
            request_id="ligand-related-evidence",
            expected_revision=state.revision,
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            reviewed = self.store.load("ligand-workflow")
            if reviewed.pending_decisions:
                break
            time.sleep(0.02)
        else:
            self.fail("Timed out waiting for ligand-guided evidence review")
        self.assertEqual(
            reviewed.workflow_data["pdb_pocket_evidence"]["mode"],
            "related-structures",
        )
        self.assertTrue(any(
            artifact.kind == "pocket_evidence" for artifact in reviewed.artifacts
        ))
        runner.shutdown()

    def test_reviewed_meeko_template_path_reaches_the_supervised_preparation(self):
        template = self.root / "reviewed-meeko-templates.json"
        template.write_text('{"ambiguous":{"CSO":["CSO"]},"residue_templates":{}}\n')
        dispatcher = CommandDispatcher(self.controller, "session", self.executable())
        command = self.start_command(dispatcher, "reviewed-template")
        command.payload["meeko_template_file"] = str(template)
        response = dispatcher.dispatch(command)
        self.assertEqual(response.status, "applied", response.error)
        state = self.wait_for(lambda item: bool(item.pending_decisions))
        recorded = (
            Path(state.workflow_data["preparation_root"])
            / "receptor" / "meeko-template-environment.txt"
        )
        self.assertEqual(recorded.read_text().strip(), str(template.resolve()))
        self.assertEqual(
            state.workflow_data["study_setup"]["meeko_template_file"],
            str(template.resolve()),
        )

    def test_histidine_decision_resumes_same_preparation_job_and_archives_failed_attempt(self):
        dispatcher = CommandDispatcher(
            self.controller, "session", self.intervention_executable(),
        )
        started = dispatcher.dispatch(self.start_command(dispatcher, "histidine-preparation"))
        self.assertEqual(started.status, "applied")
        waiting = self.wait_for(lambda item: bool(item.pending_decisions))
        decision = waiting.pending_decisions[0]
        self.assertEqual(decision.kind, "select_histidine_template")
        job_id = waiting.jobs[0].id

        approved = dispatcher.dispatch(Command(
            "workflow", "session", "histidine-choice", "resolve_decision",
            {
                "decision_id": decision.id,
                "selections": ["HIE_CURRENT"],
                "actor": "scientist",
            },
            waiting.revision,
        ))
        self.assertEqual(approved.status, "applied", approved.error)
        reviewed = self.wait_for(lambda item: any(
            pending.kind == "select_pockets" for pending in item.pending_decisions
        ) and item.workflow_data.get("continuation_queue", [{}])[0].get("status") == "completed")

        preparation_jobs = [
            job for job in reviewed.jobs
            if job.stage == "preparation_and_pocket_detection"
        ]
        self.assertEqual(len(preparation_jobs), 1)
        self.assertEqual(preparation_jobs[0].id, job_id)
        self.assertEqual(preparation_jobs[0].status, JobStatus.COMPLETED)
        attempt = reviewed.workflow_data["preparation_attempts"][0]
        self.assertEqual(attempt["meeko_template_assignments"], "A:57=HIE")
        self.assertTrue(Path(attempt["archive"]).is_dir())
        self.assertTrue(Path(attempt["intervention_record"]).is_file())
        self.assertEqual(
            reviewed.workflow_data["continuation_queue"][0]["status"], "completed",
        )
    def test_histidine_sensitivity_prepares_both_neutral_receptor_states(self):
        dispatcher = CommandDispatcher(
            self.controller, "session", self.intervention_executable(),
        )
        dispatcher.dispatch(self.start_command(dispatcher, "histidine-sensitivity"))
        waiting = self.wait_for(lambda item: bool(item.pending_decisions))
        decision = waiting.pending_decisions[0]

        approved = dispatcher.dispatch(Command(
            "workflow", "session", "test-neutral-states", "resolve_decision",
            {
                "decision_id": decision.id,
                "selections": ["TEST_NEUTRAL_CURRENT"],
                "actor": "scientist",
                "rationale": "The retained evidence does not distinguish the neutral states.",
            },
            waiting.revision,
        ))
        self.assertEqual(approved.status, "applied", approved.error)
        reviewed = self.wait_for(lambda item: any(
            pending.kind == "select_pockets" for pending in item.pending_decisions
        ) and (item.workflow_data.get("receptor_state_sensitivity") or {}).get("status")
            == "prepared_for_box_review")

        sensitivity = reviewed.workflow_data["receptor_state_sensitivity"]
        self.assertEqual(sensitivity["states"], ["HIE", "HID"])
        self.assertEqual(sensitivity["comparison_stage"], "pending_box_selection")
        self.assertEqual(sensitivity["assignments"], {
            "HIE": "A:57=HIE", "HID": "A:57=HID",
        })
        self.assertTrue(Path(sensitivity["variants"]["HIE"]["receptor_pdbqt"]).is_file())
        self.assertTrue(Path(sensitivity["variants"]["HID"]["receptor_pdbqt"]).is_file())
        self.assertEqual(
            [job.stage for job in reviewed.jobs],
            ["preparation_and_pocket_detection", "receptor_state_variant_preparation",
             "pocket_review"],
        )
        self.assertEqual(
            reviewed.workflow_data["continuation_queue"][0]["status"], "completed",
        )
        pocket_decision = next(
            pending for pending in reviewed.pending_decisions
            if pending.kind == "select_pockets"
        )
        self.controller.resolve_decision(
            "workflow", pocket_decision.id, ("P1",), actor="scientist",
            expected_revision=reviewed.revision,
        )
        classified = self.store.load("workflow").workflow_data["receptor_state_sensitivity"]
        self.assertEqual(classified["affected_boxes"], ["P1"])
        self.assertEqual(classified["comparison_stage"], "required")
        self.assertEqual(
            classified["box_influence"]["status"], "conservative_all_affected",
        )

    def test_finalization_registers_surface_bearing_report_sessions(self):
        output = self.root / "final"
        report = output / "report" / "protocol.pdf"
        report.parent.mkdir(parents=True)
        protocol = output / "protocol.json"
        bundle = output / "protocol.duprotocol"
        selected = report.parent / "cavity_selected_box.pse"
        overview = report.parent / "cavity_panel_B_structure.pse"
        figure = report.parent / "cavity_panels_AB.png"
        for path in (report, protocol, bundle, selected, overview, figure):
            path.write_bytes(path.name.encode())

        runner = ProtocolWorkflowRunner(self.controller, self.executable())
        runner._register_final_outputs(
            "workflow", SimpleNamespace(protocol=protocol, report=report, bundle=bundle),
        )

        sessions = [
            artifact for artifact in self.store.load("workflow").artifacts
            if artifact.kind == "report_view_session"
        ]
        self.assertEqual({Path(item.path).name for item in sessions}, {
            "cavity_selected_box.pse", "cavity_panel_B_structure.pse",
        })
        self.assertTrue(all(item.sha256 for item in sessions))
        figures = [
            artifact for artifact in self.store.load("workflow").artifacts
            if artifact.kind == "final_report_figure"
        ]
        self.assertEqual([Path(item.path).name for item in figures], ["cavity_panels_AB.png"])

    def test_host_can_cancel_running_preparation(self):
        dispatcher = CommandDispatcher(self.controller, "session", self.executable(slow=True))
        started = dispatcher.dispatch(self.start_command(dispatcher, "slow"))
        self.assertEqual(started.status, "applied")
        snapshot = dispatcher.dispatch(Command("workflow", "session", "snapshot", "snapshot"))
        active_job_id = self.store.load("workflow").active_job.id
        cancelled = dispatcher.dispatch(Command(
            "workflow", "session", "cancel", "cancel_active_job",
            {"job_id": active_job_id}, snapshot.revision,
        ))
        self.assertEqual(cancelled.status, "applied")
        state = self.wait_for(lambda item: bool(item.jobs) and item.jobs[0].status is JobStatus.CANCELLED)
        self.assertEqual(state.pending_decisions, [])

    def test_host_shutdown_cancels_and_reaps_running_preparation(self):
        dispatcher = CommandDispatcher(self.controller, "session", self.executable(slow=True))
        started = dispatcher.dispatch(self.start_command(dispatcher, "shutdown"))
        self.assertEqual(started.status, "applied")
        dispatcher.shutdown()
        state = self.store.load("workflow")
        self.assertEqual(state.jobs[0].status, JobStatus.CANCELLED)
        self.assertIsNone(state.active_job)

    def test_approved_preparation_finalizes_to_real_report_and_bundle_without_rerun(self):
        dispatcher = CommandDispatcher(self.controller, "session", self.executable())
        dispatcher.dispatch(self.start_command(dispatcher, "prepare-once"))
        state = self.wait_for(lambda item: bool(item.pending_decisions))
        decision = state.pending_decisions[0]
        approved = dispatcher.dispatch(Command(
            "workflow", "session", "approve-region", "resolve_decision",
            {"decision_id": decision.id, "selections": ["P1"], "actor": "scientist"},
            state.revision,
        ))
        self.assertEqual(approved.status, "applied")
        output = self.root / "final protocol"
        unauthorized = dispatcher.dispatch(Command(
            "workflow", "session", "finalize-without-authority", "start_protocol_finalization",
            {"output_directory": str(output), "exploratory_use_approved": False},
            approved.revision,
        ))
        self.assertEqual(unauthorized.status, "rejected")
        self.assertIn("explicit exploratory-use approval", unauthorized.error)
        started = dispatcher.dispatch(Command(
            "workflow", "session", "finalize-once", "start_protocol_finalization",
            {
                "output_directory": str(output), "engine": "vina", "ph": 7.4,
                "conformers": 3, "seed_count": 2, "base_seed": 41001,
                "exhaustiveness": 16, "num_modes": 15, "energy_range": 8.0,
                "exploratory_use_approved": True,
            },
            approved.revision,
        ))
        self.assertEqual(started.status, "applied")
        state = self.wait_for(lambda item: any(
            artifact.kind == "protocol_bundle" for artifact in item.artifacts
        ), timeout=15)
        kinds = {artifact.kind for artifact in state.artifacts}
        self.assertTrue({"final_protocol", "final_report", "protocol_bundle"} <= kinds)
        self.assertEqual(state.completion_status.value, "completed")
        self.assertEqual(
            [job.stage for job in state.jobs].count("preparation_and_pocket_detection"), 1,
        )
        protocol_path = Path(next(
            artifact.path for artifact in state.artifacts if artifact.kind == "final_protocol"
        ))
        protocol = json.loads(protocol_path.read_text())
        self.assertEqual(protocol["docking_regions"][0]["box_label"], "P1")
        self.assertEqual(protocol["parameters"]["seeds"], [41001, 41002])
        self.assertTrue(Path(next(
            artifact.path for artifact in state.artifacts if artifact.kind == "final_report"
        )).read_bytes().startswith(b"%PDF-"))
        bundle_path = Path(next(
            artifact.path for artifact in state.artifacts if artifact.kind == "protocol_bundle"
        ))
        with zipfile.ZipFile(bundle_path) as archive:
            names = set(archive.namelist())
        self.assertTrue(any(name.endswith("pdb_ligand_site_evidence.json") for name in names))
        self.assertTrue(any(name.endswith("structural_ensemble_manifest.json") for name in names))
        duplicate = dispatcher.dispatch(Command(
            "workflow", "session", "finalize-again", "start_protocol_finalization",
            {"output_directory": str(output), "exploratory_use_approved": True},
            state.revision,
        ))
        self.assertEqual(duplicate.status, "rejected")
        self.assertIn("already complete", duplicate.error)
        dispatcher.shutdown()

    def test_running_finalization_can_be_cancelled_and_retried_later(self):
        slow_finalizer = self.root / "slow-finalizer.py"
        slow_finalizer.write_text(
            "#!/usr/bin/env python3\nimport time\ntime.sleep(10)\n"
        )
        slow_finalizer.chmod(0o755)
        dispatcher = CommandDispatcher(
            self.controller, "session", self.executable(finalizer_target=slow_finalizer),
        )
        dispatcher.dispatch(self.start_command(dispatcher, "prepare-for-cancel"))
        state = self.wait_for(lambda item: bool(item.pending_decisions))
        decision = state.pending_decisions[0]
        approved = dispatcher.dispatch(Command(
            "workflow", "session", "approve-for-cancel", "resolve_decision",
            {"decision_id": decision.id, "selections": ["P1"], "actor": "scientist"},
            state.revision,
        ))
        started = dispatcher.dispatch(Command(
            "workflow", "session", "slow-finalize", "start_protocol_finalization",
            {"output_directory": str(self.root / "cancelled-final"),
             "exploratory_use_approved": True},
            approved.revision,
        ))
        self.assertEqual(started.status, "applied")
        running = self.wait_for(lambda item: bool(
            item.active_job and item.active_job.stage == "final_report" and item.active_job.process_id
        ))
        cancelled = dispatcher.dispatch(Command(
            "workflow", "session", "cancel-finalize", "cancel_active_job",
            {"job_id": running.active_job.id}, running.revision,
        ))
        self.assertEqual(cancelled.status, "applied")
        state = self.wait_for(lambda item: any(
            job.stage == "final_report" and job.status is JobStatus.CANCELLED for job in item.jobs
        ))
        self.assertFalse(any(artifact.kind == "protocol_bundle" for artifact in state.artifacts))
        self.assertFalse(state.active_job)
        dispatcher.shutdown()


if __name__ == "__main__":
    unittest.main()
