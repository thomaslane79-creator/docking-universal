import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docking_universal.application import StudyController
from docking_universal.gui.desktop import QT_IMPORT_ERROR, StudyWindow
from docking_universal.gui.host_client import ApplicationHostClient
from docking_universal.models import Job, JobStatus
from docking_universal.state import JsonStudyStore


@unittest.skipIf(QT_IMPORT_ERROR is not None, "selected Qt 6 binding is unavailable")
class GuiFullJourneyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from docking_universal.gui.qt import QtWidgets
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        from docking_universal.gui.qt import QtCore, QtWidgets
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self._prior_mplconfig = os.environ.get("MPLCONFIGDIR")
        os.environ["MPLCONFIGDIR"] = str(self.root / "matplotlib-cache")
        self.store = JsonStudyStore(self.root / "runs")
        StudyController(self.store).create_study("journey", "GUI journey")
        self.input = self.root / "Target.pdb"
        self.input.write_text(
            "ATOM      1  CA  GLY A   1       0.000   0.000   0.000  1.00 10.00           C\n"
        )
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.preparation = self._make_scientific_fixtures()
        scientific_python = Path(os.environ.get(
            "DOCKING_UNIVERSAL_TEST_SCIENTIFIC_PYTHON",
            "/opt/anaconda3/envs/docking-universal/bin/python",
        ))
        if not scientific_python.is_file():
            self.skipTest("installed scientific Python is unavailable")
        host_script = self._make_host_script()
        self.client = ApplicationHostClient(
            self.store.root, host_script, python_executable=scientific_python,
            timeout_seconds=10,
        )
        self.client.start()
        self.settings = QtCore.QSettings(str(self.root / "window.ini"), QtCore.QSettings.IniFormat)
        self._message_patches = [
            patch.object(QtWidgets.QMessageBox, name, return_value=QtWidgets.QMessageBox.StandardButton.Ok)
            for name in ("critical", "warning", "information")
        ]
        for message_patch in self._message_patches:
            message_patch.start()
        self.window = StudyWindow(
            self.store, "journey", settings=self.settings, host_client=self.client,
        )

    def tearDown(self):
        self.window.close()
        self.client.close()
        for message_patch in reversed(self._message_patches):
            message_patch.stop()
        if self._prior_mplconfig is None:
            os.environ.pop("MPLCONFIGDIR", None)
        else:
            os.environ["MPLCONFIGDIR"] = self._prior_mplconfig
        self.temporary.cleanup()

    def _make_scientific_fixtures(self):
        prepare = self.bin / "docking-universal-prepare"
        prepare.write_text(
            "#!/bin/sh\nset -eu\nname=$(basename \"$1\" .pdb)\n"
            "root=\"$PWD/${name}_receptor_prep\"\n"
            "mkdir -p \"$root/receptor\" \"$root/cavity/frozen_pockets\" "
            "\"$root/cavity/pdb_site_evidence/structural_ensemble\"\n"
            "cp \"$1\" \"$root/receptor/${name}.pdb\"\nprintf 'RECEPTOR\\n' > \"$root/receptor/${name}.pdbqt\"\n"
            "printf 'complete\\n' > \"$root/run.log\"\nprintf 'report\\n' > \"$root/preliminary-pocket-review.pdf\"\n"
            "printf 'image\\n' > \"$root/pocket-overview.png\"\nprintf 'session\\n' > \"$root/cavity_selected_box.pse\"\n"
            "printf 'center_x = 1\\ncenter_y = 2\\ncenter_z = 3\\nsize_x = 20\\nsize_y = 20\\nsize_z = 20\\n' > \"$root/cavity/${name}_pocket1.conf\"\n"
            "printf 'ATOM      1  C   STP Z   1       1.000   2.000   3.000  1.00  1.00           C\\n' > \"$root/cavity/frozen_pockets/pocket1_atm.pdb\"\n"
            "printf '# review\\n' > \"$root/cavity/${name}_all_retained_pockets_review.pml\"\n"
            "printf '{\"structural_ensemble\":{\"manifest\":\"structural_ensemble/structural_ensemble_manifest.json\"}}\\n' > \"$root/cavity/pdb_site_evidence/pdb_ligand_site_evidence.json\"\n"
            "printf '{\"schema_name\":\"docking-universal-structural-ensemble\"}\\n' > \"$root/cavity/pdb_site_evidence/structural_ensemble/structural_ensemble_manifest.json\"\n"
        )
        prepare.chmod(0o755)
        (self.bin / "docking-universal-finalize-protocol.py").symlink_to(
            Path(__file__).parents[1] / "libexec/docking-universal-finalize-protocol.py"
        )
        runner = self.bin / "docking-universal-run.py"
        runner.write_text(
            "#!/usr/bin/env python3\nimport sys,json,zipfile\nfrom pathlib import Path\n"
            "a=sys.argv[1:]; o=Path(a[a.index('--out')+1]); "
            "\nif a[0]=='control':\n"
            " (o/'report').mkdir(parents=True)\n"
            " with zipfile.ZipFile(o/'target_control-validated.duprotocol','w') as z:\n"
            "  z.writestr('bundle_manifest.json',json.dumps({'protocol':'control/protocol.json'}))\n"
            "  z.writestr('control/protocol.json',json.dumps({'schema_name':'docking-universal-protocol','protocol_type':'control-validated','unknown_docking_allowed':True,'control_status':'approved','engine':'vina','parameters':{'conformers_per_state':1,'seeds':[1]},'locked_inputs':{'box':'assets/box.conf'}}))\n"
            " (o/'report/control.pdf').write_bytes(b'%PDF-1.4\\n%%EOF\\n')\n"
            " (o/'study_manifest.json').write_text('{\"study_status\":\"CONTROL_APPROVED\"}\\n')\n"
            " raise SystemExit(0)\n"
            "(o/'report').mkdir(parents=True); (o/'compounds/ligand').mkdir(parents=True); "
            "(o/'study_manifest.json').write_text('{}\\n'); "
            "(o/'report/study_summary.json').write_text('{}\\n'); "
            "(o/'report/screen.pdf').write_bytes(b'%PDF-1.4\\n%%EOF\\n'); "
            "(o/'compounds/ligand/screen_manifest.json').write_text('{}\\n'); "
            "(o/'compounds/ligand/all_scores.csv').write_text('affinity\\n-7.0\\n')\n"
        )
        runner.chmod(0o755)
        return prepare

    def _make_host_script(self):
        script = self.bin / "journey-host.py"
        script.write_text(
            "import argparse,json,sys\nfrom pathlib import Path\n"
            "from docking_universal.application import StudyController\n"
            "from docking_universal.host import CommandDispatcher,serve_json_lines\n"
            "from docking_universal.state import JsonStudyStore\n"
            "p=argparse.ArgumentParser(); p.add_argument('--state-root',type=Path,required=True); a=p.parse_args()\n"
            f"d=CommandDispatcher(StudyController(JsonStudyStore(a.state_root)),'gui-journey',Path({str(self.preparation)!r}))\n"
            "print(json.dumps({'type':'ready','version':1,'session_id':d.session_id,'runtime':"
            "{'python_executable':str(Path(sys.executable).resolve()),'python_version':'.'.join(map(str,sys.version_info[:3])),'conda_environment':'docking-universal'}}),flush=True)\n"
            "try: serve_json_lines(d,sys.stdin,sys.stdout)\nfinally: d.shutdown()\n"
        )
        return script

    def wait_for(self, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.application.processEvents()
            self.window.refresh()
            if predicate(self.store.load("journey")):
                self.window.refresh()
                return
            state = self.store.load("journey")
            if state.jobs and state.jobs[-1].status.value == "failed":
                self.fail(f"GUI journey stage failed: {state.jobs[-1].error}")
            time.sleep(0.02)
        self.fail("Timed out waiting for the GUI journey stage")

    def reopen(self):
        self.window.close()
        self.window = StudyWindow(
            self.store, "journey", settings=self.settings, host_client=self.client,
        )
        self.window.show()
        self.application.processEvents()

    def test_gui_feedback_preserves_figure_zoom(self):
        from docking_universal.gui.qt import QtGui

        figure = self.root / "decision.png"
        image = QtGui.QImage(80, 40, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("white"))
        self.assertTrue(image.save(str(figure)))
        self.window.decision_figure_choice.addItem("Decision figure", str(figure))
        self.window.decision_figure_choice.setCurrentIndex(
            self.window.decision_figure_choice.count() - 1
        )
        self.window._show_selected_decision_figure()
        loaded = self.window._decision_figure_pixmap
        self.window._decision_figure_zoom = 1.75
        self.window._show_selected_decision_figure()
        self.assertIs(self.window._decision_figure_pixmap, loaded)
        self.assertEqual(self.window._decision_figure_zoom, 1.75)

    def test_gui_shows_persisted_stage_feedback_after_refresh(self):
        def running(state):
            state.jobs.append(Job(
                id="feedback-job", stage="screening", status=JobStatus.RUNNING,
                progress_phase="docking", progress_message="Docking outputs ready: 3/15",
                progress_completed=3, progress_total=15,
            ))

        self.store.update("journey", running)
        self.window.refresh()
        self.assertIn("3/15", self.window.feedback_text.text())
        self.assertIn("3/15", self.window.screening_status.text())
        self.assertEqual(self.window.active_stage_progress.maximum(), 15)
        self.assertEqual(self.window.active_stage_progress.value(), 3)
        self.store.update(
            "journey", lambda state: setattr(state.jobs[-1], "status", JobStatus.COMPLETED),
        )
        self.window.refresh()

    def test_partial_failed_screening_is_not_presented_as_complete(self):
        def failed(state):
            state.jobs.append(Job(
                id="failed-screen", stage="screening", status=JobStatus.FAILED,
                error="Docking engine stopped before all seeds completed",
            ))
            state.workflow_data["latest_screening_output"] = str(self.root / "partial-screen")
            state.workflow_data["latest_screening_status"] = "failed"

        self.store.update("journey", failed)
        self.window.refresh()
        self.assertIn("did not complete", self.window.feedback_heading.text())
        self.assertIn("Docking engine stopped", self.window.screening_status.text())
        self.assertFalse(self.window.workflow_navigation.item(4).text().startswith("✓"))

    def test_known_ligand_path_is_chosen_before_control_and_persists_result(self):
        complex_path = self.root / "Bound.pdb"
        complex_path.write_text(
            self.input.read_text()
            + "HETATM    2  C1  LIG A 101       1.000   2.000   3.000  1.00 10.00           C\n"
        )
        self.window.study_pathway.setCurrentIndex(
            self.window.study_pathway.findData("control")
        )
        self.window.input_pdb.setText(str(complex_path))
        self.window.output_directory.setText(str(self.root / "control-study"))
        self.window.detect_bound_ligands(quiet=True)
        self.assertEqual(self.window.study_setup_panel.ligand_identity()["resname"], "LIG")
        self.assertIn("control", self.window.start_preparation_button.text().lower())
        self.window.start_preparation_button.click()
        self.wait_for(lambda state: state.workflow_data.get("latest_control_status") == "approved")
        state = self.store.load("journey")
        self.assertEqual(state.workflow_data["study_setup"]["pathway"], "control")
        self.assertEqual(state.jobs[-1].stage, "control_validation")
        self.assertTrue(any(item.kind == "protocol_bundle" for item in state.artifacts))
        self.assertIn("validated", self.window.next_required_action.text().lower())
        ligands = self.root / "library.sdf"
        ligands.write_text("library compound\n$$$$\n")
        self.window.screen_ligands.setText(str(ligands))
        self.window.screen_output.setText(str(self.root / "validated-screen"))
        self.window.preview_screening()
        self.assertIn("1 sequential docking jobs", self.window.screening_status.text())
        self.assertTrue(self.window.start_screening_button.isEnabled())
        self.window.start_screening()
        self.wait_for(lambda latest: latest.workflow_data.get("latest_screening_status") == "completed")
        self.reopen()
        self.assertEqual(self.window.study_pathway.currentData(), "control")
        self.assertEqual(self.window.study_setup_panel.ligand_identity()["resname"], "LIG")
        self.assertFalse(self.window.study_pathway.isEnabled())
        self.assertFalse(self.window.start_preparation_button.isEnabled())


    def test_widgets_complete_and_recover_the_single_run(self):
        work = self.root / "work"
        self.window.show()
        self.application.processEvents()
        self.window.input_pdb.setText(str(self.input))
        self.window.output_directory.setText(str(work))
        self.assertTrue(self.window.start_preparation_button.isEnabled())
        self.window.start_preparation_button.click()
        self.assertTrue(self.store.load("journey").jobs)
        self.wait_for(lambda state: bool(state.pending_decisions))
        retained_setup = self.store.load("journey").workflow_data["study_setup"]
        self.assertEqual(retained_setup["input_pdb"], str(self.input.resolve()))
        self.assertEqual(retained_setup["working_directory"], str(work.resolve()))
        self.assertEqual(retained_setup["site_mode"], "pockets")
        self.assertFalse(self.window.input_pdb.isEnabled())
        self.assertFalse(self.window.start_preparation_button.isEnabled())
        self.assertIn("Scientific decision required", self.window.next_required_action.text())

        self.reopen()
        self.assertEqual(self.window.input_pdb.text(), str(self.input.resolve()))
        self.assertEqual(self.window.output_directory.text(), str(work.resolve()))
        self.assertTrue(self.window.study_setup_panel.isEnabled())
        self.assertFalse(self.window.study_setup_panel.lock_notice.isHidden())
        self.window.candidates.selectRow(0)
        self.window.rationale.setText("Selected after reviewing retained pocket evidence")
        self.window.approve_button.click()
        self.assertEqual(self.store.load("journey").selected_pocket_ids, ["P1"])

        final = self.root / "final"
        self.window.final_output_directory.setText(str(final))
        self.window.exploratory_approval.setChecked(True)
        self.window.finalize_button.click()
        self.wait_for(lambda state: any(a.kind == "protocol_bundle" for a in state.artifacts))
        self.assertIn("Protocol finalized", self.window.next_required_action.text())

        self.reopen()
        ligands = self.root / "ligands.sdf"
        ligands.write_text("ligand\n$$$$\n")
        self.window.screen_ligands.setText(str(ligands))
        self.window.screen_output.setText(str(self.root / "screen"))
        self.window.refresh()
        self.assertTrue(self.window.preview_screening_button.isEnabled())
        self.window.preview_screening_button.click()
        self.window.screen_exploratory_approval.setChecked(True)
        self.assertTrue(self.window.start_screening_button.isEnabled(), self.window.screening_status.text())
        self.window.start_screening_button.click()
        self.wait_for(lambda state: bool(state.workflow_data.get("latest_screening_output")))

        self.reopen()
        self.assertIn("Screening complete", self.window.next_required_action.text())
        self.assertTrue(self.window.workflow_navigation.item(5).text().startswith("✓"))
        kinds = {artifact.kind for artifact in self.store.load("journey").artifacts}
        self.assertTrue({
            "pocket_evidence", "final_report", "protocol_bundle", "screening_report",
        } <= kinds)

    def test_mmcif_can_be_selected_detected_prepared_and_reopened(self):
        from tests.test_structure_input import MMCIF
        from docking_universal.gui.qt import QtWidgets

        source = self.root / "Target.cif"
        source.write_text(MMCIF)
        with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(source), "")):
            self.window.choose_input_pdb()
        self.assertEqual(self.window.input_pdb.text(), str(source))
        self.assertIn("monomeric", self.window.study_setup_panel.deposited_evidence.text())
        self.assertIn("LIG", self.window.study_setup_panel.deposited_evidence.text())
        self.assertTrue(self.window.study_setup_panel.deposited_evidence_details.isEnabled())
        self.window.site_mode.setCurrentIndex(1)
        labels = self.window.detect_bound_ligands()
        self.assertEqual(len(labels), 1)
        self.assertIn("LIG", labels[0])
        self.assertEqual(self.window.study_setup_panel.ligand_identity()["chain_id"], "B")
        self.window.site_mode.setCurrentIndex(0)
        work = self.root / "mmcif-work"
        self.window.output_directory.setText(str(work))
        self.window.start_preparation_button.click()
        self.wait_for(lambda state: bool(state.pending_decisions))
        state = self.store.load("journey")
        setup = state.workflow_data["study_setup"]
        self.assertEqual(setup["input_structure_format"], "mmcif")
        self.assertEqual(Path(setup["input_structure"]).read_bytes(), source.read_bytes())
        self.assertEqual(setup["biological_assemblies"][0]["id"], "1")
        self.assertTrue(setup["legacy_pdb_derived"])
        self.assertEqual(Path(setup["input_pdb"]).suffix, ".pdb")
        self.assertTrue(Path(setup["structure_input_metadata"]).is_file())
        self.reopen()
        self.assertEqual(self.window.input_pdb.text(), setup["input_structure"])
        self.assertIn("read-only", self.window.study_setup_panel.lock_notice.text())
        self.assertIn("LIG", self.window.study_setup_panel.deposited_evidence.text())


if __name__ == "__main__":
    unittest.main()
