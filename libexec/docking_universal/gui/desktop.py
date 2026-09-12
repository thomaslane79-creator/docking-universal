"""Dockable read-only workspace for one persisted scientific study."""

from __future__ import annotations

from pathlib import Path

from ..events import ScientificDetail
from ..state import JsonStudyStore, StudyState

try:
    from PyQt5 import QtCore, QtGui, QtWidgets
except ImportError as exc:  # pragma: no cover - diagnosed by runtime inventory
    QtCore = QtGui = QtWidgets = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None


def require_qt() -> None:
    if QtWidgets is None:
        raise RuntimeError(f"The selected PyQt5 desktop runtime is unavailable: {QT_IMPORT_ERROR}")


if QtWidgets is not None:
    class StudyWindow(QtWidgets.QMainWindow):
        """Multiple instances present the same store; none owns scientific state."""

        def __init__(
            self, store: JsonStudyStore, study_id: str, *, settings=None,
            host_client=None, viewer_coordinator=None,
        ):
            super().__init__()
            self.store = store
            self.study_id = study_id
            self.settings = settings or QtCore.QSettings("DockingUniversal", "Desktop")
            self.host_client = host_client
            self.viewer_coordinator = viewer_coordinator
            self._exit_after_cancel = False
            self.setObjectName("docking_universal_study_window")
            self.setWindowTitle("Docking Universal — Scientific Decision Support")
            self.resize(1280, 820)
            self._build()
            self.refresh()
            geometry = self.settings.value("window/geometry")
            layout = self.settings.value("window/layout")
            if geometry is not None:
                self.restoreGeometry(geometry)
            if layout is not None:
                self.restoreState(layout)

        def _build(self) -> None:
            self.automation_banner = QtWidgets.QLabel("AUTOMATED SCIENTIFIC DECISIONS")
            self.automation_banner.setObjectName("automation_banner")
            self.automation_banner.setAlignment(QtCore.Qt.AlignCenter)
            self.automation_banner.setStyleSheet("background:#8b1e1e;color:white;font-weight:bold;padding:8px")
            self.decision_banner = QtWidgets.QLabel()
            self.decision_banner.setObjectName("decision_banner")
            self.decision_banner.setWordWrap(True)
            self.decision_banner.setStyleSheet("background:#fff1b8;color:#332600;padding:8px")
            self.summary = QtWidgets.QLabel()
            self.summary.setWordWrap(True)
            self.candidates = QtWidgets.QTableWidget(0, 4)
            self.candidates.setHorizontalHeaderLabels(("Candidate", "Rank", "Summary", "Evidence"))
            self.candidates.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            self.candidates.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
            self.candidates.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            central = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(central)
            layout.addWidget(self.automation_banner)
            layout.addWidget(self.decision_banner)
            layout.addWidget(self.summary)
            viewer_row = QtWidgets.QHBoxLayout()
            self.viewer_button = QtWidgets.QPushButton("Open required PyMOL review")
            self.viewer_button.setObjectName("open_pymol_review_button")
            self.viewer_button.clicked.connect(self.open_visual_review)
            self.viewer_status = QtWidgets.QLabel("PyMOL review has not been opened")
            viewer_row.addWidget(self.viewer_button)
            viewer_row.addWidget(self.viewer_status, 1)
            layout.addLayout(viewer_row)
            layout.addWidget(self.candidates, 1)
            approval_row = QtWidgets.QHBoxLayout()
            self.rationale = QtWidgets.QLineEdit()
            self.rationale.setPlaceholderText("Optional scientific rationale for the audit trail")
            self.approve_button = QtWidgets.QPushButton("Approve selected docking region(s)")
            self.approve_button.setObjectName("approve_regions_button")
            self.approve_button.clicked.connect(self.approve_selected_regions)
            approval_row.addWidget(self.rationale, 1)
            approval_row.addWidget(self.approve_button)
            layout.addLayout(approval_row)
            self.setCentralWidget(central)

            toolbar = self.addToolBar("View")
            toolbar.setObjectName("view_toolbar")
            toolbar.addWidget(QtWidgets.QLabel("Scientific Workflow Detail: "))
            self.detail = QtWidgets.QComboBox()
            self.detail.addItems([item.value.title() for item in ScientificDetail])
            self.detail.setCurrentText("Guided")
            self.detail.currentTextChanged.connect(self._render_events)
            toolbar.addWidget(self.detail)
            full_screen = toolbar.addAction("Full Screen")
            full_screen.setShortcut("F11")
            full_screen.triggered.connect(self.toggle_full_screen)

            self.event_view = QtWidgets.QTextBrowser()
            self.log_view = QtWidgets.QPlainTextEdit()
            self.log_view.setReadOnly(True)
            self.report_list = QtWidgets.QListWidget()
            self.report_list.itemDoubleClicked.connect(self.open_artifact)
            self.selection_view = QtWidgets.QTreeWidget()
            self.selection_view.setHeaderLabels(("Proposed selection", "Identity"))
            self._dock("Scientific Workflow Detail", self.event_view, QtCore.Qt.RightDockWidgetArea, "workflow_detail_dock")
            self._dock("Selections", self.selection_view, QtCore.Qt.RightDockWidgetArea, "selection_dock")
            self._dock("Complete Logs", self.log_view, QtCore.Qt.BottomDockWidgetArea, "logs_dock")
            self._dock("Reports and Artifacts", self.report_list, QtCore.Qt.BottomDockWidgetArea, "reports_dock")
            self._build_setup_dock()
            self.statusBar().showMessage("Selections are proposals until explicitly approved through the application host")
            self.refresh_timer = QtCore.QTimer(self)
            self.refresh_timer.setInterval(1000)
            self.refresh_timer.timeout.connect(self.refresh)
            self.refresh_timer.start()

        def _build_setup_dock(self) -> None:
            panel = QtWidgets.QWidget()
            form = QtWidgets.QFormLayout(panel)
            self.input_pdb = QtWidgets.QLineEdit()
            self.output_directory = QtWidgets.QLineEdit()
            self.site_mode = QtWidgets.QComboBox()
            self.site_mode.addItem("Predicted pockets", "pockets")
            self.site_mode.addItem("Selected bound ligand", "ligand")
            self.site_mode.currentIndexChanged.connect(self._update_site_controls)
            self.ligand_resname = QtWidgets.QLineEdit()
            self.ligand_resname.setPlaceholderText("Required for ligand mode, e.g. LIG")
            input_row = QtWidgets.QWidget()
            input_layout = QtWidgets.QHBoxLayout(input_row)
            input_layout.setContentsMargins(0, 0, 0, 0)
            input_layout.addWidget(self.input_pdb)
            input_button = QtWidgets.QPushButton("Browse…")
            input_button.clicked.connect(self.choose_input_pdb)
            input_layout.addWidget(input_button)
            output_row = QtWidgets.QWidget()
            output_layout = QtWidgets.QHBoxLayout(output_row)
            output_layout.setContentsMargins(0, 0, 0, 0)
            output_layout.addWidget(self.output_directory)
            output_button = QtWidgets.QPushButton("Browse…")
            output_button.clicked.connect(self.choose_output_directory)
            output_layout.addWidget(output_button)
            form.addRow("Receptor PDB", input_row)
            form.addRow("Study output directory", output_row)
            form.addRow("Site definition", self.site_mode)
            form.addRow("Bound ligand residue", self.ligand_resname)
            buttons = QtWidgets.QHBoxLayout()
            self.start_preparation_button = QtWidgets.QPushButton("Prepare receptor and detect pockets")
            self.start_preparation_button.setObjectName("start_preparation_button")
            self.start_preparation_button.clicked.connect(self.start_preparation)
            self.cancel_job_button = QtWidgets.QPushButton("Cancel active stage")
            self.cancel_job_button.setObjectName("cancel_job_button")
            self.cancel_job_button.clicked.connect(self.cancel_active_job)
            buttons.addWidget(self.start_preparation_button)
            buttons.addWidget(self.cancel_job_button)
            form.addRow(buttons)
            self._dock("Study Setup", panel, QtCore.Qt.LeftDockWidgetArea, "study_setup_dock")
            self._update_site_controls()

        def _dock(self, title, widget, area, name):
            dock = QtWidgets.QDockWidget(title, self)
            dock.setObjectName(name)
            dock.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
            dock.setFeatures(
                QtWidgets.QDockWidget.DockWidgetClosable
                | QtWidgets.QDockWidget.DockWidgetMovable
                | QtWidgets.QDockWidget.DockWidgetFloatable
            )
            dock.setWidget(widget)
            self.addDockWidget(area, dock)
            return dock

        def refresh(self) -> None:
            self.state = self.store.load(self.study_id)
            state = self.state
            self.summary.setText(
                f"Study: {state.name}    Workflow: {state.workflow}    "
                f"Status: {state.completion_status.value}    Revision: {state.revision}"
            )
            policy = state.workflow_data.get("active_automation_policy", {})
            self.automation_banner.setVisible(bool(policy.get("enabled")))
            pending = state.pending_decisions
            self.decision_banner.setVisible(bool(pending))
            if pending:
                decision = pending[0]
                self.decision_banner.setText(
                    f"DECISION REQUIRED: {decision.prompt}\n{decision.why_stopped}\n"
                    + " ".join(decision.consequences)
                )
            self.approve_button.setEnabled(bool(self.host_client and pending))
            self.viewer_button.setEnabled(self.viewer_coordinator is not None)
            if self.viewer_coordinator is None:
                self.viewer_status.setText("Required PyMOL adapter is not configured")
            active = state.active_job
            preparation_complete = any(
                job.stage == "preparation_and_pocket_detection" and job.status.value == "completed"
                for job in state.jobs
            )
            self.start_preparation_button.setEnabled(bool(
                self.host_client and not active and not pending and not preparation_complete
            ))
            self.cancel_job_button.setEnabled(bool(
                self.host_client and active and active.status.value == "running"
            ))
            self._render_candidates(state)
            self._render_artifacts(state)
            self._render_events()
            if self._exit_after_cancel and not active:
                self._exit_after_cancel = False
                QtCore.QTimer.singleShot(0, self.close)

        def _update_site_controls(self) -> None:
            ligand_mode = self.site_mode.currentData() == "ligand"
            self.ligand_resname.setEnabled(ligand_mode)

        def approve_selected_regions(self) -> None:
            if not self.host_client:
                return
            pending = [item for item in self.state.pending_decisions if item.kind == "select_pockets"]
            rows = sorted({index.row() for index in self.candidates.selectionModel().selectedRows()})
            if not pending or not rows:
                QtWidgets.QMessageBox.warning(self, "Selection required", "Select one or more docking regions first.")
                return
            candidates = self.state.workflow_data.get("pocket_candidates", [])
            selections = [str(candidates[row]["id"]) for row in rows]
            try:
                self.host_client.request(
                    self.study_id, "resolve_decision",
                    {
                        "decision_id": pending[0].id, "selections": selections,
                        "actor": "desktop-user", "rationale": self.rationale.text().strip() or None,
                    },
                    expected_revision=self.state.revision,
                )
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "Approval rejected", str(exc))
                self.refresh()
                return
            self.refresh()

        def choose_input_pdb(self) -> None:
            path, _filter = QtWidgets.QFileDialog.getOpenFileName(
                self, "Choose receptor structure", "", "Protein Data Bank (*.pdb)",
            )
            if path:
                self.input_pdb.setText(path)

        def choose_output_directory(self) -> None:
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose study output directory")
            if path:
                self.output_directory.setText(path)

        def start_preparation(self) -> None:
            if not self.host_client:
                return
            input_text = self.input_pdb.text().strip()
            output_text = self.output_directory.text().strip()
            if not input_text or not Path(input_text).is_file() or Path(input_text).suffix.lower() != ".pdb":
                QtWidgets.QMessageBox.warning(
                    self, "Receptor required", "Choose an existing receptor PDB file before starting.",
                )
                return
            if not output_text:
                QtWidgets.QMessageBox.warning(
                    self, "Output directory required", "Choose a study output directory before starting.",
                )
                return
            if self.site_mode.currentData() == "ligand" and not self.ligand_resname.text().strip():
                QtWidgets.QMessageBox.warning(
                    self, "Ligand required", "Enter the selected bound-ligand residue name.",
                )
                return
            payload = {
                "input_pdb": input_text,
                "working_directory": output_text,
                "site_mode": self.site_mode.currentData(),
                "ligand_resname": self.ligand_resname.text().strip() or None,
                "feedback_level": self.detail.currentText().lower().replace("teaching", "verbose").replace("technical", "verbose"),
                "cavity_mode": 1,
                "max_pockets": 3,
                "center_mode": "deepest",
                "centroid_mode": 1,
            }
            try:
                self.host_client.request(
                    self.study_id, "start_receptor_preparation", payload,
                    expected_revision=self.state.revision,
                )
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "Preparation could not start", str(exc))
            self.refresh()

        def cancel_active_job(self) -> None:
            if not self.host_client:
                return
            try:
                self.host_client.request(
                    self.study_id, "cancel_active_job", {}, expected_revision=self.state.revision,
                )
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "Cancellation could not be requested", str(exc))
            self.refresh()

        def open_visual_review(self) -> None:
            if not self.viewer_coordinator:
                return
            try:
                self.viewer_coordinator.open(self.state)
            except Exception as exc:
                self.viewer_status.setText(f"PyMOL review unavailable: {exc}")
                QtWidgets.QMessageBox.critical(self, "PyMOL review unavailable", str(exc))
                return
            self.viewer_status.setText("PyMOL review connected — visual changes do not imply approval")

        def _candidate_highlight_changed(self) -> None:
            if not self.viewer_coordinator or not self.viewer_coordinator.connected:
                return
            rows = self.candidates.selectionModel().selectedRows()
            if not rows:
                return
            candidates = self.state.workflow_data.get("pocket_candidates", [])
            if rows[0].row() >= len(candidates):
                return
            try:
                self.viewer_coordinator.show_candidate(self.state, str(candidates[rows[0].row()]["id"]))
            except Exception as exc:
                self.viewer_status.setText(f"Candidate display failed: {exc}")

        def _render_candidates(self, state: StudyState) -> None:
            values = state.workflow_data.get("pocket_candidates", [])
            self.candidates.setRowCount(len(values))
            for row, candidate in enumerate(values):
                evidence = candidate.get("evidence", {})
                columns = (
                    candidate.get("label", candidate.get("id", "")), candidate.get("rank", ""),
                    candidate.get("summary", ""), ", ".join(f"{key}={value}" for key, value in sorted(evidence.items())),
                )
                for column, value in enumerate(columns):
                    self.candidates.setItem(row, column, QtWidgets.QTableWidgetItem(str(value)))
            self.candidates.resizeColumnsToContents()
            try:
                self.candidates.itemSelectionChanged.disconnect(self._candidate_highlight_changed)
            except TypeError:
                pass
            self.candidates.itemSelectionChanged.connect(self._candidate_highlight_changed)

        def _render_artifacts(self, state: StudyState) -> None:
            self.report_list.clear()
            logs = []
            for artifact in state.artifacts:
                item = QtWidgets.QListWidgetItem(f"{artifact.kind}: {artifact.path}")
                item.setData(QtCore.Qt.UserRole, artifact.path)
                item.setToolTip("Double-click to open this retained artifact")
                self.report_list.addItem(item)
                if "log" in artifact.kind and Path(artifact.path).is_file():
                    logs.append(f"[{artifact.description or artifact.kind}]\n{Path(artifact.path).read_text(errors='replace')}")
            # The widget is bounded; full raw logs remain in their artifacts.
            self.log_view.setPlainText("\n\n".join(logs)[-200_000:])

        def open_artifact(self, item) -> None:
            path = Path(str(item.data(QtCore.Qt.UserRole) or ""))
            if not path.is_file():
                QtWidgets.QMessageBox.warning(self, "Artifact unavailable", f"Artifact does not exist: {path}")
                return
            if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path.resolve()))):
                QtWidgets.QMessageBox.warning(self, "Artifact could not be opened", str(path))

        def _render_events(self, *_args) -> None:
            if not hasattr(self, "state"):
                return
            detail = ScientificDetail(self.detail.currentText().lower())
            blocks = []
            for event in self.state.events:
                value = event.presented(detail)
                lines = [f"{value['sequence']}. {value['message']}"]
                for key in ("explanation", "teaching", "technical", "data"):
                    if value.get(key):
                        lines.append(str(value[key]))
                blocks.append("\n".join(lines))
            self.event_view.setPlainText("\n\n".join(blocks))

        def toggle_full_screen(self) -> None:
            self.showNormal() if self.isFullScreen() else self.showFullScreen()

        def closeEvent(self, event) -> None:
            self.settings.setValue("window/geometry", self.saveGeometry())
            self.settings.setValue("window/layout", self.saveState())
            try:
                latest = self.store.load(self.study_id)
                active = latest.active_job
            except (FileNotFoundError, ValueError):
                latest = None
                active = None
            if active and active.status.value == "running":
                if self._exit_after_cancel:
                    event.ignore()
                    return
                message = QtWidgets.QMessageBox(self)
                message.setIcon(QtWidgets.QMessageBox.Warning)
                message.setWindowTitle("Scientific stage is still running")
                message.setText("Docking Universal cannot continue scientific work in the background yet.")
                message.setInformativeText("Cancel the active stage and exit, or return to the run.")
                cancel_and_exit = message.addButton(
                    "Cancel stage and exit", QtWidgets.QMessageBox.DestructiveRole,
                )
                return_to_run = message.addButton(
                    "Return to run", QtWidgets.QMessageBox.RejectRole,
                )
                message.setDefaultButton(return_to_run)
                message.exec_()
                if message.clickedButton() is not cancel_and_exit:
                    event.ignore()
                    return
                try:
                    self.host_client.request(
                        self.study_id, "cancel_active_job", {}, expected_revision=latest.revision,
                    )
                except Exception as exc:
                    QtWidgets.QMessageBox.critical(self, "Cancellation could not be requested", str(exc))
                    event.ignore()
                    return
                self._exit_after_cancel = True
                self.statusBar().showMessage("Cancelling the active stage before exit…")
                event.ignore()
                return
            super().closeEvent(event)
else:
    class StudyWindow:  # pragma: no cover
        def __init__(self, *_args, **_kwargs):
            require_qt()
