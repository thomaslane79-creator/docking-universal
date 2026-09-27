import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docking_universal.application import StudyController
from docking_universal.gui.session import ActiveStudySession, QT_IMPORT_ERROR, StudySelection
from docking_universal.gui.desktop import StudyWindow
from docking_universal.models import ArtifactRecord, Job, JobStatus
from docking_universal.state import JsonStudyStore


@unittest.skipIf(QT_IMPORT_ERROR is not None, "selected Qt 5 binding is unavailable")
class ActiveStudySessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from docking_universal.gui.qt import QtWidgets
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = JsonStudyStore(self.root / "runs")
        StudyController(self.store).create_study("study", "Shared study")
        self.session = ActiveStudySession.shared(self.store, "study")

    def tearDown(self):
        self.temporary.cleanup()

    def test_shared_factory_returns_one_session_for_the_study(self):
        other_store = JsonStudyStore(self.root / "runs")
        self.assertIs(self.session, ActiveStudySession.shared(other_store, "study"))

    def test_selection_is_shared_but_never_rewrites_scientific_state(self):
        before = self.store.path_for("study").read_bytes()
        observed = []
        self.session.selectionChanged.connect(observed.append)
        compound = self.root / "screen/compounds/ligand"
        analysis = compound / "pose_analysis"

        self.session.select_pose(compound, analysis, 2, 7, site="primary site")

        self.assertEqual(self.session.selection.pose_id, 7)
        self.assertEqual(self.session.selection.cluster_id, 2)
        self.assertEqual(observed[-1], self.session.selection)
        self.assertEqual(self.store.path_for("study").read_bytes(), before)
        self.session.select_compound(compound)
        self.assertEqual(
            self.session.selection,
            StudySelection(compound=str(compound.resolve())),
        )

    def test_new_revision_emits_state_artifact_and_operation_changes(self):
        states, artifacts, operations = [], [], []
        self.session.studyChanged.connect(states.append)
        self.session.artifactsChanged.connect(artifacts.append)
        self.session.operationChanged.connect(operations.append)
        artifact = self.root / "result.json"
        artifact.write_text(json.dumps({"ok": True}))
        state = self.store.load("study")
        state.artifacts.append(ArtifactRecord("result", "result", str(artifact)))
        state.jobs.append(Job("job", "screening", JobStatus.RUNNING))
        self.store.save(state)

        self.assertTrue(self.session.refresh())
        self.assertEqual(states[-1].revision, self.store.load("study").revision)
        self.assertEqual(artifacts[-1][0].id, "result")
        self.assertEqual(operations[-1].stage, "screening")
        self.assertFalse(self.session.refresh())

    def test_artifact_queries_are_typed_and_can_require_existing_files(self):
        existing = self.root / "report.pdf"
        existing.write_bytes(b"%PDF-1.4\n%%EOF\n")
        state = self.store.load("study")
        state.artifacts.extend((
            ArtifactRecord("report", "screening_report", str(existing)),
            ArtifactRecord("missing", "screening_report", str(self.root / "missing.pdf")),
            ArtifactRecord("other", "log", str(self.root / "run.log")),
        ))
        self.store.save(state)
        self.session.refresh()

        self.assertEqual(
            [item.id for item in self.session.artifacts("screening_report")],
            ["report", "missing"],
        )
        self.assertEqual(
            [item.id for item in self.session.artifacts("screening_report", existing_only=True)],
            ["report"],
        )

    def test_viewer_lifecycle_is_shared_and_rejects_unknown_states(self):
        observed = []
        self.session.viewerChanged.connect(observed.append)
        self.session.set_viewer_state(
            connected=False, lifecycle="connecting", detail="Opening PyMOL",
        )
        self.session.set_viewer_state(
            connected=False, lifecycle="failed", detail="PyMOL exited", error="exit 1",
        )
        self.assertEqual([item.lifecycle for item in observed], ["connecting", "failed"])
        self.assertEqual(self.session.viewer.error, "exit 1")
        with self.assertRaisesRegex(ValueError, "Unknown viewer lifecycle"):
            self.session.set_viewer_state(connected=False, lifecycle="unknown")

    def test_scientific_detail_preference_is_shared_but_not_persisted_as_science(self):
        before = self.store.path_for("study").read_bytes()
        observed = []
        self.session.detailChanged.connect(observed.append)
        self.session.set_detail_level("technical")
        self.assertEqual(self.session.detail_level, "technical")
        self.assertEqual(observed, ["technical"])
        self.assertEqual(self.store.path_for("study").read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "Unknown scientific detail"):
            self.session.set_detail_level("hidden")

    def test_two_windows_share_compound_selection_without_state_write(self):
        from docking_universal.gui.qt import QtCore, QtGui

        compound = self.root / "screen/compounds/ligand"
        analysis = compound / "pose_analysis"
        interactions = analysis / "cluster_002/interactions"
        cache = analysis / "pose_interactions/pose_0001"
        interactions.mkdir(parents=True)
        cache.mkdir(parents=True)
        manifest = compound / "screen_manifest.json"
        manifest.write_text(json.dumps({"completion_status": "retained"}))
        (analysis / "cluster_summary.csv").write_text(
            "energy_rank,cluster_id,best_energy_kcal_per_mol,pose_count\n1,2,-9.2,12\n"
        )
        (analysis / "pose_inventory.csv").write_text(
            "pose_id,cluster_id,selected_cluster,seed,conformer,model,energy_kcal_per_mol,source\n"
            "1,2,yes,101,state_a,1,-9.2,poses.pdbqt\n"
        )
        (analysis / "all_poses.sdf").write_text("retained poses\n")
        (analysis / "receptor.pdb").write_text("END\n")
        cluster_diagram = interactions / "representative_plip2d.png"
        pose_diagram = cache / "interaction_diagram.png"
        (cache / "pose.sdf").write_text("pose\n")
        for diagram in (cluster_diagram, pose_diagram):
            image = QtGui.QImage(40, 30, QtGui.QImage.Format_RGB32)
            image.fill(QtGui.QColor("white"))
            self.assertTrue(image.save(str(diagram)))
        state = self.store.load("study")
        state.artifacts.extend((
            ArtifactRecord("manifest", "screening_compound_manifest", str(manifest)),
            ArtifactRecord("cluster-view", "screening_interaction_diagram", str(cluster_diagram)),
        ))
        self.store.save(state)
        settings_a = QtCore.QSettings(str(self.root / "a.ini"), QtCore.QSettings.IniFormat)
        settings_b = QtCore.QSettings(str(self.root / "b.ini"), QtCore.QSettings.IniFormat)
        window_a = StudyWindow(self.store, "study", settings=settings_a)
        window_b = StudyWindow(self.store, "study", settings=settings_b)
        try:
            self.assertIs(window_a.session, window_b.session)
            before = self.store.path_for("study").read_bytes()

            window_a.screening_results.selectRow(0)
            self.application.processEvents()

            selected = window_b.screening_results.selectionModel().selectedRows()
            self.assertEqual(len(selected), 1)
            self.assertEqual(window_b._selected_screening_compound(), compound)
            self.assertEqual(window_a.session.selection.cluster_id, 2)

            window_a.session.select_pose(compound, analysis, 2, 1, site="primary site")
            self.application.processEvents()

            self.assertEqual(window_a.session.selection.pose_id, 1)
            self.assertEqual(window_b.pose_review_mode.currentData(), "all_poses")
            selected_pose = window_b.pose_results.selectionModel().selectedRows()
            self.assertEqual(len(selected_pose), 1)
            self.assertEqual(window_b.pose_results.item(selected_pose[0].row(), 0).text(), "1")
            self.assertEqual(self.store.path_for("study").read_bytes(), before)
        finally:
            window_a.close()
            window_b.close()


if __name__ == "__main__":
    unittest.main()
