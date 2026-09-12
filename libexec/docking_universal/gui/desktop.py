"""Dockable read-only workspace for one persisted scientific study."""

from __future__ import annotations

from pathlib import Path

from ..events import ScientificDetail
from ..state import JsonStudyStore, StudyState

try:
    from PyQt5 import QtCore, QtWidgets
except ImportError as exc:  # pragma: no cover - diagnosed by runtime inventory
    QtCore = QtWidgets = None
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
            self.selection_view = QtWidgets.QTreeWidget()
            self.selection_view.setHeaderLabels(("Proposed selection", "Identity"))
            self._dock("Scientific Workflow Detail", self.event_view, QtCore.Qt.RightDockWidgetArea, "workflow_detail_dock")
            self._dock("Selections", self.selection_view, QtCore.Qt.RightDockWidgetArea, "selection_dock")
            self._dock("Complete Logs", self.log_view, QtCore.Qt.BottomDockWidgetArea, "logs_dock")
            self._dock("Reports and Artifacts", self.report_list, QtCore.Qt.BottomDockWidgetArea, "reports_dock")
            self.statusBar().showMessage("Selections are proposals until explicitly approved through the application host")

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
            self._render_candidates(state)
            self._render_artifacts(state)
            self._render_events()

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
                self.report_list.addItem(f"{artifact.kind}: {artifact.path}")
                if "log" in artifact.kind and Path(artifact.path).is_file():
                    logs.append(f"[{artifact.description or artifact.kind}]\n{Path(artifact.path).read_text(errors='replace')}")
            # The widget is bounded; full raw logs remain in their artifacts.
            self.log_view.setPlainText("\n\n".join(logs)[-200_000:])

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
            super().closeEvent(event)
else:
    class StudyWindow:  # pragma: no cover
        def __init__(self, *_args, **_kwargs):
            require_qt()
