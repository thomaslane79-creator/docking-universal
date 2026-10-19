"""Dockable read-only workspace for one persisted scientific study."""

from __future__ import annotations

import json
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from ..runtime_inventory import discover_poseedit_runtime
from ..state import JsonStudyStore, StudyState

try:
    from .qt import QtCore, QtGui, QtWidgets
    from .session import ActiveStudySession
    from .results_review import ResultsReviewPanel
    from .results_model import ResultsReviewModel
    from .results_controller import ResultsReviewController
    from .workflow_panels import (
        PreparationProgressPanel, ProtocolFinalizationPanel, ScreeningSetupPanel,
        StudySetupPanel,
    )
    from .workflow_navigation import WorkflowNavigationController
    from .scientific_detail import ScientificDetailPanel
    from .workspace_controller import WorkspaceWindowController
    from .application_host_controller import ApplicationHostController
    from .pocket_evidence import PocketEvidencePanel, conformation_summary
    from .pocket_plot import PocketScorePlot
    from .navigation_table import NavigationTable
    from .decision_dialog import DecisionDialog
    from .linked_pose_review import LinkedPosePanel, pose_view, control_view, write_comparison_report
    from .cluster_contacts import ClusterContactControls
    from .image_export import ImageExport, save_image_button, pymol_export, diagram_export, export_dialog
except ImportError as exc:  # pragma: no cover - diagnosed by runtime inventory
    QtCore = QtGui = QtWidgets = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None


def require_qt() -> None:
    if QtWidgets is None:
        raise RuntimeError(f"The selected PyQt6 desktop runtime is unavailable: {QT_IMPORT_ERROR}")


if QtWidgets is not None:
    class StudyWindow(QtWidgets.QMainWindow):
        studySwitchRequested = QtCore.pyqtSignal(str)
        def _send_windows_back(self) -> None:
            """Lower all visible application windows before handing focus to PyMOL."""
            for window in QtWidgets.QApplication.topLevelWidgets():
                if window.isVisible():
                    window.lower()

        def _uses_companion_viewer(self) -> bool:
            return bool(
                self.viewer_coordinator is not None
                and getattr(self.viewer_coordinator, "backend_kind", "companion") == "companion"
            )

        def _show_embedded_viewer(self) -> None:
            if getattr(self, "_paired_interaction_window", None) is not None:
                return
            if self.viewer_widget is not None and self.live_page is not None:
                detached = getattr(self, "_detached_structure_window", None)
                if detached is not None:
                    # The live viewport is already in this window. Never pull
                    # the main application over it during study navigation.
                    return
                if self.review_tabs.currentWidget() is not self.live_page:
                    self.review_tabs.setCurrentWidget(self.live_page)
                # In-window navigation already has focus. Re-activating the
                # native window on every row click can disturb macOS stacking.
                if not self.isActiveWindow():
                    self.raise_()
                    self.activateWindow()
        """Multiple instances present the same store; none owns scientific state."""

        WORKFLOW_RAIL_WIDTH = 235
        WORKFLOW_RAIL_MINIMUM_WIDTH = 200

        def __init__(
            self, store: JsonStudyStore, study_id: str, *, settings=None,
            host_client=None, viewer_coordinator=None, viewer_widget=None, session=None,
        ):
            super().__init__()
            self.store = store
            self.study_id = study_id
            self.session = session or ActiveStudySession.shared(store, study_id)
            if self.session.study_id != study_id:
                raise ValueError("ActiveStudySession study does not match this window")
            self.settings = settings or QtCore.QSettings("DockingUniversal", "Desktop")
            self.host_client = host_client
            self.host_controller = ApplicationHostController(
                study_id, lambda: self.host_client,
            )
            self.viewer_coordinator = viewer_coordinator
            self.viewer_widget = viewer_widget
            self._retained_setup_signature = None
            self._prepared_meeko_template_file = None
            if self.viewer_widget is not None and self.viewer_coordinator is None:
                raise ValueError("An embedded viewer widget requires a viewer coordinator")
            self._build_study_menu()
            self._exit_after_cancel = False
            self._current_interaction_diagram = None
            self._interaction_source_pixmap = None
            self._applying_session_selection = False
            self._workflow_phase = None
            self.poseedit_runtime = discover_poseedit_runtime()
            self.results_model = ResultsReviewModel()
            self.results_controller = ResultsReviewController(self.results_model)
            self.setObjectName("docking_universal_study_window")
            self.setWindowTitle("Docking Universal — Scientific Decision Support")
            self.resize(1280, 820)
            self.setMinimumSize(1100, 700)
            self._build()
            self._apply_runtime_capabilities()
            self._show_runtime_identity()
            self.workspace_controller = WorkspaceWindowController(
                self, self.settings, self._refresh_polled_state,
            )
            self.refresh_timer = self.workspace_controller.timer
            self.session.selectionChanged.connect(self._apply_session_selection)
            self.session.studyChanged.connect(self._schedule_session_refresh)
            self.session.viewerChanged.connect(self._apply_session_viewer_state)
            self.session.detailChanged.connect(self._apply_session_detail)
            self.refresh()
            self.workspace_controller.restore_layout()
            self.study_setup_dock.hide()
            self._update_stage_review_visibility()
            # Dense diagnostic surfaces never reopen automatically. They are
            # available from explicit toolbar actions when the user asks.
            self.workflow_detail_dock.hide()
            self.logs_dock.hide()
            self.reports_dock.hide()
            self.selection_dock.hide()
            self._restore_form_values()
            self._apply_runtime_capabilities()
            self.refresh()

        def _apply_runtime_capabilities(self) -> None:
            """Do not offer unaccepted Windows methods as if they were usable."""
            runtime = getattr(self.host_client, "runtime", {}) or {}
            if not runtime.get("native_scientific_preview"):
                return
            allowed = ((self.protocol_engine, runtime["supported_engines"]),
                       (self.control_engine, runtime["supported_engines"]),
                       (self.site_mode, runtime["supported_site_modes"]),
                       (self.pocket_engine, [*runtime["supported_pocket_engines"], "auto"]))
            for combo, values in allowed:
                for index in range(combo.count()):
                    # Keep retained choices visible when an older study opens;
                    # never relabel its engine as Vina by removing its item.
                    combo.model().item(index).setEnabled(combo.itemData(index) in values)
            panel = self.study_setup_panel
            panel.redock_ligand.setEnabled(False)
            panel.redock_ligand.setToolTip("Known-ligand control is awaiting native Windows acceptance; it is not silently replaced by exploratory docking.")
            panel.predict_with_ligand.setEnabled(False)
            # Preserve the serialized choice for read-only older-study review.
            index = self.study_pathway.findData("control")
            if index >= 0:
                self.study_pathway.model().item(index).setEnabled(False)
            panel.set_native_capabilities(runtime)

        def _show_runtime_identity(self) -> None:
            gui_version = QtCore.qVersion()
            host_runtime = getattr(self.host_client, "runtime", {}) or {}
            host_version = host_runtime.get("python_version", "unavailable")
            host_environment = host_runtime.get("conda_environment") or "explicit interpreter"
            viewer = self._viewer_runtime_label()
            self.runtime_status = QtWidgets.QLabel(
                f"GUI Qt {gui_version} · scientific host Python {host_version} "
                f"({host_environment}) · {viewer}"
            )
            self.runtime_status.setObjectName("runtime_identity_status")
            self.runtime_status.setToolTip(
                "The scientific host remains isolated from the GUI. The structural viewer "
                "may be embedded or use the companion fallback."
            )
            self.reconnect_services_button = QtWidgets.QPushButton("Reconnect scientific host")
            self.reconnect_services_button.setObjectName("reconnect_scientific_host_button")
            self.reconnect_services_button.clicked.connect(self.reconnect_scientific_host)
            self.reconnect_services_button.setVisible(False)
            self.statusBar().addPermanentWidget(self.reconnect_services_button)
            self.statusBar().addPermanentWidget(self.runtime_status)

        def _host_connected(self) -> bool:
            if self.host_client is None:
                return False
            return bool(getattr(self.host_client, "connected", True))

        def _viewer_runtime_label(self) -> str:
            if self.viewer_coordinator is None:
                return "structural viewer unavailable"
            name = getattr(self.viewer_coordinator, "backend_name", "PyMOL viewer")
            return f"{name} configured"

        def _refresh_host_lifecycle(self) -> None:
            if self.host_client is None:
                return
            failed = not self._host_connected()
            self.reconnect_services_button.setVisible(failed)
            if failed:
                self.runtime_status.setText(
                    "SCIENTIFIC HOST DISCONNECTED · the study is retained · reconnect to continue"
                )
                self.runtime_status.setStyleSheet(
                    "background:#8b1e1e;color:white;font-weight:bold;padding:4px"
                )
            else:
                self.runtime_status.setStyleSheet("")

        def reconnect_scientific_host(self) -> None:
            if self.host_client is None or not hasattr(self.host_client, "restart"):
                return
            self.reconnect_services_button.setEnabled(False)
            self.runtime_status.setText("Reconnecting the scientific application host…")
            QtWidgets.QApplication.processEvents()
            try:
                self.host_client.restart()
                self.session.refresh()
            except Exception as exc:
                self.runtime_status.setText(
                    f"SCIENTIFIC HOST RECONNECT FAILED · {exc}"
                )
                self.reconnect_services_button.setVisible(True)
                self.reconnect_services_button.setEnabled(True)
                return
            self.reconnect_services_button.setVisible(False)
            self.reconnect_services_button.setEnabled(True)
            self._show_connected_runtime_identity()
            self.refresh()

        def _show_connected_runtime_identity(self) -> None:
            self._apply_runtime_capabilities()
            host_runtime = getattr(self.host_client, "runtime", {}) or {}
            host_version = host_runtime.get("python_version", "unavailable")
            host_environment = host_runtime.get("conda_environment") or "explicit interpreter"
            viewer = self._viewer_runtime_label()
            self.runtime_status.setText(
                f"GUI Qt {QtCore.qVersion()} · scientific host Python {host_version} "
                f"({host_environment}) · {viewer}"
            )
            self.runtime_status.setStyleSheet("")

        def _build(self) -> None:
            self.automation_banner = QtWidgets.QLabel("AUTOMATED SCIENTIFIC DECISIONS")
            self.automation_banner.setObjectName("automation_banner")
            self.automation_banner.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.automation_banner.setStyleSheet("background:#8b1e1e;color:white;font-weight:bold;padding:8px")
            self.decision_banner = QtWidgets.QLabel()
            self.decision_banner.setObjectName("decision_banner")
            self.decision_banner.setWordWrap(True)
            self.decision_banner.setStyleSheet("background:#fff1b8;color:#332600;padding:8px")
            self.summary = QtWidgets.QLabel()
            self.summary.setWordWrap(True)
            self.feedback_card = QtWidgets.QFrame()
            self.feedback_card.setObjectName("scientific_feedback_card")
            feedback_layout = QtWidgets.QVBoxLayout(self.feedback_card)
            feedback_layout.setContentsMargins(12, 10, 12, 10)
            feedback_layout.setSpacing(4)
            self.feedback_heading = QtWidgets.QLabel("Scientific feedback")
            self.feedback_heading.setObjectName("scientific_feedback_heading")
            feedback_font = self.feedback_heading.font()
            feedback_font.setPointSize(feedback_font.pointSize() + 2)
            feedback_font.setBold(True)
            self.feedback_heading.setFont(feedback_font)
            self.feedback_text = QtWidgets.QLabel()
            self.feedback_text.setObjectName("scientific_feedback_text")
            self.feedback_text.setWordWrap(True)
            self.feedback_text.setTextInteractionFlags(
                QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
            )
            feedback_layout.addWidget(self.feedback_heading)
            feedback_layout.addWidget(self.feedback_text)
            self.running_indicator = QtWidgets.QProgressBar()
            self.running_indicator.setObjectName("central_running_indicator")
            self.running_indicator.setRange(0, 0)
            self.running_indicator.setTextVisible(False)
            self.running_indicator.setFixedHeight(22)
            self.running_indicator.setStyleSheet(
                "QProgressBar {background:#c9dff1;border:1px solid #2478bd;"
                "border-radius:4px;} QProgressBar::chunk {background:#2478bd;}"
            )
            self.running_indicator.hide()
            feedback_layout.addWidget(self.running_indicator)
            self.running_elapsed = QtWidgets.QLabel()
            self.running_elapsed.setObjectName("central_running_elapsed")
            self.running_elapsed.hide()
            feedback_layout.addWidget(self.running_elapsed)
            self.feedback_card.setStyleSheet(
                "QFrame#scientific_feedback_card { background:#eef5ff; "
                "border:1px solid #8bb7e8; border-radius:5px; }"
                "QFrame#scientific_feedback_card QLabel {color:#172b3a;background:transparent;}"
            )
            self.workspace_heading = QtWidgets.QLabel("Structural Review")
            self.workspace_heading.setObjectName("workspace_heading")
            heading_font = self.workspace_heading.font()
            heading_font.setPointSize(heading_font.pointSize() + 3)
            heading_font.setBold(True)
            self.workspace_heading.setFont(heading_font)
            self.workspace_context = QtWidgets.QLabel(
                "Review retained receptor, site, pose, and interaction evidence before making a decision."
            )
            self.workspace_context.setWordWrap(True)
            self.structural_view = QtWidgets.QLabel(
                "Interactive 3D scene\n\n"
                "Choose a retained scene in the Interactive structure tab. "
                "Viewing does not change approval."
            )
            self.structural_view.setObjectName("central_structural_review")
            self.structural_view.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.structural_view.setWordWrap(True)
            self.structural_view.setMinimumHeight(180)
            self.structural_view.setStyleSheet(
                "background:#14242f;color:#dbeaf0;border:1px solid #49616d;padding:18px"
            )
            self.review_tabs = QtWidgets.QTabWidget()
            self.review_tabs.setObjectName("central_review_modes")
            self.structure_scene_choice = QtWidgets.QComboBox()
            self.structure_scene_choice.setObjectName("structure_scene_choice")
            self.structure_scene_choice.setToolTip("Choose a retained interactive 3D scene")
            self.structure_scene_choice.currentIndexChanged.connect(self._structure_scene_changed)
            self.review_tabs.tabBar().hide()
            if self.viewer_widget is not None:
                self.live_page = QtWidgets.QWidget()
                self.live_layout = QtWidgets.QVBoxLayout(self.live_page)
                self.live_layout.setContentsMargins(0, 0, 0, 0)
                self.pose_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
                self.pose_split.setObjectName("linked_2d_3d_splitter")
                self.pose_split.setChildrenCollapsible(False)
                self.pose_split.addWidget(self.viewer_widget)
                self.linked_pose_panel = LinkedPosePanel()
                self.pose_split.addWidget(self.linked_pose_panel)
                self.pose_split.setStretchFactor(0, 2)
                self.pose_split.setStretchFactor(1, 1)
                self.pose_split.setSizes([760, 440])
                self.linked_pose_panel.hide()
                self.linked_pose_panel.ligandActivated.connect(self._highlight_linked_ligand)
                self.linked_pose_panel.exportRequested.connect(self._export_ligand_comparison)
                self.linked_pose_panel.detaching.connect(self._return_detached_structure)
                self.linked_pose_panel.detach_button.clicked.disconnect(self.linked_pose_panel.detach_diagram)
                self.linked_pose_panel.detach_button.clicked.connect(
                    lambda: self._open_interaction_review(self.linked_pose_panel.query))
                self.linked_pose_panel.detach_button.setText("Open 2D/3D review")
                self.live_layout.addWidget(self.pose_split, 1)
                self.cluster_contact_controls = ClusterContactControls(getattr(self.viewer_coordinator, 'adapter', None))
                self.live_layout.addWidget(self.cluster_contact_controls)
                self.review_tabs.addTab(self.live_page, "Interactive structure")
            else:
                self.live_page = self.structural_view
                self.live_layout = None
                self.review_tabs.addTab(self.live_page, "Interactive structure")
            self._detached_structure_window = None
            self._paired_interaction_window = None
            self._structure_scene_artifacts = None
            self._selected_structure_scene = None
            self._selected_structure_scenes = []
            self.central_selection_status = QtWidgets.QLabel("No shared structural selection")
            self.central_selection_status.setObjectName("central_selection_status")
            self.central_selection_status.setWordWrap(True)
            self.candidates = NavigationTable(0, 4)
            self.candidates.setHorizontalHeaderLabels(("Candidate", "Rank", "Summary", "Evidence"))
            self.candidates.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.candidates.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
            self.candidates.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.candidates.itemDoubleClicked.connect(self._show_candidate_evidence_details)
            self.candidates.itemClicked.connect(self._schedule_initial_candidate_review)
            self._candidate_evidence_dialogs = []
            central = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(central)
            layout.addWidget(self.automation_banner)
            layout.addWidget(self.summary)
            layout.addWidget(self.feedback_card)
            layout.addWidget(self.decision_banner)
            layout.addWidget(self.workspace_heading)
            layout.addWidget(self.workspace_context)
            layout.addWidget(self.review_tabs, 6)
            layout.addWidget(self.central_selection_status)
            self.pymol_controls = QtWidgets.QWidget()
            self.pymol_controls.setObjectName("pymol_review_controls")
            viewer_row = QtWidgets.QGridLayout(self.pymol_controls)
            viewer_row.setContentsMargins(0, 0, 0, 0)
            self.viewer_button = QtWidgets.QPushButton(
                "Load selected scene" if self.viewer_widget is not None
                else "Open selected scene in PyMOL"
            )
            self.viewer_button.setObjectName("open_pymol_review_button")
            self.viewer_button.clicked.connect(self.open_visual_review)
            # Embedded scenes are selected and loaded directly from the scene
            # chooser.  Never expose a control that looks like it launches a
            # second PyMOL application while that workspace is active.
            self.viewer_button.setVisible(self.viewer_widget is None)
            self.reset_view_button = QtWidgets.QPushButton("Reset to report view")
            self.reset_view_button.setObjectName("reset_report_view_button")
            self.reset_view_button.clicked.connect(self.reset_report_view)
            self.detach_viewer_button = QtWidgets.QPushButton("Detach PyMOL")
            self.detach_viewer_button.setObjectName("detach_embedded_viewer_button")
            self.detach_viewer_button.setVisible(self.viewer_widget is not None)
            self.detach_viewer_button.setToolTip("Open the full PyMOL interface using this same live scene and camera; closing it returns to the workspace.")
            self.detach_viewer_button.clicked.connect(self.open_full_pymol)
            self.decision_synopsis_button = QtWidgets.QPushButton("Review decision…")
            self.decision_synopsis_button.setObjectName("decision_synopsis_button")
            self.decision_synopsis_button.clicked.connect(self.show_decision_synopsis)
            self.full_synopsis_button = QtWidgets.QPushButton("Full synopsis report")
            self.full_synopsis_button.setObjectName("full_synopsis_report_button")
            self.full_synopsis_button.clicked.connect(self.show_full_synopsis_report)
            self.viewer_status = QtWidgets.QLabel(
                "Interactive structure has not been loaded"
                if self.viewer_widget is not None else "PyMOL review has not been opened"
            )
            self.scene_choice_label = QtWidgets.QLabel("Scene:")
            viewer_row.addWidget(self.scene_choice_label, 0, 0)
            viewer_row.addWidget(self.structure_scene_choice, 0, 1)
            viewer_row.addWidget(self.viewer_button, 0, 2)
            viewer_row.addWidget(self.detach_viewer_button, 0, 3)
            viewer_row.addWidget(self.reset_view_button, 0, 4)
            viewer_row.addWidget(self.decision_synopsis_button, 0, 5)
            viewer_row.addWidget(self.full_synopsis_button, 0, 6)
            viewer_row.setColumnStretch(1, 1)
            viewer_row.addWidget(self.viewer_status, 1, 0, 1, 7)
            self.pymol_controls.hide()
            self.review_tabs.currentChanged.connect(self._review_mode_changed)
            self._review_mode_changed(self.review_tabs.currentIndex())
            layout.addWidget(self.pymol_controls)
            layout.addWidget(self.candidates, 1)
            self.candidates.setMaximumHeight(125)
            self.region_approval_controls = QtWidgets.QWidget()
            approval_row = QtWidgets.QHBoxLayout(self.region_approval_controls)
            approval_row.setContentsMargins(0, 0, 0, 0)
            self.candidate_review_button = QtWidgets.QPushButton(
                "Review selected region in 3D"
            )
            self.candidate_review_button.setObjectName("review_selected_candidate_button")
            self.candidate_review_button.setToolTip(
                "Open the retained receptor, pocket coordinates, and proposed box. "
                "Viewing does not approve the region."
            )
            self.candidate_review_button.clicked.connect(
                self.open_selected_candidate_review
            )
            self.rationale = QtWidgets.QLineEdit()
            self.rationale.setPlaceholderText("Optional decision note")
            self.rationale.setToolTip("Record why you chose these regions. This note is saved with your approval.")
            self.approve_button = QtWidgets.QPushButton("Approve selected docking region(s)")
            self.approve_button.setObjectName("approve_regions_button")
            self.approve_button.clicked.connect(self.approve_selected_regions)
            approval_row.addWidget(self.candidate_review_button)
            approval_row.addWidget(self.rationale, 1)
            approval_row.addWidget(self.approve_button)
            layout.addWidget(self.region_approval_controls)
            self.setCentralWidget(central)

            self.view_toolbar = self.addToolBar("View")
            self.view_toolbar.setObjectName("view_toolbar")
            self.scientific_detail_action = self.view_toolbar.addAction("Scientific Detail")
            self.scientific_detail_action.setCheckable(True)
            self.focus_canvas_action = self.view_toolbar.addAction("Focus canvas")
            self.focus_canvas_action.setCheckable(True)
            self.focus_canvas_action.setShortcut("Ctrl+Shift+F")
            self.focus_canvas_action.toggled.connect(self.set_canvas_focus_mode)

            self.scientific_detail_panel = ScientificDetailPanel()
            self.detail = self.scientific_detail_panel.mode
            self.event_view = self.scientific_detail_panel.view
            self.scientific_detail_panel.detailChanged.connect(self._detail_changed)
            self.detail.setCurrentText(self.session.detail_level.title())
            self.log_view = QtWidgets.QPlainTextEdit()
            self.log_view.setReadOnly(True)
            self.report_list = QtWidgets.QListWidget()
            self.report_list.itemDoubleClicked.connect(self.open_artifact)
            self.selection_view = QtWidgets.QTreeWidget()
            self.selection_view.setHeaderLabels(("Proposed selection", "Identity"))
            self.workflow_detail_dock = self._dock("Scientific Workflow Detail", self.scientific_detail_panel, QtCore.Qt.DockWidgetArea.RightDockWidgetArea, "workflow_detail_dock")
            self.scientific_detail_action.triggered.connect(
                lambda checked: self._set_auxiliary_dock_visible(
                    self.workflow_detail_dock,
                    QtCore.Qt.DockWidgetArea.RightDockWidgetArea, checked,
                )
            )
            self.workflow_detail_dock.visibilityChanged.connect(
                self.scientific_detail_action.setChecked
            )
            self.selection_dock = self._dock("Selections", self.selection_view, QtCore.Qt.DockWidgetArea.RightDockWidgetArea, "selection_dock")
            self.selection_dock.hide()
            self.selections_action = self._add_auxiliary_dock_action(
                "Selections", self.selection_dock, QtCore.Qt.DockWidgetArea.RightDockWidgetArea,
            )
            self.logs_dock = self._dock("Complete Logs", self.log_view, QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, "logs_dock")
            self.reports_dock = self._dock("Reports and Study Files", self.report_list, QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, "reports_dock")
            self.tabifyDockWidget(self.logs_dock, self.reports_dock)
            self.logs_dock.hide()
            self.reports_dock.hide()
            self.logs_action = self._add_auxiliary_dock_action(
                "Logs", self.logs_dock, QtCore.Qt.DockWidgetArea.BottomDockWidgetArea,
            )
            self.artifacts_action = self._add_auxiliary_dock_action(
                "Study files", self.reports_dock, QtCore.Qt.DockWidgetArea.BottomDockWidgetArea,
            )
            self.pocket_evidence_panel = PocketEvidencePanel()
            self.pocket_score_plot = PocketScorePlot()
            self.pocket_score_scroll = QtWidgets.QScrollArea()
            self.pocket_score_scroll.setWidgetResizable(True)
            self.pocket_score_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            self.pocket_score_scroll.setFixedHeight(290)
            self.pocket_score_scroll.setWidget(self.pocket_score_plot)
            self.pocket_evidence_panel.content_layout.insertWidget(0, self.pocket_score_scroll)
            self.pocket_score_plot.candidateActivated.connect(self._select_plotted_candidate)
            self.pocket_evidence_panel.set_viewer_presentation(
                embedded=self.viewer_widget is not None
            )
            self.pocket_evidence_panel.ligandRequested.connect(self.show_evidence_ligand)
            self.pocket_evidence_panel.interactionsRequested.connect(self.render_evidence_interactions)
            self.pocket_evidence_panel.residuesRequested.connect(self.highlight_evidence_residues)
            self.pocket_evidence_panel.ligandsRequested.connect(self.show_evidence_ligands)
            self.pocket_evidence_panel.selectionChanged.connect(self.sync_evidence_selection)
            self.pocket_evidence_dock = self._dock(
                "Experimental PDB Evidence", self.pocket_evidence_panel,
                QtCore.Qt.DockWidgetArea.RightDockWidgetArea, "pocket_evidence_dock",
            )
            self._build_setup_dock()
            self._build_finalization_dock()
            self._build_screening_dock()
            self._build_screening_results_dock()
            self._build_workflow_navigation_dock()
            self._establish_default_dock_layout()
            # Keep the default stage readable; Results Review is opened by
            # selecting stage 6 or using its detach action.
            self.screening_results_dock.hide()
            self.results_review_action = self.view_toolbar.addAction("Detach Results Review")
            self.results_review_action.setObjectName("detach_results_review_action")
            self.results_review_action.triggered.connect(self.toggle_results_review_window)
            self.save_image = save_image_button(self, [
                ('3D PyMOL view', lambda: self.viewer_widget is not None and self.viewer_widget.isVisible(),
                 self._export_current_pymol_image),
                ('Selected 2D interaction diagram — original resolution',
                 lambda: self._export_diagram_path() is not None, self._export_selected_diagram),
                ('Pocket-ranking plot', lambda: bool(self.pocket_score_plot.points),
                 lambda: ImageExport(self.pocket_score_plot.grab().toImage(),
                     {'kind': 'pocket_ranking_plot', 'study_id': self.study_id,
                      'detector': self.pocket_score_plot.detector}, self._protected_image_sources())),
                ('3D PyMOL view — ray-traced PNG',
                 lambda: self.viewer_widget is not None and self.viewer_widget.isVisible(),
                 lambda: self._export_current_pymol_image(ray=True)),
            ])
            self.view_toolbar.addWidget(self.save_image)
            self._render_results_session_status(self.session.selection)
            self._render_central_selection_status(self.session.selection)
            self.statusBar().showMessage("Selections are proposals until explicitly approved through the application host")

        def _protected_image_sources(self):
            paths = [artifact.path for artifact in self.state.artifacts]
            query = getattr(getattr(self, 'linked_pose_panel', None), 'query', None)
            if query:
                paths.extend((query.diagram, query.ligand, query.receptor, query.interactions))
            return tuple(p for p in paths if p)

        def _export_current_pymol_image(self, *, ray=False):
            return pymol_export(self.viewer_widget, {'study_id': self.study_id}, self._protected_image_sources(), ray=ray)

        def _export_diagram_path(self):
            if getattr(self, '_paired_interaction_window', None) is not None:
                return self.linked_pose_panel.query.diagram
            value = self.interaction_diagram_choice.currentData()
            if value and getattr(self, '_interaction_source_pixmap', None) is not None:
                path = Path(str(value))
                if path.is_file():
                    return path
            query = getattr(getattr(self, 'linked_pose_panel', None), 'query', None)
            return query.diagram if query and query.diagram.is_file() else None

        def _export_selected_diagram(self):
            path = self._export_diagram_path()
            if path is None:
                raise ValueError('Select a retained 2D diagram first.')
            view = pose_view(path)
            if view:
                result = diagram_export(view)
                result.protected_paths += self._protected_image_sources()
                return result
            return ImageExport(QtGui.QImage(str(path)),
                {'kind': 'retained_2d_diagram', 'source': str(path.resolve()), 'study_id': self.study_id},
                self._protected_image_sources() + (path,))


        def _establish_default_dock_layout(self) -> None:
            """Provide a readable three-column baseline before optional saved state."""
            self.resizeDocks(
                [self.workflow_navigation_dock], [self.WORKFLOW_RAIL_WIDTH],
                QtCore.Qt.Orientation.Horizontal,
            )
            self.resizeDocks(
                [self.study_setup_dock], [self.WORKFLOW_RAIL_WIDTH],
                QtCore.Qt.Orientation.Horizontal,
            )
            self.resizeDocks(
                [self.workflow_detail_dock, self.pocket_evidence_dock],
                [260, 700], QtCore.Qt.Orientation.Vertical,
            )
            self.resizeDocks(
                [self.pocket_evidence_dock], [360],
                QtCore.Qt.Orientation.Horizontal,
            )

        def _build_setup_dock(self) -> None:
            panel = self.study_setup_panel = StudySetupPanel()
            self.input_pdb = panel.input_pdb
            self.output_directory = panel.output_directory
            self.site_mode = panel.site_mode
            self.study_pathway = panel.pathway
            self.control_engine = panel.control_engine
            self.control_tier = panel.control_tier
            self.ligand_resname = panel.ligand_resname
            self.pocket_engine = panel.pocket_engine
            self.start_preparation_button = panel.prepare_button
            self.cancel_job_button = panel.cancel_button
            panel.chooseInputRequested.connect(self.choose_input_pdb)
            panel.chooseProtocolRequested.connect(self.choose_saved_protocol)
            panel.reviewProtocolRequested.connect(self.review_imported_protocol)
            panel.fetchInputRequested.connect(self.fetch_input_pdb)
            self.input_pdb.editingFinished.connect(self.refresh_input_coordinate_evidence)
            self.input_pdb.editingFinished.connect(
                lambda: self.detect_bound_ligands(quiet=True)
                if self.study_pathway.currentData() == "control" else None
            )
            self.study_pathway.currentIndexChanged.connect(
                lambda: self.detect_bound_ligands(quiet=True)
                if self.study_pathway.currentData() == "control" else None
            )
            panel.detectLigandsRequested.connect(self.detect_bound_ligands)
            panel.chooseOutputRequested.connect(self.choose_output_directory)
            panel.prepareRequested.connect(self.start_preparation)
            panel.cancelRequested.connect(self.cancel_active_job)
            self.study_setup_dock = self._dock("Study Setup", panel, QtCore.Qt.LeftDockWidgetArea, "study_setup_dock")

        def _build_finalization_dock(self) -> None:
            panel = self.protocol_finalization_panel = ProtocolFinalizationPanel()
            aliases = {
                "final_output_directory": "output_directory", "protocol_engine": "engine",
                "protocol_ph": "ph", "protocol_conformers": "conformers",
                "protocol_seeds": "seeds", "protocol_base_seed": "base_seed",
                "protocol_exhaustiveness": "exhaustiveness", "protocol_modes": "modes",
                "protocol_energy_range": "energy_range", "exploratory_approval": "approval",
                "protocol_ad4_runs":"ad4_runs", "protocol_ad4_heuristic_cap":"ad4_heuristic_cap",
                "finalize_button": "finalize_button", "open_final_report_button": "open_report_button",
                "open_bundle_location_button": "open_bundle_button", "finalization_status": "status",
            }
            for window_name, panel_name in aliases.items():
                setattr(self, window_name, getattr(panel, panel_name))
            panel.chooseOutputRequested.connect(self.choose_final_output_directory)
            panel.finalizeRequested.connect(self.start_protocol_finalization)
            panel.openReportRequested.connect(self.open_final_report)
            panel.openBundleRequested.connect(self.open_bundle_location)
            panel.approvalChanged.connect(self.refresh)
            self.protocol_finalization_dock = self._dock("Finalize Reusable Protocol", panel, QtCore.Qt.LeftDockWidgetArea, "protocol_finalization_dock")

        def _build_screening_dock(self) -> None:
            panel = self.screening_setup_panel = ScreeningSetupPanel()
            aliases = {
                "screen_ligands": "ligands", "screen_output": "output",
                "screen_analysis": "analysis", "screen_representatives": "representatives",
                "screen_cluster_rmsd": "cluster_rmsd", "screen_stop_on_error": "stop_on_error",
                "screen_exploratory_approval": "approval", "preview_screening_button": "preview_button",
                "start_screening_button": "run_button", "screening_status": "status",
            }
            for window_name, panel_name in aliases.items():
                setattr(self, window_name, getattr(panel, panel_name))
            self._screening_plan = None
            self._ligand_read_generation = 0
            self._ligand_read_tasks = set()
            panel.library_panel.loadRequested.connect(self.read_screening_library)
            panel.library_panel.columnsApprovalRequested.connect(self.read_screening_library)
            panel.library_panel.sheetRequested.connect(lambda sheet: self.read_screening_library(sheet=sheet))
            panel.library_panel.previewRequested.connect(self.preview_library_record)
            panel.library_panel.selectionChanged.connect(self._invalidate_screening_plan)
            panel.ligands.textChanged.connect(self._clear_screening_library)
            panel.chooseFileRequested.connect(self.choose_screen_ligand_file)
            panel.chooseDirectoryRequested.connect(self.choose_screen_ligand_directory)
            panel.chooseOutputRequested.connect(self.choose_screen_output)
            panel.previewRequested.connect(self.preview_screening)
            panel.runRequested.connect(self.start_screening)
            panel.inputsChanged.connect(self._invalidate_screening_plan)
            panel.approvalChanged.connect(self._update_screening_controls)
            self.screening_dock = self._dock("Locked-Protocol Screening", panel, QtCore.Qt.LeftDockWidgetArea, "locked_protocol_screening_dock")

        def _build_screening_results_dock(self) -> None:
            self.results_review_panel = ResultsReviewPanel(self.poseedit_runtime)
            panel = self.results_review_panel
            panel.set_viewer_presentation(embedded=self.viewer_widget is not None)
            # Compatibility aliases keep the existing scientific controller
            # methods stable while the presentation component is extracted.
            self.results_session_status = panel.session_status
            self.results_window_button = panel.window_button
            self.screening_results = panel.screening_results
            self.poseedit_runtime_status = panel.renderer_status
            self.pose_review_mode = panel.review_mode
            self.pose_cluster_filter = panel.cluster_filter
            self.interaction_diagram_choice = panel.diagram_choice
            self.interaction_diagram_view = panel.diagram_view
            self.interaction_scroll = panel.diagram_scroll
            self.interaction_context = panel.interaction_context
            self.interaction_zoom = panel.interaction_zoom
            self.pose_results = panel.pose_results
            self.open_screen_report_button = panel.open_report_button
            self.open_pose_session_button = panel.open_pose_session_button
            self.sync_pose_button = panel.sync_pose_button
            self.open_interaction_diagram_button = panel.open_diagram_button

            self.results_window_button.clicked.connect(self.toggle_results_review_window)
            self.screening_results.itemSelectionChanged.connect(
                self._screening_result_selection_changed
            )
            self.pose_review_mode.currentIndexChanged.connect(self._pose_review_mode_changed)
            self.pose_cluster_filter.currentIndexChanged.connect(self._apply_pose_cluster_filter)
            self.interaction_diagram_choice.currentIndexChanged.connect(
                self._show_selected_interaction_diagram
            )
            self.interaction_diagram_view.activated.connect(
                self._activate_interaction_ligand
            )
            self.interaction_zoom.currentIndexChanged.connect(self._interaction_zoom_changed)
            self.pose_results.itemSelectionChanged.connect(self._expanded_pose_selection_changed)
            self.open_screen_report_button.clicked.connect(self.open_screening_report)
            self.open_pose_session_button.clicked.connect(self.open_selected_pose_session)
            self.sync_pose_button.clicked.connect(self.sync_selected_pose_to_pymol)
            self.open_interaction_diagram_button.clicked.connect(
                self.open_selected_interaction_diagram
            )
            self.screening_results_dock = self._dock(
                "Results Review", panel,
                QtCore.Qt.RightDockWidgetArea, "screening_results_dock",
            )
            self.screening_results_dock.topLevelChanged.connect(
                self._results_review_top_level_changed
            )

        def _build_study_menu(self) -> None:
            menu = self.menuBar().addMenu("Study")
            self.current_study_action = menu.addAction(f"Current: {self.study_id}")
            self.current_study_action.setEnabled(False)
            menu.addSeparator()
            self.new_study_action = menu.addAction("New study…")
            self.new_study_action.setObjectName("new_study_action")
            self.open_study_action = menu.addAction("Open study…")
            self.open_study_action.setObjectName("open_study_action")
            self.new_study_action.triggered.connect(lambda: self._choose_another_study("create"))
            self.open_study_action.triggered.connect(lambda: self._choose_another_study("open"))

        def _choose_another_study(self, mode: str) -> None:
            if not self.host_controller.available:
                QtWidgets.QMessageBox.warning(
                    self, "Application host unavailable",
                    "Reconnect the scientific application host before creating or opening a study.",
                )
                return
            from .study_launcher import choose_study
            selected = choose_study(
                self.store, self.host_client, self, mode=mode,
                current_study_id=self.study_id,
            )
            if selected and selected != self.study_id:
                self.studySwitchRequested.emit(selected)

        def _form_settings_group(self) -> str:
            return f"study-drafts/{self.study_id}"

        @staticmethod
        def _restore_combo(combo, value) -> None:
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)

        def _save_form_values(self) -> None:
            """Save reversible draft inputs, never scientific authorization."""
            values = {
                "setup/input_pdb": self.input_pdb.text(),
                "setup/output_directory": self.output_directory.text(),
                "setup/site_mode": self.site_mode.currentData(),
                "setup/pathway": self.study_pathway.currentData(),
                "setup/control_engine": self.control_engine.currentData(),
                "setup/control_tier": self.control_tier.currentData(),
                "setup/ligand_resname": self.study_setup_panel.ligand_value(),
                "setup/pocket_engine": self.pocket_engine.currentData(),
                "setup/predict_with_ligand": self.study_setup_panel.predict_with_ligand.isChecked(),
                "final/output_directory": self.final_output_directory.text(),
                "final/engine": self.protocol_engine.currentData(),
                "final/ph": self.protocol_ph.value(),
                "final/conformers": self.protocol_conformers.value(),
                "final/seeds": self.protocol_seeds.value(),
                "final/base_seed": self.protocol_base_seed.value(),
                "final/exhaustiveness": self.protocol_exhaustiveness.value(),
                "final/modes": self.protocol_modes.value(),
                "final/energy_range": self.protocol_energy_range.value(),
                "final/ad4_runs":self.protocol_ad4_runs.value(),
                "final/ad4_heuristic_cap":self.protocol_ad4_heuristic_cap.value(),
                "screen/ligands": self.screen_ligands.text(),
                "screen/output": self.screen_output.text(),
                "screen/analysis": self.screen_analysis.currentData(),
                "screen/representatives": self.screen_representatives.value(),
                "screen/cluster_rmsd": self.screen_cluster_rmsd.value(),
                "screen/stop_on_error": self.screen_stop_on_error.isChecked(),
            }
            self.settings.beginGroup(self._form_settings_group())
            try:
                for key, value in values.items():
                    self.settings.setValue(key, value)
            finally:
                self.settings.endGroup()
            self.settings.sync()

        def _restore_form_values(self) -> None:
            """Restore convenience inputs while requiring fresh approvals."""
            self.settings.beginGroup(self._form_settings_group())
            try:
                if not self.settings.childKeys() and not self.settings.childGroups():
                    return
                if not self.state.workflow_data.get("study_setup"):
                    self.input_pdb.setText(self.settings.value("setup/input_pdb", "", type=str))
                    self.output_directory.setText(
                        self.settings.value("setup/output_directory", "", type=str)
                    )
                    self._restore_combo(
                        self.site_mode, self.settings.value("setup/site_mode", "pockets", type=str)
                    )
                    self.study_setup_panel.predict_with_ligand.setChecked(
                        self.settings.value("setup/predict_with_ligand", False, type=bool)
                    )
                    self._restore_combo(
                        self.study_pathway, self.settings.value("setup/pathway", "exploratory", type=str)
                    )
                    self._restore_combo(
                        self.control_engine, self.settings.value("setup/control_engine", "vina", type=str)
                    )
                    self._restore_combo(
                        self.control_tier, self.settings.value("setup/control_tier", "quick", type=str)
                    )
                    self.ligand_resname.setCurrentText(
                        self.settings.value("setup/ligand_resname", "", type=str)
                    )
                    self._restore_combo(
                        self.pocket_engine,
                        self.settings.value("setup/pocket_engine", "p2rank", type=str),
                    )
                self.final_output_directory.setText(
                    self.settings.value("final/output_directory", "", type=str)
                )
                self._restore_combo(
                    self.protocol_engine, self.settings.value("final/engine", "vina", type=str)
                )
                for key, widget, value_type in (
                    ("final/ph", self.protocol_ph, float),
                    ("final/conformers", self.protocol_conformers, int),
                    ("final/seeds", self.protocol_seeds, int),
                    ("final/base_seed", self.protocol_base_seed, int),
                    ("final/exhaustiveness", self.protocol_exhaustiveness, int),
                    ("final/modes", self.protocol_modes, int),
                    ("final/energy_range", self.protocol_energy_range, float),
                    ("final/ad4_runs",self.protocol_ad4_runs,int),
                    ("final/ad4_heuristic_cap",self.protocol_ad4_heuristic_cap,int),
                    ("screen/representatives", self.screen_representatives, int),
                    ("screen/cluster_rmsd", self.screen_cluster_rmsd, float),
                ):
                    stored = self.settings.value(key, None, type=value_type)
                    if stored is not None:
                        widget.setValue(stored)
                self.screen_ligands.setText(
                    self.settings.value("screen/ligands", "", type=str)
                )
                self.screen_output.setText(self.settings.value("screen/output", "", type=str))
                self._restore_combo(
                    self.screen_analysis,
                    self.settings.value("screen/analysis", "representatives", type=str),
                )
                self.screen_stop_on_error.setChecked(
                    self.settings.value("screen/stop_on_error", False, type=bool)
                )
            finally:
                self.settings.endGroup()
            self.exploratory_approval.setChecked(False)
            self.screen_exploratory_approval.setChecked(False)
            self._screening_plan = None

        def toggle_results_review_window(self) -> None:
            """Detach or redock the one results surface; never clone workflow state."""
            if self.screening_results_dock.isFloating():
                self.redock_results_review()
            else:
                self.detach_results_review()

        def detach_results_review(self) -> None:
            self.results_review_panel.setParent(None)
            self.screening_results_dock.setWidget(self.results_review_panel)
            self.screening_results_dock.show()
            self.screening_results_dock.setFloating(True)
            self.screening_results_dock.resize(920, 760)
            self.screening_results_dock.raise_()
            self.screening_results_dock.activateWindow()

        def redock_results_review(self) -> None:
            self.results_review_panel.setParent(None)
            self.screening_results_dock.setWidget(QtWidgets.QWidget())
            self.screening_results_dock.setFloating(False)
            self.screening_results_dock.hide()
            self.right_review_stack.insertWidget(1, self.results_review_panel)
            self.right_review_stack.setCurrentWidget(self.results_review_panel)
            self.pocket_evidence_dock.show()

        def _results_review_top_level_changed(self, floating: bool) -> None:
            label = "Return to workspace" if floating else "Detach review"
            self.results_window_button.setText(label)
            if hasattr(self, "results_review_action"):
                self.results_review_action.setText(
                    "Return Results Review to workspace" if floating else "Detach Results Review"
                )
            self.screening_results_dock.setWindowTitle(
                "Docking Universal — Results Review" if floating else "Results Review"
            )

        def _render_results_session_status(self, selection) -> None:
            parts = ["Shared study"]
            if selection.compound:
                parts.append(Path(selection.compound).name)
            if selection.site:
                parts.append(str(selection.site))
            if selection.cluster_id is not None:
                parts.append(f"cluster {selection.cluster_id}")
            if selection.pose_id is not None:
                parts.append(f"pose {selection.pose_id}")
            elif selection.compound is None:
                parts.append("no pose selected")
            self.results_session_status.setText(" · ".join(parts))

        def _render_central_selection_status(self, selection) -> None:
            parts = []
            if selection.compound:
                parts.append(Path(selection.compound).name)
            if selection.site:
                parts.append(str(selection.site))
            if selection.cluster_id is not None:
                parts.append(f"cluster {selection.cluster_id}")
            if selection.pose_id is not None:
                parts.append(f"pose {selection.pose_id}")
            self.central_selection_status.setText(
                "Shared selection: " + " · ".join(parts)
                if parts else "No shared structural selection"
            )

        @staticmethod
        def _report_asset_label(path: Path) -> str | None:
            name = path.stem.lower()
            control_labels = {
                "control_panel_a_cluster": "Control pose recovery — cluster landscape",
                "control_panel_b_overlay": "Control pose recovery — 3D overlay",
                "control_panels_ab": "Control pose recovery — landscape and 3D",
                "control_experimental_plip2d": "Control interactions — experimental ligand",
                "control_top_ranked_plip2d": "Control interactions — lowest-energy pose",
                "control_lowest_rmsd_plip2d": "Control interactions — global lowest-RMSD pose",
            }
            if name in control_labels:
                return control_labels[name]
            if name.startswith("control_energy_rank_") and name.endswith("_plip2d"):
                return f"Control interactions — energy rank {name.split('_')[3]}"
            if name.endswith("cavity_panel_a_selection"):
                return "Pocket scores and ranking — Panel A"
            if name.endswith("cavity_panel_b_structure"):
                return "Pocket structural evidence — Panel B"
            if name.endswith("cavity_panels_ab"):
                return "Pocket ranking and structural evidence"
            if name.endswith("cavity_selected_box"):
                return "Selected docking region"
            if "pocket_evidence_site_" in name and name.endswith("_ab_3d"):
                return "Deposited-ligand alignment — Panel A"
            if "pocket_evidence_site_" in name and name.endswith("_ab_2d"):
                return "Deposited-ligand identity — Panel B"
            if "pocket_evidence_site_" in name and name.endswith("_ab"):
                return "Deposited-ligand site evidence"
            if name.endswith("_panels_ab"):
                return "Docking clusters and representative poses"
            if name.endswith("_panel_a_clusters"):
                return "Docking scores and clusters — Panel A"
            if name.endswith("_panel_b_representatives"):
                return "Docking pose representatives — Panel B"
            if name.endswith("_selected_interactions_abc"):
                return "Top-pose interaction diagrams"
            if name.endswith("_top3_3d_snapshots"):
                return "Top three poses in the receptor"
            if name == "representative_plip2d":
                cluster = path.parent.parent.name.removeprefix("cluster_").lstrip("0") or "0"
                return f"Pose interaction diagram — Cluster {cluster}"
            return None


        def _refresh_structure_scenes(self, state: StudyState) -> None:
            """Discover live sessions without decoding any report PNGs.

            Legacy inventories may identify PSEs only through report assets.
            Keep that filename/manifest mapping, not the static image viewer.
            """
            retained = {}

            def add(label, scene):
                scene = Path(scene)
                if scene.suffix.lower() == '.pse' and scene.is_file():
                    retained.setdefault(str(scene.resolve()), label)

            for artifact in state.artifacts:
                path = Path(artifact.path)
                if path.suffix.lower() == '.pse':
                    add(self._report_asset_label(path) or path.stem.replace('_', ' '), path)
                elif artifact.kind in {'scientific_image', 'final_report_figure', 'screening_report_figure'}:
                    label = self._report_asset_label(path) or path.stem.replace('_', ' ')
                    for panel, scene in self._scenes_for_report_asset(path):
                        add(label + ' — ' + panel, scene)
            control_root = state.workflow_data.get('latest_control_output')
            if control_root:
                for scene in sorted((Path(control_root) / 'report').glob('*.pse')):
                    add(self._report_asset_label(scene) or scene.stem.replace('_', ' '), scene)
            current = self.structure_scene_choice.currentData()
            self.structure_scene_choice.blockSignals(True)
            self.structure_scene_choice.clear()
            for scene, label in sorted(retained.items(), key=lambda item: (item[1], item[0])):
                self.structure_scene_choice.addItem(label, scene)
            index = self.structure_scene_choice.findData(current)
            if index >= 0:
                self.structure_scene_choice.setCurrentIndex(index)
            self.structure_scene_choice.blockSignals(False)
            self._selected_structure_scenes = list(retained)
            selected = self.structure_scene_choice.currentData()
            self._selected_structure_scene = Path(selected) if selected else None
            has_scenes = bool(retained)
            self.scene_choice_label.setVisible(has_scenes)
            self.structure_scene_choice.setVisible(has_scenes)
            self.viewer_button.setVisible(self.viewer_widget is None and has_scenes)
            self.viewer_button.setEnabled(self.viewer_coordinator is not None and has_scenes)
            self.structural_view.setText(
                "Interactive 3D review\n\nChoose a scene or review a selected pocket in PyMOL. "
                "Static figures are available in the reports. Viewing is not approval."
            )


        def _structure_scene_changed(self, index: int) -> None:
            scene = self.structure_scene_choice.itemData(index) if index >= 0 else None
            self._selected_structure_scene = Path(scene) if scene else None
            if scene and self.viewer_widget is not None:
                self._open_visual_scene(Path(scene))
                self.review_tabs.setCurrentWidget(self.live_page)

        def _review_mode_changed(self, _index: int) -> None:
            """The central review surface is interactive only."""
            embedded = self.viewer_widget is not None
            self.pymol_controls.setVisible(embedded or self.viewer_coordinator is not None)
            self.workspace_context.setVisible(not embedded)
            self.central_selection_status.setVisible(not embedded)
            self.viewer_status.setVisible(not embedded)
            self._size_candidate_table()
            if embedded and not getattr(self, '_linked_pose_active', False):
                self._schedule_initial_candidate_review()

        def _schedule_initial_candidate_review(self, *_args) -> None:
            # Default table highlighting is performed with signals blocked.
            # Replay it only after the window and GL viewport can be displayed;
            # clicking the already-highlighted row must work too.
            if getattr(self, "_initial_candidate_review_pending", False):
                return
            self._initial_candidate_review_pending = True
            QtCore.QTimer.singleShot(0, self._initialize_candidate_review)

        def _initialize_candidate_review(self) -> None:
            self._initial_candidate_review_pending = False
            if (
                not self.isVisible() or self.viewer_widget is None
                or self.viewer_coordinator is None or self.viewer_coordinator.connected
                or self.review_tabs.currentWidget() is not self.live_page
                or getattr(self, "_workflow_target", None) != "central"
            ):
                return
            rows = self.candidates.selectionModel().selectedRows()
            candidates = self.state.workflow_data.get("pocket_candidates", [])
            if not rows or rows[0].row() >= len(candidates):
                return
            candidate = candidates[rows[0].row()]
            geometry = candidate.get("evidence", {}).get("geometry", {})
            if any(geometry.get(f"{field}_{axis}") is None
                   for field in ("center", "size") for axis in "xyz"):
                return
            # Draft/simulated studies are not renderable. Do not turn their
            # placeholder rows into an automatic error dialog or launch a
            # companion process. The normal coordinator validates provenance.
            if not any(
                artifact.kind in {"prepared_receptor_structure", "report_view_session"}
                and artifact.sha256 and Path(artifact.path).is_file()
                for artifact in self.state.artifacts
            ):
                return
            if self._connect_structure_review():
                self._candidate_highlight_changed()

        def _return_detached_structure(self) -> None:
            self._close_interaction_review()
            if self._detached_structure_window is not None:
                self._detached_structure_window.close()

        def _close_interaction_review(self):
            window = getattr(self, "_paired_interaction_window", None)
            if window is not None:
                window.close()

        def _open_interaction_review(self, view):
            import time
            started = time.perf_counter()
            if view is None or self.viewer_widget is None:
                return False
            existing = getattr(self, "_paired_interaction_window", None)
            if existing is not None and existing.view == view:
                existing.show()
                existing.raise_()
                return True
            self._close_interaction_review()
            self._return_detached_structure()
            if self.linked_pose_panel._detached_window is not None:
                self.linked_pose_panel._detached_window.close()
            adapter = self.viewer_coordinator.adapter
            snapshot = None
            previous_linked = getattr(self, "_linked_pose_active", False)
            try:
                if not self.viewer_coordinator.connected:
                    adapter.launch()
                    self.viewer_coordinator.connected = True
                snapshot = adapter.begin_interaction_review(view)
                panel = self.linked_pose_panel
                sizes = self.pose_split.sizes()
                panel.set_pose(view)
                panel.detach_button.hide()
                from .interaction_review_window import InteractionReviewWindow
                window = InteractionReviewWindow(view, panel, self.viewer_widget, adapter, self)
                self._paired_interaction_window = window
                self._linked_pose_active = True
                restored = {"done": False}
                frame_callback = {"connected": False}

                def restore(*_args):
                    if restored["done"]:
                        return
                    restored["done"] = True
                    if frame_callback["connected"]:
                        self.viewer_widget.frameSwapped.disconnect(first_frame)
                        frame_callback["connected"] = False
                    window.dispose()
                    self.pose_split.insertWidget(0, self.viewer_widget)
                    self.pose_split.insertWidget(1, panel)
                    self.pose_split.setSizes(sizes)
                    panel.detach_button.show()
                    panel.detach_button.setText("Open 2D/3D review")
                    panel.hide()  # diagrams use the paired window, not a crowded embedded column
                    self.viewer_widget.show()
                    try:
                        adapter.end_interaction_review(snapshot)
                    except Exception as exc:
                        self.viewer_status.setText(f"Study scene could not be restored: {exc}")
                    self._paired_interaction_window = None
                    self._linked_pose_active = previous_linked
                    self._sync_residue_highlight_actions()
                    self._ensure_pocket_space()
                    window.deleteLater()

                window.finished.connect(restore)
                window.showMaximized()
                panel.show()
                self.viewer_widget.show()
                QtCore.QTimer.singleShot(0, panel._fit)
                self._paired_review_latency = {'setup_seconds': time.perf_counter() - started,
                                              'first_frame_seconds': None, 'source': view.label}
                def first_frame():
                    self._paired_review_latency['first_frame_seconds'] = time.perf_counter() - started
                    self.viewer_widget.frameSwapped.disconnect(first_frame)
                    frame_callback["connected"] = False
                if hasattr(self.viewer_widget, 'frameSwapped'):
                    self.viewer_widget.frameSwapped.connect(first_frame)
                    frame_callback["connected"] = True
                return True
            except Exception as exc:
                if snapshot is not None:
                    adapter.end_interaction_review(snapshot)
                self.pose_split.insertWidget(0, self.viewer_widget)
                self.pose_split.insertWidget(1, self.linked_pose_panel)
                self.linked_pose_panel.detach_button.show()
                self.linked_pose_panel.hide()
                self._paired_interaction_window = None
                self._linked_pose_active = previous_linked
                self.viewer_status.setText(f"Paired 2D/3D review unavailable: {exc}")
                QtWidgets.QMessageBox.warning(self, "2D/3D review unavailable", str(exc))
                return False

        def open_full_pymol(self) -> None:
            """Move the live viewport into upstream PyMOL's complete Qt shell."""
            if self.viewer_widget is None:
                return
            self._close_interaction_review()
            existing = self._detached_structure_window
            if existing is not None:
                if getattr(existing, "_du_full_pymol", False):
                    existing.show()
                    existing.raise_()
                    existing.activateWindow()
                    return
                existing.close()
            if self.linked_pose_panel._detached_window is not None:
                self.linked_pose_panel._detached_window.close()
            from ..viewer.full_pymol import create_full_pymol_window
            sizes = self.pose_split.sizes()

            def restore():
                browser = getattr(self._detached_structure_window, "study_panel", None)
                if browser is not None:
                    browser.dispose()
                self.pose_split.insertWidget(0, self.viewer_widget)
                self.pose_split.setSizes(sizes)
                self.viewer_widget.show()
                self._detached_structure_window = None
                self.review_tabs.setCurrentWidget(self.live_page)

            try:
                window = create_full_pymol_window(self.viewer_widget, self, restore)
                window._du_full_pymol = True
                self._detached_structure_window = window
                from .full_pymol_study import FullPyMOLStudyPanel
                window.study_panel = FullPyMOLStudyPanel(self)
                dock = QtWidgets.QDockWidget("Study evidence", window)
                dock.setObjectName("full_pymol_study_evidence_dock")
                dock.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable |
                                 QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable)
                dock.setWidget(window.study_panel)
                window.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, dock)
                window.menudict["Display"].addAction(dock.toggleViewAction())
                window.study_dock = dock
                image_menu = window.menuBar().addMenu('Save image…')
                save_action = image_menu.addAction('Current 3D view — OpenGL PNG…')
                save_action.triggered.connect(lambda _checked=False:
                    export_dialog(window, '3D PyMOL view', self._export_current_pymol_image))
                ray_action = image_menu.addAction('Ray-traced 3D PNG…')
                ray_action.triggered.connect(lambda _checked=False:
                    export_dialog(window, 'ray-traced 3D PNG', lambda: self._export_current_pymol_image(ray=True)))
                window.resizeDocks([dock], [360], QtCore.Qt.Orientation.Horizontal)
                window.showMaximized()
                window.raise_()
                window.activateWindow()
                self.viewer_widget.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
            except Exception as exc:
                if self._detached_structure_window is not None:
                    self._detached_structure_window.close()
                QtWidgets.QMessageBox.warning(self, "Full PyMOL unavailable", str(exc))

        def detach_embedded_viewer(self) -> None:
            """Move the one live embedded engine into a maximized, resizable window."""
            if self.viewer_widget is None or self.live_layout is None:
                return
            self._close_interaction_review()
            if self.linked_pose_panel._detached_window is not None:
                self.linked_pose_panel._detached_window.close()
            existing = self._detached_structure_window
            if existing is not None:
                existing.raise_()
                existing.activateWindow()
                return

            dialog = QtWidgets.QDialog(self, QtCore.Qt.WindowType.Window)
            dialog.setObjectName("detached_embedded_pymol_window")
            dialog.setWindowTitle("Docking Universal — Interactive structure")
            layout = QtWidgets.QVBoxLayout(dialog)
            layout.setContentsMargins(0, 0, 0, 0)
            controls = QtWidgets.QHBoxLayout()
            controls.setContentsMargins(10, 7, 10, 7)
            title = QtWidgets.QLabel(
                "Interactive structure — same live session, scene, and selections"
            )
            title_font = title.font()
            title_font.setBold(True)
            title.setFont(title_font)
            return_button = QtWidgets.QPushButton("Return to workspace")
            return_button.setObjectName("return_embedded_viewer_button")
            controls.addWidget(title, 1)
            controls.addWidget(return_button)
            layout.addLayout(controls)

            split_sizes = self.pose_split.sizes()
            layout.addWidget(self.viewer_widget, 1)
            self._detached_structure_window = dialog

            restored = {"done": False}

            def restore_viewer(*_args) -> None:
                if restored["done"]:
                    return
                restored["done"] = True
                layout.removeWidget(self.viewer_widget)
                self.pose_split.insertWidget(0, self.viewer_widget)
                self.pose_split.setSizes(split_sizes)
                self.viewer_widget.show()
                self._detached_structure_window = None
                self.review_tabs.setCurrentWidget(self.live_page)
                self.raise_()
                self.activateWindow()

            dialog.finished.connect(restore_viewer)
            return_button.clicked.connect(dialog.close)
            QtGui.QShortcut(QtGui.QKeySequence("Escape"), dialog).activated.connect(dialog.close)
            dialog.showMaximized()
            self.viewer_widget.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)


        @staticmethod
        def _scenes_for_report_asset(path: Path | None) -> list[tuple[str, Path]]:
            if path is None:
                return []
            name = path.name
            if name.endswith("_top3_3d_snapshots.png") or name.endswith(
                "_selected_interactions_ABC.png"
            ):
                manifest = (
                    path.with_suffix(".manifest.json")
                    if name.endswith("_top3_3d_snapshots.png")
                    else path.with_name(
                        name.replace(
                            "_selected_interactions_ABC.png",
                            "_top3_3d_snapshots.manifest.json",
                        )
                    )
                )
                try:
                    sources = json.loads(manifest.read_text()).get("sources") or []
                except (OSError, json.JSONDecodeError):
                    sources = []
                scenes = []
                for index, source in enumerate(sources[:3]):
                    candidate = Path(str(source)).with_suffix(".pse")
                    if candidate.is_file():
                        scenes.append((f"Panel {'ABC'[index]}", candidate.resolve()))
                return scenes
            if name == "cavity_panels_AB.png":
                candidate = path.with_name("cavity_panel_B_structure.pse")
            elif name in {"control_panels_AB.png", "control_panel_B_overlay.png"}:
                candidate = path.with_name("control_panel_B_overlay.pse")
            elif "pocket_evidence_site_" in name and name.endswith("_AB.png"):
                candidate = path.with_suffix(".pse")
            elif name.endswith("_panels_AB.png"):
                candidate = path.with_name(name.replace("_panels_AB.png", "_panel_B_representatives.pse"))
            elif name in {"cavity_selected_box.png", "cavity_panel_B_structure.png"}:
                candidate = path.with_suffix(".pse")
            else:
                return []
            return [("3D panel", candidate.resolve())] if candidate.is_file() else []

        @staticmethod
        def _scene_for_report_asset(path: Path | None) -> Path | None:
            scenes = StudyWindow._scenes_for_report_asset(path)
            return scenes[0][1] if len(scenes) == 1 else None


        def _build_workflow_navigation_dock(self) -> None:
            navigation_panel = QtWidgets.QWidget()
            navigation_layout = QtWidgets.QVBoxLayout(navigation_panel)
            navigation_layout.setContentsMargins(8, 8, 8, 8)
            self.next_required_action = QtWidgets.QLabel()
            self.next_required_action.setObjectName("next_required_action")
            self.next_required_action.setWordWrap(True)
            self.next_required_action.setStyleSheet(
                "QLabel { background: #eef5ff; color:#172b3a; border: 1px solid #8bb7e8; "
                "border-radius: 4px; padding: 7px; font-weight: 600; }"
            )
            navigation_layout.addWidget(self.next_required_action)
            self.next_required_action.hide()
            self.active_stage_status = QtWidgets.QLabel("No scientific stage is running")
            self.active_stage_status.setObjectName("active_stage_status")
            self.active_stage_status.setWordWrap(True)
            navigation_layout.addWidget(self.active_stage_status)
            self.active_stage_progress = QtWidgets.QProgressBar()
            self.active_stage_progress.setObjectName("active_stage_progress")
            self.active_stage_progress.setTextVisible(True)
            navigation_layout.addWidget(self.active_stage_progress)
            self.show_complete_logs_button = QtWidgets.QPushButton("Show complete logs")
            self.show_complete_logs_button.clicked.connect(
                lambda: self._set_auxiliary_dock_visible(
                    self.logs_dock, QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, True,
                )
            )
            navigation_layout.addWidget(self.show_complete_logs_button)
            self.show_complete_logs_button.hide()
            self.workflow_navigation = QtWidgets.QListWidget()
            self.workflow_navigation.setObjectName("workflow_navigation")
            steps = (
                ("1  Study setup", "study_setup_dock"),
                ("2  Prepare & detect", "preparation_progress"),
                ("3  Review & decide", "central"),
                ("4  Finalize protocol", "protocol_finalization_dock"),
                ("5  Screen ligands", "locked_protocol_screening_dock"),
                ("6  Results review", "screening_results_dock"),
            )
            for label, target in steps:
                item = QtWidgets.QListWidgetItem(label)
                item.setData(QtCore.Qt.UserRole, target)
                self.workflow_navigation.addItem(item)
            navigation_layout.addWidget(self.workflow_navigation)
            self.workflow_navigation.currentItemChanged.connect(
                lambda current, _previous: self._activate_workflow_target(
                    current.data(QtCore.Qt.UserRole) if current else "central"
                )
            )
            self.workflow_navigation_dock = self._dock(
                "Scientific Workflow", navigation_panel,
                QtCore.Qt.LeftDockWidgetArea, "workflow_navigation_dock",
            )
            self.workflow_navigation_dock.setFeatures(
                QtWidgets.QDockWidget.DockWidgetClosable
                | QtWidgets.QDockWidget.DockWidgetMovable
                | QtWidgets.QDockWidget.DockWidgetFloatable
            )
            self.workflow_action = self._add_auxiliary_dock_action(
                "Scientific workflow", self.workflow_navigation_dock,
                QtCore.Qt.DockWidgetArea.LeftDockWidgetArea,
            )
            self.workflow_action.setToolTip("Show or hide the chronological workflow steps")
            self.view_toolbar.insertAction(self.scientific_detail_action, self.workflow_action)
            self.splitDockWidget(
                self.workflow_navigation_dock, self.study_setup_dock, QtCore.Qt.Vertical,
            )
            self.protocol_finalization_dock.hide()
            self.screening_dock.hide()
            self.workflow_navigation_controller = WorkflowNavigationController({
                "study_setup_dock": self.study_setup_dock,
                "protocol_finalization_dock": self.protocol_finalization_dock,
                "locked_protocol_screening_dock": self.screening_dock,
            })
            self._configure_stable_workflow_surfaces()
            self._stabilize_workflow_rail()
            self.workflow_navigation.setCurrentRow(0)

        def _configure_stable_workflow_surfaces(self) -> None:
            """Use fixed dock shells; stage navigation swaps pages, never dock geometry."""
            self.workflow_stage_stack = QtWidgets.QStackedWidget()
            self.workflow_stage_stack.setObjectName("workflow_stage_stack")
            self.workflow_stage_stack.setMinimumWidth(0)
            self.workflow_stage_stack.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Expanding,
            )
            self.workflow_stage_blank = QtWidgets.QWidget()
            blank_layout = QtWidgets.QVBoxLayout(self.workflow_stage_blank)
            blank_message = QtWidgets.QLabel(
                "This stage uses the central scientific-review workspace.\n\n"
                "Review the figures, interactive structure, and retained evidence there."
            )
            blank_message.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            blank_message.setWordWrap(True)
            blank_layout.addWidget(blank_message, 1)
            self.preparation_progress_panel = PreparationProgressPanel()
            self.preparation_progress_panel.cancelRequested.connect(self.cancel_active_job)
            self.preparation_progress_panel.logsRequested.connect(
                lambda: self._set_auxiliary_dock_visible(
                    self.logs_dock, QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, True,
                )
            )
            self.preparation_progress_panel.artifactsRequested.connect(
                lambda: self._set_auxiliary_dock_visible(
                    self.reports_dock, QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, True,
                )
            )
            for panel in (
                self.study_setup_panel,
                self.preparation_progress_panel,
                self.protocol_finalization_panel,
                self.screening_setup_panel,
                self.workflow_stage_blank,
            ):
                self.workflow_stage_stack.addWidget(panel)
            self.study_setup_dock.setWindowTitle("Workflow Stage")
            self.study_setup_dock.setWidget(QtWidgets.QWidget())
            self.stage_form_scroll = QtWidgets.QScrollArea()
            self.stage_form_scroll.setObjectName("central_stage_form")
            self.stage_form_scroll.setWidgetResizable(True)
            self.stage_form_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            self.stage_form_scroll.setWidget(self.workflow_stage_stack)
            self.stage_form_heading = QtWidgets.QLabel("1. Study setup")
            self.stage_form_heading.setStyleSheet("font-size: 18px; font-weight: 600;")
            self.centralWidget().layout().insertWidget(4, self.stage_form_heading)
            self.centralWidget().layout().insertWidget(5, self.stage_form_scroll, 1)
            self.protocol_finalization_dock.setWidget(QtWidgets.QWidget())
            self.screening_dock.setWidget(QtWidgets.QWidget())
            self.protocol_finalization_dock.hide()
            self.screening_dock.hide()
            self.study_setup_dock.hide()
            self._workflow_stage_pages = {
                "study_setup_dock": self.study_setup_panel,
                "preparation_progress": self.preparation_progress_panel,
                "protocol_finalization_dock": self.protocol_finalization_panel,
                "locked_protocol_screening_dock": self.screening_setup_panel,
                "central": self.workflow_stage_blank,
                "screening_results_dock": self.workflow_stage_blank,
            }

            self.right_review_stack = QtWidgets.QStackedWidget()
            self.right_review_stack.setObjectName("right_review_stack")
            self.right_review_stack.setMinimumWidth(0)
            self.right_review_stack.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Expanding,
            )
            self.right_review_blank = QtWidgets.QWidget()
            self.right_review_stack.addWidget(self.pocket_evidence_panel)
            self.right_review_stack.addWidget(self.results_review_panel)
            self.right_review_stack.addWidget(self.right_review_blank)
            self.pocket_evidence_dock.setWindowTitle("Scientific Evidence")
            self.pocket_evidence_dock.setMinimumWidth(320)
            self.pocket_evidence_dock.setWidget(self.right_review_stack)
            self.screening_results_dock.setWidget(QtWidgets.QWidget())
            self.screening_results_dock.hide()
            self.pocket_evidence_dock.show()

        def _stabilize_workflow_rail(self) -> None:
            """Keep stage changes from re-scaling the scientific workspace."""
            docks = (self.workflow_navigation_dock,)
            for dock in docks:
                dock.setMinimumWidth(self.WORKFLOW_RAIL_MINIMUM_WIDTH)
                dock.setMaximumWidth(300)
            self.workflow_navigation.setUniformItemSizes(True)
            self.resizeDocks(
                list(docks), [self.WORKFLOW_RAIL_WIDTH] * len(docks),
                QtCore.Qt.Orientation.Horizontal,
            )

        def _update_preparation_progress_panel(self, state) -> None:
            panel = self.preparation_progress_panel
            jobs = [
                job for job in state.jobs
                if job.stage in {"preparation_and_pocket_detection", "control_validation"}
            ]
            job = jobs[-1] if jobs else None
            pending_review = any(
                decision.kind == "select_pockets" for decision in state.pending_decisions
            )
            preparation_decision = next((
                decision for decision in state.pending_decisions
                if decision.kind != "select_pockets"
                and decision.continuation.get("checkpoint")
                == "rerun_preparation_with_histidine_template"
            ), None)
            if job is None:
                panel.status.setText(
                    "Preparation has not started. Complete Study setup, then start receptor preparation."
                )
                panel.progress.setRange(0, 100)
                panel.progress.setValue(0)
                panel.progress.setFormat("Not started")
            elif preparation_decision is not None:
                panel.status.setText(
                    "Receptor preparation paused at a required molecular-model decision. "
                    "Open Review preparation decision to inspect the retained evidence and choose "
                    "whether to resume this same preparation stage."
                )
                panel.progress.setRange(0, 100)
                panel.progress.setValue(max(1, int((job.progress or 0.0) * 100)))
                panel.progress.setFormat("Paused — scientific decision required")
            elif pending_review:
                panel.status.setText(
                    "Preparation and site detection completed. Candidate regions and experimental "
                    "evidence are retained and awaiting scientific review."
                )
                panel.progress.setRange(0, 100)
                panel.progress.setValue(100)
                panel.progress.setFormat("Completed — review required")
            elif job.status.value == "running":
                panel.status.setText(
                    job.progress_message
                    or ("Known-ligand redocking is running…" if job.stage == "control_validation"
                        else "The scientific host is preparing the receptor and detecting candidate sites.")
                )
                if job.progress_total is not None and job.progress_completed is not None:
                    panel.progress.setRange(0, job.progress_total)
                    panel.progress.setValue(job.progress_completed)
                    panel.progress.setFormat(f"Milestones %v/{job.progress_total}")
                else:
                    panel.progress.setRange(0, 0)
                    panel.progress.setFormat("Running")
            else:
                if job.stage == "control_validation" and job.status.value == "completed":
                    approved = state.workflow_data.get("latest_control_status") == "approved"
                    panel.status.setText(
                        "Known-ligand control passed; a validated protocol is ready."
                        if approved else
                        "Known-ligand control finished but did not approve a protocol. Review the control report."
                    )
                else:
                    panel.status.setText(
                        f"Preparation status: {job.status.value.replace('_', ' ')}"
                        + (f" — {job.error}" if job.error else "")
                    )
                panel.progress.setRange(0, 100)
                panel.progress.setValue(100 if job.status.value == "completed" else 0)
                panel.progress.setFormat(job.status.value.replace("_", " ").title())
            panel.cancel_button.setEnabled(bool(job and job.status.value == "running"))

            candidates = state.workflow_data.get("pocket_candidates", [])
            preparation_root = state.workflow_data.get("preparation_root")
            retained = []
            for artifact in state.artifacts:
                if artifact.kind in {
                    "prepared_receptor_structure", "pocket_coordinates", "pocket_evidence",
                    "preliminary_report", "run_log",
                }:
                    retained.append(f"• {artifact.description or artifact.kind}: {Path(artifact.path).name}")
            lines = []
            if preparation_root:
                lines.append(f"Preparation root: {preparation_root}")
            if candidates:
                detectors = sorted({
                    str((candidate.get("evidence") or {}).get("detector", "unknown"))
                    for candidate in candidates
                })
                lines.append(f"Candidate regions: {len(candidates)}")
                lines.append(f"Pocket detector evidence: {', '.join(detectors)}")
            if retained:
                lines.extend(["", "Retained outputs", *retained])
            elif job is not None:
                lines.append("Retained outputs will be listed as the scientific host registers them.")
            panel.summary.setPlainText("\n".join(lines))

        def _update_workflow_progress(self, state) -> None:
            """Expose lifecycle progress without skipping a scientific decision."""
            pending_pockets = any(item.kind == "select_pockets" for item in state.pending_decisions)
            preparation_started = any(
                job.stage in {"preparation_and_pocket_detection", "control_validation"}
                for job in state.jobs
            )
            preparation_done = pending_pockets or bool(state.selected_pocket_ids) or any(
                job.stage in {"preparation_and_pocket_detection", "control_validation"}
                and job.status.value == "completed"
                for job in state.jobs
            )
            control_path = (state.workflow_data.get("study_setup") or {}).get("pathway") == "control"
            site_first_control = bool((state.workflow_data.get("study_setup") or {}).get("site_review_first"))
            reuse_path = (state.workflow_data.get("study_setup") or {}).get("pathway") == "reuse"
            regions_approved = (
                state.workflow_data.get("latest_control_status") == "approved"
                if control_path and not site_first_control else bool(state.selected_pocket_ids and not pending_pockets)
            )
            has_bundle = any(
                artifact.kind == "protocol_bundle" and Path(artifact.path).is_file()
                for artifact in state.artifacts
            )
            screening_started = bool(
                state.workflow_data.get("latest_screening_output")
                or any(job.stage == "screening" for job in state.jobs)
            )
            screening_done = bool(
                state.workflow_data.get("latest_screening_output")
                and state.workflow_data.get("latest_screening_status") == "completed"
            )
            latest_job = state.jobs[-1] if state.jobs else None
            failed_job = latest_job if latest_job and latest_job.status.value in {
                "failed", "cancelled", "interrupted",
            } else None

            labels = (
                "Study setup",
                "Known-ligand control" if control_path else "Prepare & detect",
                "Pose-recovery assessment" if control_path else "Review & decide",
                "Validated protocol" if control_path else "Finalize protocol",
                "Screen ligands",
                "Results review",
            )
            if site_first_control:
                labels = ("Study setup", "Prepare & gather evidence", "Review & decide",
                          "Control & protocol", "Screen ligands", "Results review")
            complete = (
                preparation_started or preparation_done,
                preparation_done,
                regions_approved,
                has_bundle,
                screening_done,
                screening_done,
            )

            available = (
                True,
                preparation_started,
                preparation_done,
                regions_approved,
                has_bundle,
                screening_started,
            )
            if reuse_path:
                labels = ("Saved protocol import", "Preparation (inherited)", "Regions (inherited)",
                          "Protocol settings (locked)", "Screen ligands", "Results review")
                complete = (has_bundle, False, False, False, screening_done, screening_done)
                available = (True, False, False, False, has_bundle, screening_started)

            active_row = 0
            if not self.output_directory.text().strip():
                next_action = "Choose a study output folder, then load or download your receptor structure."
            elif not Path(self.input_pdb.text().strip()).is_file():
                next_action = "Choose a structure file, or enter a PDB ID and click Fetch RCSB ID."
            else:
                next_action = "Review the deposited structure information and choose your pathway, then start preparation."
            if pending_pockets:
                active_row = 2
                next_action = "Scientific decision required: review the evidence and approve one or more docking regions."
            elif state.active_job:
                stage_rows = {
                    "preparation_and_pocket_detection": 1,
                    "control_validation": 3 if site_first_control else 1,
                    "final_report": 3,
                    "screening": 4,
                }
                active_row = stage_rows.get(state.active_job.stage, 0)
                next_action = (
                    state.active_job.progress_message
                    or f"Running {state.active_job.stage.replace('_', ' ')}…"
                )
            elif failed_job and not screening_done:
                active_row = {
                    "preparation_and_pocket_detection": 1,
                    "final_report": 3,
                    "screening": 4,
                }.get(failed_job.stage, 0)
                next_action = (
                    f"{failed_job.stage.replace('_', ' ').title()} {failed_job.status.value}. "
                    f"{failed_job.error or 'Inspect the retained logs before retrying.'}"
                )
            elif regions_approved and not has_bundle:
                active_row = 3
                next_action = "Review the locked settings and finalize the report and .duprotocol bundle."
                if site_first_control and not state.workflow_data.get("latest_control_status"):
                    next_action = "Sites approved. Review the tested-site scope, then explicitly start the known-ligand control."
                elif site_first_control:
                    next_action = "Review the site-specific control result. Additional or unvalidated sites require explicit exploratory protocol approval."
            elif has_bundle and not screening_started:
                active_row = 4
                validated_scope = not site_first_control or (state.workflow_data.get("control_site_review") or {}).get("all_selected_sites_validated")
                next_action = "Protocol validated. Choose ligands to begin sequential screening." if control_path and validated_scope else "Protocol finalized. Choose ligands to begin sequential screening."
                if reuse_path:
                    next_action = "Saved protocol imported. Choose compounds to begin sequential screening; its receptor and settings remain locked."
            elif control_path and state.workflow_data.get("latest_control_status") == "not_approved":
                active_row = 2
                next_action = "Control completed but pose recovery did not pass. Review its report; no validated protocol was issued."
            elif screening_started and not screening_done:
                active_row = 4
                next_action = "Screening is in progress; review retained progress and logs here."
            elif screening_done:
                active_row = 5
                next_action = "Screening complete. Review poses, clusters, interactions, and reports."
            elif preparation_done:
                active_row = 2
                next_action = "Review the detected regions and their supporting evidence."

            for row, label in enumerate(labels):
                item = self.workflow_navigation.item(row)
                marker = "✓" if complete[row] else ("●" if row == active_row else "○")
                item.setText(f"{marker}  {row + 1}  {label}")
                flags = item.flags()
                if available[row]:
                    item.setFlags(
                        flags
                        | QtCore.Qt.ItemFlag.ItemIsEnabled
                        | QtCore.Qt.ItemFlag.ItemIsSelectable
                    )
                else:
                    item.setFlags(
                        flags
                        & ~QtCore.Qt.ItemFlag.ItemIsEnabled
                        & ~QtCore.Qt.ItemFlag.ItemIsSelectable
                    )
                item.setToolTip(
                    "Completed — retained details remain available"
                    if complete[row]
                    else "Current stage"
                    if row == active_row
                    else "Available"
                    if available[row]
                    else "Complete the preceding scientific stage first"
                )
                if reuse_path and row in (1, 2, 3):
                    item.setToolTip("Inherited unchanged from the saved protocol, not performed in this study. Review the imported record in Study setup.")
            phase = (
                "results" if screening_done
                else "screening" if screening_started or has_bundle
                else "finalization" if regions_approved
                else "review" if preparation_done
                else "preparation" if preparation_started
                else "setup"
            )
            if phase != self._workflow_phase:
                self._workflow_phase = phase
                self.workflow_navigation.setCurrentRow(active_row)
            self.next_required_action.setText(f"Next required action\n{next_action}")
            self._update_preparation_progress_panel(state)
            if pending_pockets:
                feedback_heading = "Scientific decision required"
            elif state.active_job:
                feedback_heading = "Scientific workflow in progress"
            elif failed_job and not screening_done:
                feedback_heading = "Scientific stage did not complete"
            elif screening_done:
                feedback_heading = "Screening complete — review the evidence"
            else:
                feedback_heading = "Next scientific action"
            self.feedback_heading.setText(feedback_heading)
            self.feedback_text.setText(next_action)
            running = bool(state.active_job and state.active_job.status.value in {"running", "queued"})
            self.running_indicator.setVisible(running)
            self.running_elapsed.setVisible(running)
            if running:
                stage_name = {
                    "preparation_and_pocket_detection": "Preparing receptor and detecting pockets",
                    "control_validation": "Running known-ligand redocking",
                    "final_report": "Generating report and protocol",
                    "screening": "Screening ligands",
                    "pose_interaction": "Calculating pose interactions",
                }.get(state.active_job.stage, state.active_job.stage.replace("_", " ").capitalize())
                self.feedback_heading.setText(f"RUNNING — {stage_name}")
                self._update_running_elapsed(state)
            feedback_colors = (
                ("#fff1b8", "#c99a16") if pending_pockets
                else ("#dceeff", "#2478bd") if running
                else ("#fff1e8", "#c98963") if failed_job and not screening_done and not state.active_job
                else ("#e8f6ec", "#64a878") if screening_done
                else ("#eef5ff", "#8bb7e8")
            )
            self.feedback_card.setStyleSheet(
                "QFrame#scientific_feedback_card { "
                f"background:{feedback_colors[0]}; border:1px solid {feedback_colors[1]}; "
                "border-radius:5px; }"
                "QFrame#scientific_feedback_card QLabel {color:#172b3a;background:transparent;}"
            )
            active = state.active_job
            if active is None:
                self.active_stage_status.setText("No scientific stage is running")
                self.active_stage_progress.hide()
            elif active.status.value == "waiting_for_decision":
                self.active_stage_status.setText(
                    f"{active.stage.replace('_', ' ').title()} · waiting for your decision"
                )
                self.active_stage_progress.hide()
            else:
                self.active_stage_status.setText(
                    active.progress_message
                    or f"{active.stage.replace('_', ' ').title()} · {active.status.value}"
                )
                self.active_stage_progress.show()
                if active.progress_total is not None and active.progress_completed is not None:
                    self.active_stage_progress.setRange(0, active.progress_total)
                    self.active_stage_progress.setValue(active.progress_completed)
                    self.active_stage_progress.setFormat(
                        f"Milestones %v/{active.progress_total}" if active.stage != "screening"
                        else f"Outputs %v/{active.progress_total} planned"
                    )
                else:
                    self.active_stage_progress.setRange(0, 0)

        def _activate_workflow_target(self, target: str) -> None:
            self._workflow_target = target
            self._update_stage_review_visibility()
            browser = getattr(self._detached_structure_window, "study_panel", None)
            if browser is not None:
                browser.refresh()
            page = self._workflow_stage_pages.get(target, self.workflow_stage_blank)
            self.workflow_stage_stack.setCurrentWidget(page)
            stage_titles = {
                "study_setup_dock": "Study Setup and Preparation",
                "preparation_progress": "Prepare and Detect",
                "protocol_finalization_dock": "Finalize Protocol",
                "locked_protocol_screening_dock": "Screen Ligands",
                "central": "Review and Decide",
                "screening_results_dock": "Results Review",
            }
            self.study_setup_dock.setWindowTitle(
                stage_titles.get(target, "Workflow Stage")
            )
            self.stage_form_heading.setText({
                "study_setup_dock": "1. Study setup",
                "preparation_progress": "2. Prepare and detect",
                "protocol_finalization_dock": "4. Finalize protocol",
                "locked_protocol_screening_dock": "5. Screen ligands",
            }.get(target, ""))
            if target == "protocol_finalization_dock" and (self.state.workflow_data.get("study_setup") or {}).get("site_review_first"):
                self.stage_form_heading.setText("4. Control and protocol")
            if target == "screening_results_dock":
                self.right_review_stack.setCurrentWidget(self.results_review_panel)
                if self.screening_results_dock.isFloating():
                    self.screening_results_dock.raise_()
                    self.screening_results_dock.activateWindow()
            else:
                if target == "central":
                    self.right_review_stack.setCurrentWidget(self.pocket_evidence_panel)
                    if self.viewer_widget is not None:
                        self.review_tabs.setCurrentWidget(self.live_page)
                        self._schedule_initial_candidate_review()
                    self.centralWidget().setFocus()
                else:
                    self.right_review_stack.setCurrentWidget(self.right_review_blank)

        def _update_stage_review_visibility(self) -> None:
            target = getattr(self, "_workflow_target", "study_setup_dock")
            review = target in {"central", "screening_results_dock"}
            pocket_review = target == "central"
            for widget in (
                self.workspace_heading, self.review_tabs,
            ):
                widget.setVisible(review)
            embedded = self.viewer_widget is not None and self.review_tabs.currentWidget() is self.live_page
            self.workspace_context.setVisible(review and not embedded)
            self.central_selection_status.setVisible(review and not embedded)
            self.pymol_controls.setVisible(review and (embedded or self.viewer_coordinator is not None))
            self.candidates.setVisible(pocket_review)
            self.region_approval_controls.setVisible(pocket_review)
            if hasattr(self, "stage_form_scroll"):
                self.stage_form_heading.setVisible(not review)
                self.stage_form_scroll.setVisible(not review)
                self.study_setup_dock.hide()
                self.pocket_evidence_dock.setVisible(review)
            self.reset_view_button.setVisible(self.reset_view_button.isEnabled())
            self.decision_synopsis_button.setVisible(self.decision_synopsis_button.isEnabled())
            self.full_synopsis_button.setVisible(self.full_synopsis_button.isEnabled())

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

        def _add_auxiliary_dock_action(self, label, dock, area):
            action = self.view_toolbar.addAction(label)
            action.setCheckable(True)
            action.setChecked(dock.isVisible())
            action.triggered.connect(
                lambda checked, target=dock, target_area=area:
                self._set_auxiliary_dock_visible(target, target_area, checked)
            )
            dock.visibilityChanged.connect(action.setChecked)
            return action

        def _set_auxiliary_dock_visible(self, dock, area, visible):
            """Toggle diagnostic docks without allowing them to cover the canvas."""
            if not visible:
                dock.hide()
                return
            if dock.isFloating():
                dock.setFloating(False)
            self.addDockWidget(area, dock)
            dock.show()
            dock.raise_()
            if area == QtCore.Qt.DockWidgetArea.BottomDockWidgetArea:
                target = max(150, min(260, self.height() // 3))
                self.resizeDocks([dock], [target], QtCore.Qt.Orientation.Vertical)
            else:
                target = max(240, min(360, self.width() // 4))
                self.resizeDocks([dock], [target], QtCore.Qt.Orientation.Horizontal)

        def _apply_retained_study_setup(self, state) -> None:
            """Render accepted setup from scientific state and lock it in place."""
            setup = state.workflow_data.get("study_setup")
            if not isinstance(setup, dict) and any(
                job.stage == "preparation_and_pocket_detection" for job in state.jobs
            ):
                source = next((
                    artifact for artifact in state.artifacts
                    if artifact.kind == "source_receptor_structure"
                ), None)
                preparation_root = state.workflow_data.get("preparation_root")
                candidates = state.workflow_data.get("pocket_candidates") or []
                detector = next((
                    item.get("evidence", {}).get("detector")
                    for item in candidates
                    if item.get("evidence", {}).get("detector")
                ), "auto")
                evidence = state.workflow_data.get("pdb_pocket_evidence") or {}
                setup = {
                    "input_pdb": source.path if source else "Unavailable in this older record",
                    "working_directory": (
                        str(Path(str(preparation_root)).parent)
                        if preparation_root else "Unavailable in this older record"
                    ),
                    "site_mode": "pockets",
                    "ligand_resname": None,
                    "pocket_engine": detector,
                    "pdb_pocket_evidence": (
                        "related-structures" if evidence.get("mode") == "related-structures" else "off"
                    ),
                    "record_origin": "reconstructed_from_retained_artifacts",
                }
            locked = bool(setup) or any(
                job.stage == "preparation_and_pocket_detection" for job in state.jobs
            )
            self.study_setup_panel.set_locked(locked)
            if not isinstance(setup, dict):
                return
            signature = json.dumps(setup, sort_keys=True, default=str)
            if signature == self._retained_setup_signature:
                return
            self._retained_setup_signature = signature
            if setup.get("pathway") == "reuse":
                self.study_setup_panel.protocol_bundle.setText(str(setup['protocol_bundle']))
                self._restore_combo(self.study_pathway, "reuse")
                imported = state.workflow_data.get('protocol_import') or {}
                from ..reporting import engine_display_name
                self.study_setup_panel.protocol_note.setText(
                    f"Imported target: {imported.get('target', 'Not recorded')} · "
                    f"{engine_display_name(imported.get('engine', 'Not recorded'))} · "
                    f"{imported.get('region_count', '?')} locked docking region(s). "
                    "Receptor, regions and settings are inherited unchanged. No preparation was repeated. "
                    + ("Exploratory protocol: no pose-recovery control. "
                       if imported.get('exploratory_authorization_required') else "Pose-recovery control recorded in the saved bundle. ")
                    + "Select compounds in Screen ligands."
                )
                return
            if setup.get("record_origin") == "reconstructed_from_retained_artifacts":
                self.study_setup_panel.lock_notice.setText(
                    "This completed study predates the setup record. Available values were recovered "
                    "from saved study files and are read-only. Create a new study to change them."
                )
            else:
                self.study_setup_panel.lock_notice.setText(
                    "This source is part of the retained study record and is read-only. "
                    "Create a new study to change it."
                )
            self.input_pdb.setText(str(setup.get("input_structure") or setup.get("input_pdb") or ""))
            from ..services.coordinate_evidence import read_retained_evidence
            metadata_path = setup.get("structure_input_metadata")
            evidence = read_retained_evidence(metadata_path) if metadata_path else None
            self.study_setup_panel.set_coordinate_evidence(evidence)
            self.output_directory.setText(str(setup.get("working_directory") or ""))
            self._restore_combo(self.site_mode, setup.get("site_mode", "pockets"))
            self._restore_combo(self.study_pathway, setup.get("pathway", "exploratory"))
            self._restore_combo(self.control_engine, setup.get("engine", "vina"))
            self._restore_combo(self.control_tier, setup.get("control_tier", "quick"))
            self._restore_combo(self.pocket_engine, setup.get("pocket_engine", "auto"))
            self.study_setup_panel.predict_with_ligand.setChecked(setup.get("predict_pockets_with_ligand", False))
            self.study_setup_panel.pdb_evidence.setChecked(
                setup.get("pdb_pocket_evidence", "related-structures") == "related-structures"
            )
            resname = str(setup.get("ligand_resname") or "")
            if resname:
                identity = {
                    "resname": resname,
                    "chain_id": str(setup.get("ligand_chain_id") or ""),
                    "residue_number": str(setup.get("ligand_residue_number") or ""),
                    "insertion_code": str(setup.get("ligand_insertion_code") or ""),
                    "altloc": str(setup.get("ligand_altloc") or ""),
                }
                location = ""
                if identity["chain_id"] and identity["residue_number"]:
                    location = (
                        f" — chain {identity['chain_id']}, residue "
                        f"{identity['residue_number']}{identity['insertion_code']}"
                    )
                    if identity["altloc"]:
                        location += f"; altloc {identity['altloc']}"
                self.ligand_resname.clear()
                self.ligand_resname.addItem(f"{resname}{location}", identity)
                self.ligand_resname.setCurrentIndex(0)
            else:
                self.ligand_resname.clear()
            self.study_setup_panel.set_locked(True)

        def _update_running_elapsed(self, state) -> None:
            self._update_screening_elapsed(state)
            if not state.active_job or state.active_job.status.value not in {'running', 'queued'}:
                return
            text = 'Calculation active'
            if state.active_job.started_at:
                try:
                    started = datetime.fromisoformat(state.active_job.started_at.replace('Z', '+00:00'))
                    seconds = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
                    text += f' · elapsed {seconds // 60}:{seconds % 60:02d}'
                except (ValueError, TypeError):
                    pass
            self.running_elapsed.setText(text)

        def _update_screening_elapsed(self, state) -> None:
            from ..job_timing import elapsed_seconds, duration_text
            latest = next((job for job in reversed(state.jobs) if job.stage == 'screening'), None)
            label = self.screening_setup_panel.elapsed
            label.setVisible(latest is not None)
            if latest is None:
                label.clear()
                return
            seconds = elapsed_seconds(latest)
            status = latest.status.value.replace('_', ' ')
            timing = (('Elapsed ' if latest.status.value == 'running' else 'Total run time ')
                      + duration_text(seconds)) if seconds is not None else 'Run time unavailable (timestamps not recorded)'
            label.setText(f'Latest screening {status} · {timing}. Includes preparation, docking, analysis and reporting.')

        def _refresh_polled_state(self) -> None:
            """Poll authority; unchanged ticks must not rebuild tables or reload poses."""
            if getattr(self, '_stage_submission_in_progress', False):
                return  # preserve STARTING feedback until the host acknowledges
            if getattr(self.viewer_widget, '_du_ray_export_active', False):
                # Native ray tracing holds PyMOL's lock; keep GUI Cancel responsive.
                self._refresh_host_lifecycle()
                self._update_running_elapsed(self.state)
                return
            self.session.refresh()
            host_connected = self._host_connected()
            if (self.session.state.revision != self.state.revision
                    or host_connected != getattr(self, '_polled_host_connection', host_connected)):
                self.refresh()
                return
            self._refresh_host_lifecycle()
            self._refresh_viewer_lifecycle()
            self._update_running_elapsed(self.state)

        def _refresh_viewer_lifecycle(self) -> None:
            if getattr(self.viewer_widget, '_du_ray_export_active', False):
                return
            if self.viewer_coordinator is not None:
                if hasattr(self.viewer_coordinator, 'refresh_health'):
                    self.viewer_coordinator.refresh_health()
                self.session.set_viewer_state(
                    connected=bool(self.viewer_coordinator.connected),
                    report_view_available=bool(self.viewer_coordinator.connected
                        and getattr(self.viewer_coordinator, 'report_view_available', False)),
                    lifecycle=getattr(self.viewer_coordinator, 'status',
                        'connected' if self.viewer_coordinator.connected else 'disconnected'),
                    error=getattr(self.viewer_coordinator, 'last_error', None),
                )

        def refresh(self) -> None:
            self._refresh_host_lifecycle()
            self._polled_host_connection = self._host_connected()
            self.session.refresh()
            self.state = self.session.state
            state = self.state
            from ..services.pdb_lookup_status import lookup_status_for_state
            self.pocket_evidence_panel.set_lookup_status(lookup_status_for_state(state))
            self._apply_retained_study_setup(state)
            self._refresh_viewer_lifecycle()
            self.summary.setText(
                f"Study: {state.name}    Workflow: {state.workflow}    "
                f"Status: {state.completion_status.value}    Revision: {state.revision}"
            )
            self._update_workflow_progress(state)
            scene_artifacts = (
                tuple((artifact.kind, artifact.path, artifact.sha256) for artifact in state.artifacts),
                state.workflow_data.get('latest_control_output'),
            )
            if scene_artifacts != self._structure_scene_artifacts:
                self._refresh_structure_scenes(state)
                self._structure_scene_artifacts = scene_artifacts
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
            pocket_decision = next((
                decision for decision in pending if decision.kind == "select_pockets"
            ), None)
            self.approve_button.setEnabled(bool(
                self.host_controller.available and pocket_decision
            ))
            self.viewer_button.setEnabled(bool(
                self.viewer_widget is None
                and
                self.viewer_coordinator is not None
                and bool(getattr(self, "_selected_structure_scenes", None))
                and getattr(self.viewer_coordinator, "status", "disconnected") != "connecting"
            ))
            report_view_available = bool(
                self.viewer_coordinator
                and self.viewer_coordinator.connected
                and self.viewer_coordinator.report_view_available
            )
            self.reset_view_button.setEnabled(report_view_available)
            self.decision_synopsis_button.setEnabled(bool(pending))
            self.decision_synopsis_button.setText(
                "Review preparation decision…"
                if pending and pending[0].kind == "select_histidine_template"
                else "Decision synopsis"
            )
            self.full_synopsis_button.setEnabled(any(
                artifact.kind == "preliminary_report" and Path(artifact.path).is_file()
                for artifact in state.artifacts
            ))
            if self.viewer_coordinator is None:
                self.viewer_status.setText("Required structural viewer is not configured")
            active = state.active_job
            preparation_complete = any(
                job.stage == "preparation_and_pocket_detection" and job.status.value == "completed"
                for job in state.jobs
            )
            self.start_preparation_button.setEnabled(bool(
                self.host_controller.available and not active and not pending and not preparation_complete
                and not state.workflow_data.get("study_setup")
            ))
            self.cancel_job_button.setEnabled(bool(
                self.host_controller.available and active and active.status.value == "running"
            ))
            self.cancel_job_button.setVisible(self.cancel_job_button.isEnabled())
            self.results_review_action.setVisible(bool(state.workflow_data.get("latest_screening_output")))
            preparation_root = state.workflow_data.get("preparation_root")
            if preparation_root and not self.final_output_directory.text().strip():
                root = Path(str(preparation_root))
                self.final_output_directory.setText(str(root.parent / f"{state.study_id}_protocol"))
            has_bundle = any(
                artifact.kind == "protocol_bundle" and Path(artifact.path).is_file()
                for artifact in state.artifacts
            )
            final_report = next((
                artifact for artifact in state.artifacts
                if artifact.kind == "final_report" and Path(artifact.path).is_file()
            ), None)
            if final_report is None:
                final_report = next((artifact for artifact in state.artifacts
                                     if artifact.kind == "control_report" and Path(artifact.path).is_file()), None)
            bundle_artifact = next((
                artifact for artifact in state.artifacts
                if artifact.kind == "protocol_bundle" and Path(artifact.path).is_file()
            ), None)
            self.open_final_report_button.setEnabled(final_report is not None)
            self.open_bundle_location_button.setEnabled(bundle_artifact is not None)
            approved_regions = bool(state.selected_pocket_ids and not pending)
            setup = state.workflow_data.get("study_setup") or {}
            needs_control = bool(setup.get("site_review_first") and not state.workflow_data.get("latest_control_status"))
            control_preview, control_error = None, None
            if needs_control and approved_regions:
                from ..services.control_review import reviewed_control_inputs, NoControlSiteSelected
                try:
                    control_preview = reviewed_control_inputs(state)
                except NoControlSiteSelected as exc:
                    needs_control = False
                    control_error = str(exc)
                except ValueError as exc:
                    control_error = str(exc)
            description = "Review and approve sites first. No redocking has run."
            if control_preview:
                extra = control_preview['untested_box_labels']
                description = (
                    f"Run {setup['engine']} pose recovery for {control_preview['ligand_id']} in "
                    f"{control_preview['tested_box_label']} using the {setup['control_tier']} tier. "
                    "The reviewed receptor and box are reused; preparation and evidence lookup are not repeated. "
                    + ("Additional selected sites remain exploratory: " + ', '.join(extra) + '. '
                       "After the control, explicitly finalize an exploratory protocol to screen all selected sites."
                       if extra else "A passing control authorizes only this tested site, receptor, engine and settings.")
                    + (" Untested receptor-state variants also remain exploratory: "
                       + ', '.join(control_preview['untested_receptor_states']) + '.'
                       if control_preview['untested_receptor_states'] else '')
                )
            self.protocol_finalization_panel.set_control_mode(needs_control, description)
            self.finalize_button.setEnabled(bool(
                self.host_controller.available and approved_regions and not active and not has_bundle
                and (control_preview if needs_control else self.exploratory_approval.isChecked())
            ))
            if has_bundle:
                bundle = next(artifact for artifact in state.artifacts if artifact.kind == "protocol_bundle")
                self.finalization_status.setText(f"Reusable protocol complete: {bundle.path}")
            elif active and active.stage == "final_report":
                self.finalization_status.setText("Generating the final report and portable protocol bundle…")
            elif state.jobs and state.jobs[-1].stage == "final_report" and state.jobs[-1].status.value in {
                "failed", "cancelled", "interrupted",
            }:
                self.finalization_status.setText(
                    f"Finalization {state.jobs[-1].status.value}: "
                    f"{state.jobs[-1].error or 'inspect the retained logs before retrying.'}"
                )
            elif approved_regions:
                self.finalization_status.setText(
                    control_error or "Sites approved. Start the disclosed site-specific control when ready."
                    if needs_control else control_error or
                    (state.workflow_data.get('control_site_review') or {}).get('scope_warning') or
                    "Review the locked settings and explicitly authorize exploratory reuse to finalize."
                )
            if bundle_artifact and not self.screen_output.text().strip():
                self.screen_output.setText(str(Path(bundle_artifact.path).parent / f"{state.study_id}_screen"))
            self.preview_screening_button.setEnabled(bool(
                self.host_controller.available and bundle_artifact and not active
                and self.screen_ligands.text().strip() and self.screen_output.text().strip()
            ))
            self._update_screening_controls()
            if active and active.stage == "screening":
                message = active.progress_message or "Screening is starting…"
                self.screening_status.setText(message)
            elif state.workflow_data.get("latest_screening_output"):
                screening_result = state.workflow_data.get("latest_screening_status")
                latest_screen_job = next((
                    job for job in reversed(state.jobs) if job.stage == "screening"
                ), None)
                self.screening_status.setText(
                    f"Latest screening {screening_result}: {state.workflow_data['latest_screening_output']}"
                    + (f" — {latest_screen_job.error or 'Partial outputs retained; inspect the logs.'}"
                       if screening_result != "completed" and latest_screen_job
                       else "")
                )
            self._update_screening_elapsed(state)
            self._render_candidates(state)
            self._render_artifacts(state)
            self._render_screening_results(state)
            self._refresh_pending_pose_interaction(state)
            self._render_events()
            self._update_stage_review_visibility()
            self._sync_residue_highlight_actions()
            if self._exit_after_cancel and not active:
                self._exit_after_cancel = False
                QtCore.QTimer.singleShot(0, self.close)

        def _update_site_controls(self) -> None:
            ligand_mode = self.site_mode.currentData() == "ligand" or self.study_pathway.currentData() == "control"
            self.ligand_resname.setEnabled(ligand_mode)

        def approve_selected_regions(self) -> None:
            if not self.host_controller.available:
                return
            pending = [item for item in self.state.pending_decisions if item.kind == "select_pockets"]
            rows = sorted({index.row() for index in self.candidates.selectionModel().selectedRows()})
            if not pending or not rows:
                QtWidgets.QMessageBox.warning(self, "Selection required", "Select one or more docking regions first.")
                return
            setup = self.state.workflow_data.get("study_setup") or {}
            if setup.get("site_mode") == "ligand" and not all((
                setup.get("ligand_resname"), setup.get("ligand_chain_id"),
                setup.get("ligand_residue_number"),
            )):
                QtWidgets.QMessageBox.warning(
                    self,
                    "Exact ligand instance required",
                    "This retained ligand-guided setup identifies only a residue name. "
                    "If the structure contains repeated or symmetry-related instances, its "
                    "box can be centered between sites. Create a new study, detect deposited "
                    "ligands, and select one exact chain/residue instance before preparation.",
                )
                return
            candidates = self.state.workflow_data.get("pocket_candidates", [])
            selections = [str(candidates[row]["id"]) for row in rows]
            try:
                self.host_controller.resolve_pockets(
                    pending[0].id, selections, self.rationale.text().strip(),
                    self.state.revision,
                )
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "Approval rejected", str(exc))
                self.refresh()
                return
            self.refresh()

        def choose_input_pdb(self) -> None:
            path, _filter = QtWidgets.QFileDialog.getOpenFileName(
                self, "Choose receptor structure", "",
                "Macromolecular structures (*.cif *.mmcif *.pdb);;PDBx/mmCIF (*.cif *.mmcif);;Legacy PDB (*.pdb)",
            )
            if path:
                self.input_pdb.setText(path)
                self.refresh_input_coordinate_evidence()
                self.detect_bound_ligands(quiet=True)

        def refresh_input_coordinate_evidence(self) -> None:
            from ..services.coordinate_evidence import read_coordinate_evidence
            path = self.input_pdb.text().strip()
            try:
                evidence = read_coordinate_evidence(path) if path else None
            except Exception as exc:
                self.study_setup_panel.set_coordinate_evidence(None)
                self.statusBar().showMessage(f"Could not read deposited structure evidence: {exc}")
                return
            self.study_setup_panel.set_coordinate_evidence(evidence)

        def detect_bound_ligands(self, quiet: bool = False) -> list[str]:
            from ..services.bound_ligands import detect_bound_ligands

            path = Path(self.input_pdb.text().strip())
            if not path.is_file():
                if not quiet:
                    QtWidgets.QMessageBox.warning(
                        self, "Receptor required",
                        "Choose or fetch a receptor structure before detecting deposited ligands.",
                    )
                return []
            previous_data = self.ligand_resname.currentData()
            previous = self.ligand_resname.currentText().strip()
            try:
                candidates = detect_bound_ligands(path)
            except Exception as exc:
                if not quiet:
                    QtWidgets.QMessageBox.critical(self, "Ligand detection failed", str(exc))
                return []
            self.ligand_resname.clear()
            for candidate in candidates:
                for instance in candidate.instances:
                    self.ligand_resname.addItem(instance.label, instance.identity)
            if previous:
                matching = next((i for i in range(self.ligand_resname.count())
                                 if self.ligand_resname.itemData(i) == previous_data), -1)
                if matching >= 0:
                    self.ligand_resname.setCurrentIndex(matching)
            elif self.ligand_resname.count() == 1:
                self.ligand_resname.setCurrentIndex(0)
            else:
                self.ligand_resname.setCurrentIndex(-1)
                self.ligand_resname.setEditText("")
            if candidates:
                self.statusBar().showMessage(
                    f"Found {len(candidates)} deposited non-water residue type(s). "
                    "Choose the ligand or cofactor that defines the site."
                )
            elif not quiet:
                QtWidgets.QMessageBox.information(
                    self, "No deposited ligands found",
                    "This structure contains no deposited non-water ligand residues. Use predicted-pocket mode or enter an explicit residue name.",
                )
            return [instance.label for candidate in candidates for instance in candidate.instances]

        def fetch_input_pdb(self) -> str | None:
            from ..services.rcsb import canonical_pdb_id, download_pdb_entry

            raw = self.input_pdb.text().strip()
            output_text = self.output_directory.text().strip()
            try:
                pdb_id = canonical_pdb_id(raw)
            except ValueError as exc:
                QtWidgets.QMessageBox.warning(self, "PDB ID required", str(exc))
                return None
            if not output_text:
                QtWidgets.QMessageBox.warning(
                    self, "Output directory required",
                    "Choose a study output directory so the downloaded structure can be retained with the study.",
                )
                return None
            self.statusBar().showMessage(f"Downloading {pdb_id} from the RCSB Protein Data Bank…")
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            try:
                path = download_pdb_entry(pdb_id, Path(output_text) / "inputs")
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "RCSB download failed", str(exc))
                return None
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
            self.input_pdb.setText(str(path))
            self.refresh_input_coordinate_evidence()
            self.detect_bound_ligands(quiet=True)
            self.statusBar().showMessage(
                f"Downloaded {pdb_id} as retained mmCIF. Review the site-definition options, then prepare the receptor."
            )
            return str(path)

        def choose_output_directory(self) -> None:
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose study output directory")
            if path:
                self.output_directory.setText(path)

        def choose_final_output_directory(self) -> None:
            path = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Choose final protocol output directory",
            )
            if path:
                self.final_output_directory.setText(path)

        def choose_screen_ligand_file(self) -> None:
            path, _filter = QtWidgets.QFileDialog.getOpenFileName(
                self, "Choose compound library", "", "Ligand files (*.sdf *.mol *.csv *.tsv *.xlsx *.SDF *.MOL *.CSV *.TSV *.XLSX);;SMILES tables (*.csv *.tsv *.xlsx *.CSV *.TSV *.XLSX);;SDF libraries (*.sdf *.SDF);;MOL molecules (*.mol *.MOL)",
            )
            if path:
                self.screen_ligands.setText(path)
                if self.host_controller.available:
                    self.read_screening_library()

        def choose_screen_ligand_directory(self) -> None:
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose ligand SDF/MOL folder")
            if path:
                self.screen_ligands.setText(path)
                if self.host_controller.available:
                    self.read_screening_library()

        def choose_screen_output(self) -> None:
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose screening output directory")
            if path:
                self.screen_output.setText(path)

        def prepare_geostd_library(self, input_path: str, output_directory: str) -> str | None:
            """Resolve restraints and any explicitly reviewed PTM template bridge."""
            from ..services.geostd_components import (
                available_library, bundled_minimal_library, default_component_cache,
                download_components, missing_components, network_disclosure,
                modified_polymer_component_ids, reduce2_required_component_ids,
            )
            from ..services.meeko_template_bridge import (
                ccd_network_disclosure, ccd_path, default_ccd_cache,
                download_ccd_components,
            )

            self._prepared_meeko_template_file = None
            try:
                components = reduce2_required_component_ids(Path(input_path))
                modified_components = modified_polymer_component_ids(Path(input_path))
                available = available_library(components)
            except Exception as exc:
                QtWidgets.QMessageBox.critical(
                    self, "Component review failed",
                    f"The retained receptor components could not be reviewed safely: {exc}",
                )
                return None
            cache = default_component_cache()
            reference = available or (cache if cache.is_dir() else bundled_minimal_library())
            requested_geostd = () if available else missing_components(reference, components)

            missing_meeko = ()
            helper = Path(__file__).resolve().parents[2] / "docking-universal-meeko-template-bridge.py"
            scientific_python = getattr(self.host_client, "python_executable", None)
            if modified_components:
                if not scientific_python or not helper.is_file():
                    QtWidgets.QMessageBox.critical(
                        self, "PTM template review unavailable",
                        "The selected scientific Python or Meeko template helper is unavailable. "
                        "Preparation stopped before guessing modified-residue chemistry.",
                    )
                    return None
                inspected = subprocess.run(
                    [str(scientific_python), str(helper), "--list-missing", *modified_components],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                )
                if inspected.returncode != 0:
                    QtWidgets.QMessageBox.critical(
                        self, "PTM template review failed",
                        inspected.stderr.strip() or "Meeko template coverage could not be inspected.",
                    )
                    return None
                try:
                    missing_meeko = tuple(json.loads(inspected.stdout)["missing_components"])
                except (KeyError, TypeError, ValueError):
                    QtWidgets.QMessageBox.critical(
                        self, "PTM template review failed",
                        "The scientific template helper returned an invalid coverage record.",
                    )
                    return None

            ccd_cache = default_ccd_cache()
            requested_ccd = tuple(
                component for component in missing_meeko
                if not ccd_path(ccd_cache, component).is_file()
            )
            if requested_geostd or requested_ccd:
                disclosure = {
                    "geostd": network_disclosure(requested_geostd) if requested_geostd else None,
                    "ccd": ccd_network_disclosure(requested_ccd) if requested_ccd else None,
                }
                descriptions = []
                if requested_geostd:
                    descriptions.append(
                        "Reduce2 restraints: " + ", ".join(requested_geostd)
                    )
                if requested_ccd:
                    descriptions.append(
                        "Meeko chemical templates: " + ", ".join(requested_ccd)
                    )
                dialog = QtWidgets.QMessageBox(self)
                dialog.setIcon(QtWidgets.QMessageBox.Icon.Question)
                dialog.setWindowTitle("Missing public chemical definitions")
                dialog.setText("Additional public definitions are required for " + "; ".join(descriptions))
                dialog.setInformativeText(
                    "If approved, Docking Universal will request only the listed public component "
                    "identifiers from the named public repositories. The services also receive "
                    "ordinary connection metadata such as your IP address and request time. "
                    "Receptor coordinates, ligand files, docking boxes, poses, scores, results, "
                    "study names, and reports are not transmitted."
                )
                dialog.setDetailedText(json.dumps(disclosure, indent=2))
                download = dialog.addButton(
                    "Download listed definitions", QtWidgets.QMessageBox.ButtonRole.AcceptRole,
                )
                cancel = dialog.addButton(
                    "Cancel preparation", QtWidgets.QMessageBox.ButtonRole.RejectRole,
                )
                dialog.setDefaultButton(cancel)
                dialog.exec()
                if dialog.clickedButton() is not download:
                    self.statusBar().showMessage(
                        "Preparation cancelled; no component identifier or structure data was shared."
                    )
                    return None

            geostd_library = Path(reference)
            inputs = Path(output_directory) / "inputs"
            inputs.mkdir(parents=True, exist_ok=True)
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            try:
                if requested_geostd:
                    record = download_components(requested_geostd, cache, approved=True)
                    geostd_library = cache
                    (inputs / "geostd-component-provenance.json").write_text(
                        json.dumps(record, indent=2) + "\n"
                    )
                if missing_meeko:
                    ccd_record = download_ccd_components(
                        missing_meeko, ccd_cache, approved=True,
                    )
                    (inputs / "ccd-component-provenance.json").write_text(
                        json.dumps(ccd_record, indent=2) + "\n"
                    )
            except Exception as exc:
                QtWidgets.QMessageBox.critical(
                    self, "Component download failed",
                    f"No receptor coordinates were sent. The public definition step failed: {exc}",
                )
                return None
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()

            if missing_meeko:
                template_file = inputs / "reviewed-meeko-ptm-templates.json"
                audit_file = inputs / "meeko-ptm-template-audit.json"
                QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
                try:
                    generated = subprocess.run(
                        [
                            str(scientific_python), str(helper), *missing_meeko,
                            "--geostd-library", str(geostd_library),
                            "--ccd-cache", str(ccd_cache),
                            "--output-json", str(template_file),
                            "--audit-json", str(audit_file),
                        ],
                        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                    )
                finally:
                    QtWidgets.QApplication.restoreOverrideCursor()
                if generated.returncode != 0 or not template_file.is_file() or not audit_file.is_file():
                    QtWidgets.QMessageBox.critical(
                        self, "PTM template generation stopped",
                        (
                            generated.stderr.strip()
                            or generated.stdout.strip()
                            or "The deposited modification could not be converted without guessing."
                        ),
                    )
                    return None
                audit = json.loads(audit_file.read_text())
                summaries = []
                for entry in audit.get("components", []):
                    if entry.get("status") != "candidate_validated":
                        continue
                    summaries.append(
                        f"{entry['component_id']} — {entry.get('component_name') or 'unnamed component'}; "
                        f"parent {entry.get('parent_component_id') or 'not deposited'}; "
                        f"formal charge {entry.get('ccd_formal_charge', 'not deposited')}"
                    )
                review = QtWidgets.QMessageBox(self)
                review.setIcon(QtWidgets.QMessageBox.Icon.Warning)
                review.setWindowTitle("Review generated modified-residue template")
                review.setText("A local Meeko template was generated for:\n" + "\n".join(summaries))
                review.setInformativeText(
                    "The candidate preserves the CCD heavy atoms and formal charges and has an "
                    "unambiguous peptide backbone with N- and C-terminal links. Using it changes "
                    "receptor parameterization. It does not prove the biological protonation state; "
                    "review the prepared structure and require target-matched control evidence."
                )
                review.setDetailedText(json.dumps(audit, indent=2))
                use_template = review.addButton(
                    "Use validated local template", QtWidgets.QMessageBox.ButtonRole.AcceptRole,
                )
                stop = review.addButton(
                    "Stop for structural review", QtWidgets.QMessageBox.ButtonRole.RejectRole,
                )
                review.setDefaultButton(stop)
                review.exec()
                if review.clickedButton() is not use_template:
                    self.statusBar().showMessage(
                        "Preparation cancelled; the generated candidate was retained but not used."
                    )
                    return None
                approval = {
                    "schema_name": "docking-universal-meeko-template-approval",
                    "schema_version": 1,
                    "approved_at": datetime.now(timezone.utc).isoformat(),
                    "actor": "desktop-user",
                    "selection": "use_validated_local_template",
                    "components": list(missing_meeko),
                    "template_file": str(template_file.resolve()),
                    "audit_file": str(audit_file.resolve()),
                    "warning_acknowledged": (
                        "Template generation does not establish the biological protonation state; "
                        "prepared-structure review and control evidence remain required."
                    ),
                }
                (inputs / "meeko-ptm-template-approval.json").write_text(
                    json.dumps(approval, indent=2) + "\n"
                )
                self._prepared_meeko_template_file = str(template_file.resolve())

            self.statusBar().showMessage(
                "Public component definitions and any reviewed Meeko PTM template are ready."
            )
            return str(Path(geostd_library).resolve())

        def choose_saved_protocol(self) -> None:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Choose saved docking protocol", "", "Docking Universal protocol (*.duprotocol)")
            if path:
                self.study_setup_panel.protocol_bundle.setText(path)

        def import_saved_protocol(self) -> None:
            from .workflow_panels import ProtocolImportDialog
            try:
                path = self.study_setup_panel.protocol_bundle.text().strip()
                revision = self.state.revision
                self.statusBar().showMessage("Verifying saved protocol and retained input hashes…")
                preview = self.host_controller.inspect_protocol_bundle(path)
                if ProtocolImportDialog(preview, self).exec() != QtWidgets.QDialog.DialogCode.Accepted:
                    return
                self.host_controller.import_protocol_bundle(path, preview['sha256'], revision)
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, "Protocol import unavailable", str(exc))
            finally:
                self.refresh()

        def review_imported_protocol(self) -> None:
            from .workflow_panels import ProtocolImportDialog
            imported = self.state.workflow_data.get('protocol_import') or {}
            try:
                preview = self.host_controller.inspect_protocol_bundle(imported.get('snapshot', ''))
                if preview['sha256'] != imported.get('sha256'):
                    raise ValueError('Imported protocol changed; screening is unavailable')
                ProtocolImportDialog(preview, self, read_only=True).exec()
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, "Saved protocol unavailable", str(exc))

        def start_preparation(self) -> None:
            """Paint immediate feedback before component review or host submission."""
            if not self.host_controller.available:
                return
            if self.study_pathway.currentData() == "reuse":
                self.import_saved_protocol()
                return
            self.feedback_heading.setText("STARTING — Preparing receptor and detecting pockets")
            self.feedback_text.setText("Checking receptor components and preparation settings…")
            self.feedback_card.setStyleSheet(
                "QFrame#scientific_feedback_card {background:#dceeff;"
                "border:2px solid #2478bd;border-radius:5px;}"
                "QFrame#scientific_feedback_card QLabel {color:#172b3a;background:transparent;}"
            )
            self.running_indicator.show()
            self.running_elapsed.setText("Preparation requested — please wait")
            self.running_elapsed.show()
            self.start_preparation_button.setEnabled(False)
            self._stage_submission_in_progress = True
            try:
                QtWidgets.QApplication.processEvents(
                    QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
                )
                self._submit_preparation()
            finally:
                self._stage_submission_in_progress = False
                self.refresh()

        def _submit_preparation(self) -> None:
            if not self.host_controller.available:
                return
            input_text = self.input_pdb.text().strip()
            output_text = self.output_directory.text().strip()
            if input_text and not Path(input_text).is_file():
                from ..services.rcsb import PDB_ID
                if PDB_ID.fullmatch(input_text.upper()):
                    downloaded = self.fetch_input_pdb()
                    if not downloaded:
                        return
                    input_text = downloaded
            if (
                not input_text or not Path(input_text).is_file()
                or Path(input_text).suffix.lower() not in {".pdb", ".cif", ".mmcif"}
            ):
                QtWidgets.QMessageBox.warning(
                    self, "Receptor required",
                    "Choose an existing receptor mmCIF/PDB file or enter a four-character RCSB PDB ID.",
                )
                return
            if not output_text:
                QtWidgets.QMessageBox.warning(
                    self, "Output directory required", "Choose a study output directory before starting.",
                )
                return
            ligand_resname = self.study_setup_panel.ligand_value()
            ligand_identity = self.study_setup_panel.ligand_identity()
            geostd_library = self.prepare_geostd_library(input_text, output_text)
            if not geostd_library:
                return
            if self.study_pathway.currentData() == "control":
                if not all((ligand_resname, ligand_identity.get("chain_id"),
                            ligand_identity.get("residue_number"))):
                    QtWidgets.QMessageBox.warning(
                        self, "Exact control ligand required",
                        "Detect deposited ligands and choose one exact ligand instance before redocking.",
                    )
                    return
                control_payload = {
                    "input_structure": input_text,
                    "output_directory": output_text,
                    "ligand_resname": ligand_resname,
                    "ligand_chain_id": ligand_identity["chain_id"],
                    "ligand_residue_number": ligand_identity["residue_number"],
                    "ligand_insertion_code": ligand_identity.get("insertion_code", ""),
                    "engine": self.control_engine.currentData(),
                    "control_tier": self.control_tier.currentData(),
                    "geostd_library": geostd_library,
                    "meeko_template_file": self._prepared_meeko_template_file,
                    "pocket_engine": self.pocket_engine.currentData(),
                    "predict_pockets_with_ligand": self.study_setup_panel.predict_with_ligand.isChecked(),
                    "pdb_pocket_evidence": (
                        "related-structures" if self.study_setup_panel.pdb_evidence.isChecked() else "off"
                    ),
                }
                try:
                    self.host_controller.start_control_validation(control_payload, self.state.revision)
                except Exception as exc:
                    QtWidgets.QMessageBox.critical(self, "Known-ligand control could not start", str(exc))
                self.refresh()
                return
            if self.site_mode.currentData() == "ligand" and not ligand_resname:
                QtWidgets.QMessageBox.warning(
                    self, "Ligand required",
                    "Detect deposited ligands from the receptor and choose the ligand that defines the site.",
                )
                return
            if self.site_mode.currentData() == "ligand" and not all((
                ligand_identity.get("chain_id"), ligand_identity.get("residue_number"),
            )):
                QtWidgets.QMessageBox.warning(
                    self, "Exact ligand instance required",
                    "Detect deposited ligands and choose one exact chain/residue instance. "
                    "A residue name alone may refer to multiple sites and cannot safely define "
                    "one docking box.",
                )
                return
            payload = {
                "input_pdb": input_text,
                "working_directory": output_text,
                "site_mode": self.site_mode.currentData(),
                "ligand_resname": ligand_resname or None,
                "ligand_chain_id": ligand_identity.get("chain_id") or None,
                "ligand_residue_number": ligand_identity.get("residue_number") or None,
                "ligand_insertion_code": ligand_identity.get("insertion_code", ""),
                "ligand_altloc": ligand_identity.get("altloc", ""),
                "feedback_level": self.detail.currentText().lower().replace("teaching", "verbose").replace("technical", "verbose"),
                "cavity_mode": 1,
                "max_pockets": 0,  # No count cutoff; review all eligible regions.
                "center_mode": "deepest",
                "centroid_mode": 1,
                "pocket_engine": self.pocket_engine.currentData(),
                "predict_pockets_with_ligand": (self.site_mode.currentData() == "ligand" and
                                                 self.study_setup_panel.predict_with_ligand.isChecked()),
                "geostd_library": geostd_library,
                "meeko_template_file": self._prepared_meeko_template_file,
                "pdb_pocket_evidence": (
                    "related-structures" if self.study_setup_panel.pdb_evidence.isChecked() else "off"
                ),
            }
            try:
                self.host_controller.start_preparation(payload, self.state.revision)
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "Preparation could not start", str(exc))
            self.refresh()

        def cancel_active_job(self) -> None:
            if not self.host_controller.available:
                return
            try:
                self.host_controller.cancel_active_job(
                    self.state.revision,
                    self.state.active_job.id if self.state.active_job else None,
                )
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "Cancellation could not be requested", str(exc))
            self.refresh()

        def start_protocol_finalization(self) -> None:
            if not self.host_controller.available:
                return
            if self.protocol_finalization_panel._control_mode:
                try:
                    self.host_controller.start_control_validation({}, self.state.revision)
                except Exception as exc:
                    QtWidgets.QMessageBox.critical(self, "Reviewed control could not start", str(exc))
                self.refresh()
                return
            output = self.final_output_directory.text().strip()
            if not output:
                QtWidgets.QMessageBox.warning(
                    self, "Output directory required",
                    "Choose where the final report and portable protocol should be written.",
                )
                return
            if not self.exploratory_approval.isChecked():
                QtWidgets.QMessageBox.warning(
                    self, "Explicit approval required",
                    "Reusable exploratory protocol creation requires explicit approval.",
                )
                return
            payload = {
                "output_directory": output,
                "engine": self.protocol_engine.currentData(),
                "ph": self.protocol_ph.value(),
                "conformers": self.protocol_conformers.value(),
                "seed_count": self.protocol_seeds.value(),
                "base_seed": self.protocol_base_seed.value(),
                "exhaustiveness": self.protocol_exhaustiveness.value(),
                "num_modes": self.protocol_modes.value(),
                "energy_range": self.protocol_energy_range.value(),
                "exploratory_use_approved": True,
            }
            if self.protocol_engine.currentData()=='adgpu':
                payload.update(ad4_runs=self.protocol_ad4_runs.value(),ad4_heuristic_cap=self.protocol_ad4_heuristic_cap.value())
            try:
                self.host_controller.start_finalization(payload, self.state.revision)
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "Protocol finalization could not start", str(exc))
            self.refresh()

        def open_final_report(self) -> None:
            report = next((
                artifact for artifact in self.state.artifacts
                if artifact.kind == "final_report" and Path(artifact.path).is_file()
            ), None)
            if report is None:
                report = next((artifact for artifact in self.state.artifacts
                               if artifact.kind == "control_report" and Path(artifact.path).is_file()), None)
            if report:
                self._open_path(Path(report.path))

        def open_bundle_location(self) -> None:
            bundle = next((
                artifact for artifact in self.state.artifacts
                if artifact.kind == "protocol_bundle" and Path(artifact.path).is_file()
            ), None)
            if bundle:
                self._open_path(Path(bundle.path).parent)

        def _clear_screening_library(self, *_args):
            self._ligand_read_generation += 1
            self.screening_setup_panel.library_panel.clear()
            if Path(self.screen_ligands.text().strip()).suffix.lower() in {'.csv', '.tsv', '.xlsx'}:
                self.screening_setup_panel.library_panel.summary.setText(
                    'SMILES table: click Read/select compounds, then review and approve its columns.')

        def _read_library_async(self, operation, callback):
            from .ligand_library_panel import LibraryReadTask
            task = LibraryReadTask()
            self._ligand_read_tasks.add(task)
            generation = self._ligand_read_generation

            def finished(result, error):
                self._ligand_read_tasks.discard(task)
                task.deleteLater()
                if generation == self._ligand_read_generation:
                    callback(result, error)
            task.finished.connect(finished)
            task.start(operation)

        def read_screening_library(self, column_mapping=None, sheet=None):
            if not self.host_controller.available:
                return
            panel = self.screening_setup_panel.library_panel
            source = self.screen_ligands.text().strip()
            self._ligand_read_generation += 1
            panel.clear()
            panel.loading = True
            panel.read_button.setEnabled(False)
            panel.summary.setText("Reading compound records locally… This does not start docking.")
            self._update_screening_controls()

            def loaded(library, error):
                panel.loading = False
                panel.read_button.setEnabled(True)
                if error:
                    panel.read_error = error
                    panel.summary.setText(f"Library could not be read: {error}")
                    self._update_screening_controls()
                    return
                panel.set_library(library)
                self.screening_status.setText('Review the suggested columns and click Use these columns. This does not start docking.'
                    if not library.get('mapping_approved', True) else
                    "Choose compounds using the Dock checkboxes, then preview the selected workload.")
            options = {}
            if column_mapping is not None:
                options['column_mapping'] = column_mapping
            if sheet is not None:
                options['sheet'] = sheet
            self._read_library_async(lambda: self.host_controller.inspect_ligand_library(source, **options), loaded)

        def preview_library_record(self, identifier):
            panel = self.screening_setup_panel.library_panel
            library = panel.library
            if not library or not self.host_controller.available:
                return
            panel._pixmap = None
            panel.preview.clear()
            panel.preview.setText("Rendering compound structure…")

            def rendered(result, error):
                if panel.current_record_id() != identifier:
                    return
                if error:
                    panel.preview.setText(error)
                    return
                try:
                    panel.set_preview(result)
                except ValueError as exc:
                    panel.preview.setText(str(exc))
            self._read_library_async(lambda: self.host_controller.ligand_record_preview(
                library['source'], library['fingerprint'], identifier,
                **({'column_mapping': library['column_mapping']} if 'column_mapping' in library else {})), rendered)

        def _invalidate_screening_plan(self, *_args) -> None:
            self._screening_plan = None
            self._update_screening_controls()

        def _update_screening_controls(self, *_args) -> None:
            if not hasattr(self, "start_screening_button"):
                return
            plan = self._screening_plan or {}
            authorization_ready = (
                not plan.get("exploratory_authorization_required")
                or self.screen_exploratory_approval.isChecked()
            )
            active = getattr(self, "state", None) and self.state.active_job
            library_panel = self.screening_setup_panel.library_panel
            self.start_screening_button.setText("Dock selected compounds" if library_panel.library is not None
                                                else "Run locked-protocol screening")
            library_ready = not library_panel.loading and not library_panel.read_error
            if Path(self.screen_ligands.text().strip()).suffix.lower() in {'.csv', '.tsv', '.xlsx'} and library_panel.library is None:
                library_ready = False
            if library_panel.library is not None:
                library_ready = library_ready and bool(library_panel.selection()['record_ids'])
            self.start_screening_button.setEnabled(bool(plan and authorization_ready and not active
                                                       and library_ready and self.host_controller.available))
            self.preview_screening_button.setEnabled(bool(
                self.host_controller.available and not active and library_ready
                and self.screen_ligands.text().strip() and self.screen_output.text().strip()
                and any(item.kind == 'protocol_bundle' and Path(item.path).is_file()
                        for item in self.state.artifacts)))

        def preview_screening(self) -> None:
            if not self.host_controller.available:
                return
            library_panel = self.screening_setup_panel.library_panel
            if (library_panel.loading or library_panel.read_error
                    or (library_panel.library and not library_panel.library.get('mapping_approved', True))):
                self.screening_status.setText("Finish reading a valid ligand library before previewing the workload.")
                return
            try:
                self._screening_plan = self.host_controller.screening_plan(
                    self.screen_ligands.text().strip(),
                    **({"ligand_selection": self.screening_setup_panel.library_panel.selection()}
                       if self.screening_setup_panel.library_panel.library is not None else {}),
                )
            except Exception as exc:
                self._screening_plan = None
                QtWidgets.QMessageBox.critical(self, "Screening inputs were rejected", str(exc))
                self._update_screening_controls()
                return
            plan = self._screening_plan
            self.screening_setup_panel.set_engine(plan['engine'])
            self.screening_status.setText(
                f"{plan['compound_count']} compound(s) × {plan['conformers_per_compound']} conformers "
                f"× {plan['independent_seed_count']} seeds × {plan['docking_site_count']} sites = "
                f"{plan['total_docking_jobs']} sequential docking jobs. Engine: {plan['engine']}."
            )
            self.screen_exploratory_approval.setVisible(
                bool(plan["exploratory_authorization_required"])
            )
            self.screening_setup_panel.inline_explanations['approval'].setVisible(
                bool(plan["exploratory_authorization_required"])
            )
            self._update_screening_controls()

        def start_screening(self) -> None:
            if not self.host_controller.available or not self._screening_plan:
                return
            payload = {
                "ligand_source": self.screen_ligands.text().strip(),
                "output_directory": self.screen_output.text().strip(),
                "analysis": self.screen_analysis.currentData(),
                "representatives": self.screen_representatives.value(),
                "cluster_rmsd": self.screen_cluster_rmsd.value(),
                "stop_on_error": self.screen_stop_on_error.isChecked(),
                "exploratory_use_approved": self.screen_exploratory_approval.isChecked(),
            }
            cpu = self.screening_setup_panel.cpu_override()
            if cpu is not None:
                payload['cpu'] = cpu
            selection = self.screening_setup_panel.library_panel.selection()
            if selection is not None:
                payload["ligand_selection"] = selection
            self.feedback_heading.setText('STARTING — Screening selected compounds')
            self.feedback_text.setText('Validating the selected compounds and locked protocol before launch…')
            self.screening_status.setText('Screening requested — checking inputs, then preparing ligand states and conformers…')
            self.running_indicator.show()
            self.running_elapsed.setText('Screening requested — please wait')
            self.running_elapsed.show()
            self.start_screening_button.setEnabled(False)
            self._stage_submission_in_progress = True
            try:
                QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
                self.host_controller.start_screening(payload, self.state.revision)
            except Exception as exc:
                self._stage_submission_in_progress = False
                self.refresh()
                self.screening_status.setText(f"Screening could not start: {exc}")
                QtWidgets.QMessageBox.critical(self, "Screening could not start", str(exc))
                return
            finally:
                self._stage_submission_in_progress = False
            self._screening_plan = None
            self.refresh()

        def _open_visual_scene(self, scene: Path) -> None:
            self._close_interaction_review()
            self._evidence_2d_record = None
            self._evidence_2d_view = None
            self._linked_pose_active = False
            if self.viewer_widget is not None:
                if getattr(self, 'cluster_contact_controls', None) is not None:
                    self.cluster_contact_controls.hide()
                self.linked_pose_panel.clear_pose("Select a docked pose to view linked 2D interactions.")
                self.linked_pose_panel.hide()
            self._selected_structure_scene = Path(scene)
            self.open_visual_review()

        def open_visual_review(self) -> None:
            if not self.viewer_coordinator:
                return
            reconnecting = getattr(self.viewer_coordinator, "status", None) == "failed"
            self.session.set_viewer_state(
                connected=False, lifecycle="connecting",
                detail=(
                    "Connecting to the local PyMOL companion…"
                    if self._uses_companion_viewer()
                    else "Loading the embedded PyMOL scene…"
                ),
            )
            QtWidgets.QApplication.processEvents()
            try:
                scene = getattr(self, "_selected_structure_scene", None)
                if scene is None:
                    raise ValueError("Select a retained 3D PyMOL scene first")
                if hasattr(self.viewer_coordinator, "set_context"):
                    self.viewer_coordinator.set_context(self.state)
                if reconnecting and hasattr(self.viewer_coordinator, "reconnect"):
                    self.viewer_coordinator.reconnect(self.state)
                self.viewer_coordinator.open_scene(scene)
            except Exception as exc:
                self._viewer_failed(exc)
                QtWidgets.QMessageBox.critical(self, "PyMOL review unavailable", str(exc))
                return
            backend = getattr(self.viewer_coordinator, "backend_name", "PyMOL viewer")
            self.viewer_status.setText(
                f"{backend} connected — visual changes do not imply approval"
            )
            if self.viewer_coordinator.report_view_available:
                self.viewer_status.setText(
                    f"{backend} matches {self.viewer_coordinator.report_view_name} — "
                    "exploration does not imply approval"
                )
            self.reset_view_button.setEnabled(self.viewer_coordinator.report_view_available)
            self.session.set_viewer_state(
                connected=True,
                report_view_available=bool(getattr(self.viewer_coordinator, "report_view_available", False)),
                detail=self.viewer_status.text(),
                lifecycle="connected",
            )
            self._show_embedded_viewer()
            self._resync_current_pose_if_available()

        def _viewer_failed(self, exc: Exception) -> None:
            backend = getattr(self.viewer_coordinator, "backend_name", "PyMOL viewer")
            detail = f"{backend} failed: {exc}"
            self.viewer_status.setText(detail)
            self.session.set_viewer_state(
                connected=False, report_view_available=False, detail=detail,
                lifecycle="failed", error=str(exc),
            )

        def _resync_current_pose_if_available(self) -> bool:
            selection = self.session.selection
            if selection.pose_id is None or not selection.analysis_root:
                return False
            pose = (
                Path(selection.analysis_root) / "pose_interactions"
                / f"pose_{selection.pose_id:04d}" / "pose.sdf"
            )
            if not pose.is_file():
                return False
            return self._sync_pose_if_connected(
                Path(selection.analysis_root), selection.pose_id,
            )

        def reset_report_view(self) -> None:
            if not self.viewer_coordinator:
                return
            try:
                self.viewer_coordinator.reset_report_view()
            except Exception as exc:
                self._viewer_failed(exc)
                QtWidgets.QMessageBox.critical(self, "Report view could not be restored", str(exc))
                return
            self.viewer_status.setText("Restored the exact retained report view")
            self.session.set_viewer_state(
                connected=True, report_view_available=True,
                detail=self.viewer_status.text(),
                lifecycle="connected",
            )

        def show_decision_synopsis(self) -> None:
            pending = self.state.pending_decisions
            if not pending:
                return
            decision = pending[0]
            candidates = self.state.workflow_data.get("pocket_candidates", [])
            selected_values = ()
            if decision.kind == "select_pockets":
                rows = self.candidates.selectionModel().selectedRows()
                selected = [
                    candidates[index.row()] for index in rows
                    if index.row() < len(candidates)
                ]
                selected_values = tuple(str(item.get("id")) for item in selected)
            evidence = {"candidates": candidates} if candidates else {}
            deposited = decision.payload.get("deposited_mmcif_evidence")
            if deposited:
                evidence["deposited_mmcif_evidence"] = deposited
            dialog = DecisionDialog(
                decision,
                settings=self.settings,
                evidence=evidence,
                selected=selected_values,
                allow_approval=bool(self.host_controller.available),
                parent=self,
            )
            if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return
            try:
                self.host_controller.resolve_decision(
                    decision.id, list(dialog.selected_values()),
                    dialog.rationale.text().strip(), self.state.revision,
                )
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "Approval rejected", str(exc))
            self.refresh()

        def show_full_synopsis_report(self) -> None:
            reports = [
                artifact for artifact in self.state.artifacts
                if artifact.kind == "preliminary_report" and Path(artifact.path).is_file()
            ]
            report = next((
                artifact for artifact in reports
                if "preliminary" in Path(artifact.path).name.lower()
                or "pocket" in Path(artifact.path).name.lower()
            ), reports[0] if reports else None)
            if report is None:
                QtWidgets.QMessageBox.warning(
                    self, "Synopsis report unavailable",
                    "The complete pocket-review report has not been generated yet.",
                )
                return
            self._open_path(Path(report.path))

        def _candidate_highlight_changed(self) -> None:
            self._close_interaction_review()
            from ..services.pdb_lookup_status import lookup_status_for_state
            self.pocket_evidence_panel.set_lookup_status(lookup_status_for_state(self.state))
            rows = self.candidates.selectionModel().selectedRows()
            self._update_candidate_review_action()
            if not rows:
                self.pocket_evidence_panel.set_candidate(None)
                return
            candidates = self.state.workflow_data.get("pocket_candidates", [])
            if rows[0].row() >= len(candidates):
                return
            candidate = candidates[rows[0].row()]
            self.pocket_score_plot.selected = str(candidate["id"])
            self.pocket_score_plot.update()
            self.pocket_evidence_panel.set_candidate(candidate)
            if not self.viewer_coordinator:
                return
            if not self.viewer_coordinator.connected:
                self.open_selected_candidate_review()
                return
            try:
                self.viewer_coordinator.show_candidate(self.state, str(candidate["id"]))
                self._ensure_pocket_space()
                self._show_embedded_viewer()
            except Exception as exc:
                self.viewer_status.setText(f"Candidate display failed: {exc}")

        def _select_plotted_candidate(self, candidate_id: str) -> None:
            for row, candidate in enumerate(self.state.workflow_data.get("pocket_candidates", [])):
                if str(candidate["id"]) == candidate_id:
                    blocker = QtCore.QSignalBlocker(self.candidates)
                    self.candidates.clearSelection()
                    self.candidates.selectRow(row)
                    del blocker
                    self._candidate_highlight_changed()
                    return

        def _update_candidate_review_action(self) -> None:
            rows = self.candidates.selectionModel().selectedRows()
            available = bool(
                self.viewer_coordinator
                and rows
                and any(
                    decision.kind == "select_pockets"
                    for decision in self.state.pending_decisions
                )
            )
            self.candidate_review_button.setEnabled(available)
            # Embedded candidate selection already loads the scene. Keep the
            # explicit launcher only for the companion viewer.
            self.candidate_review_button.setVisible(self.viewer_widget is None)
            if self.viewer_widget is not None:
                self.candidate_review_button.setText(
                    "Review selected region in interactive 3D"
                )
            elif self.viewer_coordinator is not None:
                self.candidate_review_button.setText("Review selected region in PyMOL")
            else:
                self.candidate_review_button.setText("3D review unavailable")

        def open_selected_candidate_review(self) -> None:
            """Open retained structural evidence without requiring a report figure."""
            rows = self.candidates.selectionModel().selectedRows()
            candidates = self.state.workflow_data.get("pocket_candidates", [])
            if not rows or rows[0].row() >= len(candidates):
                QtWidgets.QMessageBox.warning(
                    self, "Selection required", "Select a docking-region candidate first.",
                )
                return
            if self.viewer_coordinator is None:
                QtWidgets.QMessageBox.warning(
                    self, "3D review unavailable",
                    "A PyMOL review backend is not configured for this installation.",
                )
                return
            candidate = candidates[rows[0].row()]
            candidate_id = str(candidate.get("id"))
            try:
                if not self.viewer_coordinator.connected:
                    if (
                        getattr(self.viewer_coordinator, "status", None) == "failed"
                        and hasattr(self.viewer_coordinator, "reconnect")
                    ):
                        self.viewer_coordinator.reconnect(self.state)
                    else:
                        self.viewer_coordinator.open(self.state)
                self.viewer_coordinator.show_candidate(self.state, candidate_id)
                self._ensure_pocket_space()
                adapter = getattr(self.viewer_coordinator, "adapter", None)
                if (
                    self._uses_companion_viewer() and adapter is not None
                    and hasattr(adapter, "bring_to_front")
                ):
                    self._send_windows_back()
                    QtCore.QTimer.singleShot(200, adapter.bring_to_front)
                else:
                    self._show_embedded_viewer()
                backend = getattr(
                    self.viewer_coordinator, "backend_name", "3D structural viewer",
                )
                self.viewer_status.setText(
                    f"{backend}: reviewing {candidate_id}; viewing does not imply approval"
                )
                self.session.set_viewer_state(
                    connected=True,
                    report_view_available=bool(
                        getattr(self.viewer_coordinator, "report_view_available", False)
                    ),
                    detail=self.viewer_status.text(), lifecycle="connected",
                )
            except Exception as exc:
                self._viewer_failed(exc)
                QtWidgets.QMessageBox.critical(
                    self, "3D pocket review unavailable", str(exc),
                )

        def _ensure_pocket_space(self):
            """A cached local visualization, independent of approvals/scientific jobs."""
            from ..services.pocket_space import inputs, cached
            import os
            adapter = getattr(self.viewer_coordinator, 'adapter', None)
            if (not hasattr(adapter, 'show_pocket_space')
                    or getattr(self, '_paired_interaction_window', None) is not None
                    or getattr(self, '_linked_pose_active', False)):
                return
            if self.state.active_job and self.state.active_job.status.value in {'running', 'queued'}:
                return
            try:
                record = inputs(self.state)
                if record is None:
                    return
                manifest = cached(record)
                if manifest:
                    self._apply_pocket_space(manifest)
                    return
                process = getattr(self, '_pocket_space_process', None)
                if process and process.state() != QtCore.QProcess.ProcessState.NotRunning:
                    return
                if getattr(self, '_pocket_space_failed_cache', None) == record['cache']:
                    return
                python = getattr(self.host_client, 'python_executable', None)
                if python is None:
                    return
                prefix = Path(python).parent.parent
                prank = Path(os.environ.get('DOCKING_UNIVERSAL_P2RANK_VISUALIZATION') or
                    prefix / 'share/docking-universal/p2rank-2.6-alpha' /
                    ('prank.bat' if os.name == 'nt' else 'prank'))
                if not prank.is_file():
                    self.viewer_status.setText('Pocket-space surface unavailable: install the pinned alpha visualization dependency.')
                    return
                cache = Path(record['cache'])
                cache.mkdir(parents=True, exist_ok=True)
                request = cache / 'request.json'
                request.write_text(json.dumps(record, indent=2))
                process = QtCore.QProcess(self)
                environment = QtCore.QProcessEnvironment()
                for name, value in self.host_client._environment().items():
                    environment.insert(name, value)
                if (prefix / 'lib/jvm').is_dir():
                    environment.insert('JAVA_HOME', str(prefix / 'lib/jvm'))
                process.setProcessEnvironment(environment)
                process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
                process.setStandardOutputFile(str(cache / 'worker.log'))
                self._pocket_space_process = process
                self.statusBar().showMessage('Generating pocket-space surfaces locally · retained scores and boxes are unchanged…')
                process.finished.connect(lambda code, status: self._pocket_space_finished(record, code))
                process.errorOccurred.connect(lambda error: self._pocket_space_finished(record, -1)
                    if error == QtCore.QProcess.ProcessError.FailedToStart else None)
                worker = Path(__file__).resolve().parents[2] / 'docking-universal-pocket-space.py'
                process.start(str(python), [str(worker), '--request', str(request), '--prank', str(prank)])
            except Exception as exc:
                self.viewer_status.setText(f'Pocket-space surface unavailable: {exc}')

        def _pocket_space_finished(self, record, code):
            from ..services.pocket_space import cached, inputs
            try:
                if code != 0:
                    raise ValueError(f"generation failed; see {Path(record['cache']) / 'worker.log'}")
                if inputs(self.state) != record:
                    return
                manifest = cached(record)
                if manifest is None:
                    raise ValueError('verified grid was not retained')
                if (getattr(self, '_paired_interaction_window', None) is None
                        and not getattr(self, '_linked_pose_active', False)):
                    self._apply_pocket_space(manifest)
            except Exception as exc:
                self._pocket_space_failed_cache = record['cache']
                self.statusBar().showMessage(f'Pocket-space surface unavailable: {exc}', 15000)

        def _apply_pocket_space(self, manifest):
            import re
            from .study_viewer import POCKET_COLORS
            selected = self.candidates.selectionModel().selectedRows()
            candidates = self.state.workflow_data.get('pocket_candidates', [])
            if not selected or selected[0].row() >= len(candidates):
                return
            candidate = candidates[selected[0].row()]
            ranks = [int(v) for v in re.findall(r'P(\d+)', str(candidate['id']))]
            color = POCKET_COLORS[(int(candidate.get('rank') or 1) - 1) % len(POCKET_COLORS)]
            shown = self.viewer_coordinator.adapter.show_pocket_space(manifest, ranks, color)
            self.viewer_status.setText('Predicted pocket-space surface · approximate grid boundary, not protein surface'
                                       if shown else 'This region has no matched P2Rank pocket-space grid.')
            self.statusBar().showMessage(self.viewer_status.text(), 8000)

        def _show_candidate_evidence_details(self, item) -> None:
            """Open the complete retained record without expanding the navigation table."""
            if item.column() != 3:
                return
            candidates = self.state.workflow_data.get("pocket_candidates", [])
            if item.row() >= len(candidates):
                return
            candidate = candidates[item.row()]
            label = candidate.get("label") or candidate.get("id") or "candidate"
            evidence = candidate.get("evidence") or {}
            digest, _tooltip = self._candidate_evidence_digest(candidate, evidence)

            dialog = QtWidgets.QDialog(self)
            dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
            dialog.setWindowTitle(f"{label} — complete retained evidence")
            dialog.resize(820, 620)
            layout = QtWidgets.QVBoxLayout(dialog)
            heading = QtWidgets.QLabel(f"<b>{label}</b><br>{digest}")
            heading.setWordWrap(True)
            explanation = QtWidgets.QLabel(
                "This is the complete retained evidence record. Individual deposited-ligand "
                "structures remain selectable in the Experimental PDB Evidence panel."
            )
            explanation.setWordWrap(True)
            content = QtWidgets.QPlainTextEdit()
            content.setReadOnly(True)
            content.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
            content.setPlainText(json.dumps(evidence, indent=2, sort_keys=True))
            close_button = QtWidgets.QPushButton("Close")
            close_button.clicked.connect(dialog.close)
            layout.addWidget(heading)
            layout.addWidget(explanation)
            layout.addWidget(content, 1)
            layout.addWidget(close_button, 0, QtCore.Qt.AlignmentFlag.AlignRight)
            self._candidate_evidence_dialogs.append(dialog)
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()

        def highlight_evidence_residues(self, residues) -> bool:
            """The same exact-residue review action as in the full PyMOL shell."""
            self._close_interaction_review()
            try:
                adapter = getattr(self.viewer_coordinator, "adapter", None)
                if self.viewer_widget is None or not hasattr(adapter, "highlight_obstruction_residues"):
                    raise ValueError("Residue highlighting requires the embedded PyMOL backend")
                self._show_embedded_viewer()
                if not self._connect_structure_review():
                    return False
                result = adapter.highlight_obstruction_residues(residues)
                self._sync_residue_highlight_actions()
                shown = result.get("highlighted", True) if isinstance(result, dict) else True
                self.viewer_status.setText(f"Residue highlight {'shown' if shown else 'hidden'}. Camera unchanged.")
                self.statusBar().showMessage(self.viewer_status.text(), 6000)
                return True
            except Exception as exc:
                self._sync_residue_highlight_actions()
                self.viewer_status.setText(f"Residue highlight unavailable: {exc}")
                self.statusBar().showMessage(self.viewer_status.text(), 10000)
                return False

        def _sync_residue_highlight_actions(self):
            adapter = getattr(self.viewer_coordinator, "adapter", None)
            self.pocket_evidence_panel.sync_residue_highlight(adapter)
            browser = getattr(self._detached_structure_window, "study_panel", None)
            if browser is not None:
                browser.evidence.sync_residue_highlight(adapter)

        def _connect_structure_review(self) -> bool:
            """Evidence/candidate review does not depend on a report figure."""
            if not self.viewer_coordinator:
                return False
            if self.viewer_coordinator.connected:
                return True
            try:
                if getattr(self.viewer_coordinator, "status", None) == "failed":
                    self.viewer_coordinator.reconnect(self.state)
                else:
                    self.viewer_coordinator.open(self.state)
            except Exception as exc:
                self._viewer_failed(exc)
                return False
            return bool(self.viewer_coordinator.connected)

        def render_evidence_interactions(self, observation):
            from ..services.evidence_interactions import evidence_inputs, evidence_diagram_current
            if self.viewer_widget is None:
                QtWidgets.QMessageBox.information(self, "Embedded viewer required", "Linked experimental 2D review requires the embedded structure viewer.")
                return
            process = getattr(self, "_evidence_2d_process", None)
            if process and process.state() != QtCore.QProcess.ProcessState.NotRunning:
                return
            if self.state.active_job and self.state.active_job.status.value in {"running", "queued"}:
                self.statusBar().showMessage("Wait for the active scientific stage before rendering interactions.")
                return
            try:
                record = evidence_inputs(observation)
                cache = Path(record["cache"])
                if evidence_diagram_current(cache):
                    self._show_evidence_diagram(record)
                    return
                python = getattr(self.host_client, "python_executable", None)
                if not python:
                    raise ValueError("The scientific Python host is unavailable")
                cache.mkdir(parents=True, exist_ok=True)
                record["diagram_only"] = (cache / "result.json").is_file() and all((cache / name).is_file() for name in
                        ("ligand.sdf", "receptor.pdb", "plip/report.xml"))
                request = cache / "request.json"
                request.write_text(json.dumps(record, indent=2))
                process = QtCore.QProcess(self)
                environment = QtCore.QProcessEnvironment()
                for name, value in self.host_client._environment().items():
                    environment.insert(name, value)
                process.setProcessEnvironment(environment)
                process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
                process.setStandardOutputFile(str(cache / "worker.log"))
                self._evidence_2d_process = process
                self._evidence_2d_record = record
                self.pocket_evidence_panel.rendering_2d = True
                self.pocket_evidence_panel._update_2d_action()
                self.linked_pose_panel.show_loading(f"Rendering 2D interactions for {record['entry']} {record['ligand']}…")
                self._linked_pose_active = True
                self.linked_pose_panel.hide()
                self.statusBar().showMessage(f"Rendering 2D interactions for {record['entry']} {record['ligand']}…")
                self._show_evidence_render_progress(record)
                process.finished.connect(lambda code, status: self._evidence_2d_finished(record, code))
                process.errorOccurred.connect(lambda error: self._evidence_2d_failed_start(record, error))
                worker = Path(__file__).resolve().parents[2] / "docking-universal-evidence-interactions.py"
                arguments = [str(worker), "--request", str(request)]
                if record["diagram_only"]:
                    arguments.append("--diagram-only")
                process.start(str(python), arguments)
            except Exception as exc:
                self._close_evidence_render_progress()
                QtWidgets.QMessageBox.warning(self, "2D interactions unavailable", str(exc))

        def _show_evidence_render_progress(self, record):
            """Visible local computation, not an invented percentage or modal gate."""
            self._close_evidence_render_progress()
            progress = QtWidgets.QProgressDialog(self)
            progress.setWindowTitle("Preparing 2D / 3D interaction review")
            progress.setWindowModality(QtCore.Qt.WindowModality.NonModal)
            progress.setCancelButton(None)
            progress.setRange(0, 0)
            progress.setAutoClose(False)
            progress.setMinimumDuration(0)
            progress.setMinimumWidth(440)
            elapsed = QtCore.QElapsedTimer()
            elapsed.start()
            timer = QtCore.QTimer(progress)
            def update():
                activity = ("Updating the 2D drawing from retained PLIP contacts; no new analysis.\n"
                            if record.get("diagram_only") else
                            "Calculating PLIP contacts and drawing the 2D diagram locally.\n")
                progress.setLabelText(
                    f"{record['entry']} · {record['ligand']} {record['chain']}:{record['residue']}\n"
                    + activity +
                    f"Elapsed: {elapsed.elapsed() // 1000} s · the paired review opens when ready.")
            timer.timeout.connect(update)
            timer.start(1000)
            update()
            self._evidence_2d_progress = progress
            progress.show()

        def _close_evidence_render_progress(self):
            progress = getattr(self, "_evidence_2d_progress", None)
            if progress is not None:
                progress.close()
                progress.deleteLater()
                self._evidence_2d_progress = None

        def _evidence_2d_failed_start(self, record, error):
            if error == QtCore.QProcess.ProcessError.FailedToStart:
                self._evidence_2d_finished(record, -1)

        def _evidence_2d_finished(self, record, code):
            self._close_evidence_render_progress()
            self.pocket_evidence_panel.rendering_2d = False
            self.pocket_evidence_panel._update_2d_action()
            cache = Path(record["cache"])
            if code == 0 and (cache / "result.json").is_file():
                current = self.pocket_evidence_panel.selected_observation() or {}
                if current.get("aligned_ligand_pdb") == record["aligned"]:
                    self._show_evidence_diagram(record)
                else:
                    self.linked_pose_panel.clear_pose("Diagram cached. Select its observation and click Render 2D interactions to view it.")
            else:
                self.linked_pose_panel.clear_pose(f"2D rendering failed. Details: {cache / 'worker.log'}")
                self.statusBar().showMessage(f"2D rendering failed. See {cache / 'worker.log'}")
                QtWidgets.QMessageBox.warning(self, "2D rendering failed", f"See the local worker log for details:\n{cache / 'worker.log'}")

        def _show_evidence_diagram(self, record):
            from .linked_pose_review import PoseView
            from ..services.evidence_interactions import evidence_diagram_path
            cache = Path(record["cache"])
            self._evidence_2d_record = record
            self._evidence_2d_view = PoseView(cache / "ligand.sdf", cache / "receptor.pdb",
                evidence_diagram_path(cache), cache / "plip" / "report.xml",
                f"{record['entry']} · {record['ligand']} {record['chain']}:{record['residue']} · deposited interactions",
                ligand_name=record['ligand'], coordinate_kind="experimental")
            self._linked_pose_active = True
            self._open_interaction_review(self._evidence_2d_view)
            self.linked_pose_panel.status.setText("Interactions and 3D coordinates both come from the original deposited protein and ligand.")
            result = json.loads((cache / "result.json").read_text())
            if result.get("diagram_kind") == "ligand_and_plip_contact_summary":
                self.linked_pose_panel.status.setText("Compact ligand and PLIP contact summary; detailed layout unavailable. Both views use the original deposited coordinates.")
        def show_evidence_ligand(self, path: str) -> None:
            self._close_interaction_review()
            if not self.viewer_coordinator:
                self.viewer_status.setText("PyMOL is not configured for this installation")
                return
            if not self._connect_structure_review():
                self.viewer_status.setText(
                    "Could not connect to PyMOL; the evidence remains selected for review"
                )
                return
            try:
                receptor = next((Path(a.path) for a in self.state.artifacts if a.kind == "prepared_receptor_structure" and Path(a.path).is_file()), None)
                self.viewer_coordinator.show_evidence_ligand(path, receptor)
                adapter = getattr(self.viewer_coordinator, "adapter", None)
                if self._uses_companion_viewer() and adapter is not None and hasattr(adapter, "bring_to_front"):
                    self._send_windows_back()
                    QtCore.QTimer.singleShot(300, adapter.bring_to_front)
                else:
                    self._show_embedded_viewer()
                self.viewer_status.setText("Showing aligned deposited ligand — viewing does not imply approval")
            except Exception as exc:
                self.viewer_status.setText(f"Experimental ligand display failed: {exc}")

        def show_evidence_ligands(self, paths: list[str]) -> None:
            self._close_interaction_review()
            if not paths:
                return
            if not self.viewer_coordinator:
                self.viewer_status.setText("PyMOL is not configured for this installation")
                return
            if not self._connect_structure_review():
                self.viewer_status.setText("Could not connect to PyMOL for evidence comparison")
                return
            try:
                receptor = next((Path(a.path) for a in self.state.artifacts if a.kind == "prepared_receptor_structure" and Path(a.path).is_file()), None)
                self.viewer_coordinator.show_evidence_ligands(paths, receptor)
                adapter = getattr(self.viewer_coordinator, "adapter", None)
                if self._uses_companion_viewer() and adapter is not None and hasattr(adapter, "bring_to_front"):
                    self._send_windows_back()
                    QtCore.QTimer.singleShot(300, adapter.bring_to_front)
                else:
                    self._show_embedded_viewer()
                self.viewer_status.setText(
                    f"Showing {len(paths)} selected deposited ligands in PyMOL — viewing does not imply approval"
                )
            except Exception as exc:
                self.viewer_status.setText(f"Experimental evidence comparison failed: {exc}")

        def sync_evidence_selection(self, paths: list[str]) -> None:
            """Mirror table selection immediately without replacing the report scene."""
            view = getattr(self, "_evidence_2d_view", None)
            record = getattr(self, "_evidence_2d_record", None)
            if getattr(self, "_paired_interaction_window", None) is not None:
                if record and record['aligned'] in paths:
                    return  # polling/unchanged selection cannot replace the source pair
                self._close_interaction_review()
            if record and record['aligned'] not in paths:
                self._evidence_2d_record = None
                self._linked_pose_active = False
                self.linked_pose_panel.hide()
            if view and self.viewer_widget is not None and (record or {}).get('aligned', str(view.ligand)) not in paths:
                self._evidence_2d_view = None
                self._linked_pose_active = False
                self.linked_pose_panel.hide()
            if not self.viewer_coordinator or not self.viewer_coordinator.connected:
                return
            try:
                self.viewer_coordinator.sync_evidence_ligands(paths)
                adapter = getattr(self.viewer_coordinator, "adapter", None)
                if self._uses_companion_viewer() and adapter is not None and hasattr(adapter, "bring_to_front"):
                    # Let the current table event finish before activating the
                    # companion window; otherwise Qt immediately reclaims focus.
                    self._send_windows_back()
                    QtCore.QTimer.singleShot(150, adapter.bring_to_front)
                    QtCore.QTimer.singleShot(500, adapter.bring_to_front)
                    QtCore.QTimer.singleShot(1000, adapter.bring_to_front)
                backend = getattr(self.viewer_coordinator, "backend_name", "PyMOL")
                self.viewer_status.setText(
                    f"{backend} synchronized with {len(paths)} selected evidence observation(s)"
                )
            except Exception as exc:
                self.viewer_status.setText(f"Evidence selection sync failed: {exc}")

        def _size_candidate_table(self) -> None:
            self.candidates.setMaximumHeight(
                self.candidates.horizontalHeader().height()
                + self.candidates.verticalHeader().defaultSectionSize()
                * min(4, max(1, self.candidates.rowCount()))
                + self.candidates.horizontalScrollBar().sizeHint().height() + 6
            )

        def _render_candidates(self, state: StudyState) -> None:
            # Polling repaints evidence; only user navigation should reload 3D.
            fingerprint = json.dumps({
                "candidates": state.workflow_data.get("pocket_candidates", []),
                "root": state.workflow_data.get("preparation_root"),
            }, sort_keys=True)
            if fingerprint == getattr(self, "_candidate_table_fingerprint", None):
                self._update_candidate_review_action()
                return
            blocker = QtCore.QSignalBlocker(self.candidates)
            self.pocket_score_plot.set_study(state)
            self.pocket_score_scroll.setVisible(bool(self.pocket_score_plot.points))
            values = state.workflow_data.get("pocket_candidates", [])
            self.candidates.setRowCount(len(values))
            # Show short candidate lists in full; selection must not require
            # finding a barely visible scrollbar below the molecular canvas.
            self._size_candidate_table()
            for row, candidate in enumerate(values):
                evidence = candidate.get("evidence", {})
                evidence_text, evidence_tooltip = self._candidate_evidence_digest(
                    candidate, evidence,
                )
                columns = (
                    candidate.get("label", candidate.get("id", "")), candidate.get("rank", ""),
                    candidate.get("summary", ""),
                    evidence_text,
                )
                for column, value in enumerate(columns):
                    item = QtWidgets.QTableWidgetItem(str(value))
                    if column == 3:
                        item.setToolTip(evidence_tooltip)
                    self.candidates.setItem(row, column, item)
            header = self.candidates.horizontalHeader()
            header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Stretch)
            try:
                self.candidates.itemSelectionChanged.disconnect(self._candidate_highlight_changed)
            except TypeError:
                pass
            self.candidates.itemSelectionChanged.connect(self._candidate_highlight_changed)
            rows = self.candidates.selectionModel().selectedRows()
            if values and not rows:
                # Present the highest-ranked candidate's evidence immediately.
                # Highlighting is only navigation; approval still requires the
                # separate explicit action and rationale audit path.
                self.candidates.selectRow(0)
                rows = self.candidates.selectionModel().selectedRows()
            self.pocket_evidence_panel.set_candidate(
                values[rows[0].row()] if rows and rows[0].row() < len(values) else None
            )
            self.pocket_score_plot.selected = (
                str(values[rows[0].row()]["id"])
                if rows and rows[0].row() < len(values) else None
            )
            self.pocket_score_plot.update()
            self._update_candidate_review_action()
            self._candidate_table_fingerprint = fingerprint
            del blocker
            self._schedule_initial_candidate_review()

        @staticmethod
        def _candidate_evidence_digest(candidate: dict, evidence: dict) -> tuple[str, str]:
            """Return a decision-sized summary; never serialize nested evidence into the table."""
            parts = []
            details = []
            conformational = evidence.get("conformational_site_evidence") or {}
            summary, explanation = conformation_summary(conformational)
            parts.append(summary)
            details.append(explanation)

            experimental = evidence.get("experimental_ligand_evidence") or {}
            observations = int(experimental.get("observation_count") or 0)
            entries = int(experimental.get("pdb_entry_count") or 0)
            classes = experimental.get("evidence_class_counts") or {}
            exact = int(classes.get("exact_sequence_match") or 0)
            homolog = int(classes.get("close_structural_homolog") or 0)
            if observations:
                parts.append(
                    f"{observations} ligand observations / {entries} PDBs "
                    f"({exact} exact; {homolog} homolog)"
                )
                details.append(
                    "Select this candidate to inspect individual structures in Experimental PDB Evidence."
                )

            current_id = str(candidate.get("id", "")).lstrip("P")
            for item in evidence.get("pocket_equivalences") or []:
                peers = [
                    f"P{value}" for value in item.get("pockets", [])
                    if str(value) != current_id
                ]
                if not peers:
                    continue
                rmsd = item.get("fitted_pocket_atom_rmsd_angstrom")
                rmsd_text = f"; RMSD {rmsd} Å" if isinstance(rmsd, (int, float)) else ""
                parts.append(f"Symmetry-related to {','.join(peers)}{rmsd_text}")

            if not parts:
                parts.append("No retained experimental evidence")
            if not details:
                details.append("Select the candidate to review its retained evidence and geometry.")
            return " · ".join(parts), " ".join(details)

        def _render_artifacts(self, state: StudyState) -> None:
            self.report_list.clear()
            logs = []
            for artifact in state.artifacts:
                if Path(artifact.path).suffix.lower() in {'.png', '.jpg', '.jpeg', '.svg', '.webp', '.tif', '.tiff'}:
                    continue  # Static figures are accessed through reports, not image viewers.
                item = QtWidgets.QListWidgetItem(f"{artifact.kind.replace('_', ' ').capitalize()}: {artifact.path}")
                item.setData(QtCore.Qt.UserRole, artifact.path)
                item.setToolTip("Double-click to open this saved study file")
                self.report_list.addItem(item)
                if "log" in artifact.kind and Path(artifact.path).is_file():
                    logs.append(f"[{artifact.description or artifact.kind}]\n{Path(artifact.path).read_text(errors='replace')}")
            # The widget is bounded; full raw logs remain in their artifacts.
            self.log_view.setPlainText("\n\n".join(logs)[-200_000:])

        def _render_screening_results(self, state: StudyState) -> None:
            selected_compound = self._selected_screening_compound()
            selected_pose = None
            pose_rows = self.pose_results.selectionModel().selectedRows()
            if pose_rows:
                selected_pose = self.pose_results.item(pose_rows[0].row(), 0).data(QtCore.Qt.UserRole)
            results = self.results_model.compounds(state)
            self.screening_results.blockSignals(True)
            self.screening_results.setRowCount(len(results))
            for row, result in enumerate(results):
                values = (
                    result.name, result.status, result.site_count, result.planned_jobs,
                    result.best_score, result.cluster_count,
                )
                for column, value in enumerate(values):
                    item = QtWidgets.QTableWidgetItem(str(value))
                    item.setData(QtCore.Qt.UserRole, str(result.path))
                    self.screening_results.setItem(row, column, item)
            self.screening_results.resizeColumnsToContents()
            if selected_compound is not None:
                for row in range(self.screening_results.rowCount()):
                    if self.screening_results.item(row, 0).data(QtCore.Qt.UserRole) == str(selected_compound):
                        self.screening_results.selectRow(row)
                        break
            self.screening_results.blockSignals(False)
            self.open_screen_report_button.setEnabled(any(
                artifact.kind == "screening_report" and Path(artifact.path).is_file()
                for artifact in state.artifacts
            ))
            self.open_pose_session_button.setEnabled(any(
                any(path.is_file() for path in result.path.glob("**/*.pse"))
                for result in results
            ))
            self.open_pose_session_button.setVisible(self.viewer_widget is None)
            self._pose_selection_to_restore = selected_pose
            self._screening_result_selection_changed()
            self._pose_selection_to_restore = None

        def _selected_screening_compound(self) -> Path | None:
            rows = self.screening_results.selectionModel().selectedRows()
            if not rows:
                return None
            item = self.screening_results.item(rows[0].row(), 0)
            return Path(str(item.data(QtCore.Qt.UserRole))) if item else None

        def _schedule_session_refresh(self, _state) -> None:
            QtCore.QTimer.singleShot(0, self._poll_refresh)

        def _apply_session_viewer_state(self, viewer) -> None:
            """Expose the shared viewer state in every study window."""
            embedded = self.viewer_widget is not None
            backend = (
                getattr(self.viewer_coordinator, "backend_name", "PyMOL")
                if self.viewer_coordinator is not None else "Structural viewer"
            )
            self.viewer_button.setText(
                f"Reconnect {backend}" if viewer.lifecycle == "failed"
                else ("Load selected 3D scene" if embedded else "Open selected 3D scene in PyMOL")
            )
            self.viewer_button.setEnabled(
                not embedded
                and
                self.viewer_coordinator is not None
                and bool(getattr(self, "_selected_structure_scenes", None))
                and viewer.lifecycle != "connecting"
            )
            self.viewer_button.setVisible(
                not embedded and bool(getattr(self, "_selected_structure_scenes", None))
            )
            self.reset_view_button.setEnabled(bool(
                self.viewer_coordinator and viewer.report_view_available
            ))
            if viewer.detail:
                self.viewer_status.setText(viewer.detail)
            elif viewer.connected:
                self.viewer_status.setText(
                    f"{backend} is connected for this study — visual changes do not imply approval"
                )
            elif self.viewer_coordinator is None:
                self.viewer_status.setText(
                    "Structural viewer is unavailable; shared study status is disconnected"
                )
            elif viewer.lifecycle == "connecting":
                self.viewer_status.setText(f"Connecting to {backend}…")
            if viewer.connected:
                location = "embedded workspace" if embedded else "companion window"
                self.structural_view.setText(
                    f"{backend} connected in the {location}\n\n"
                    "The retained report orientation and shared pose selection are active. "
                    "Use Reset to report view after free exploration."
                )
            else:
                self.structural_view.setText(
                    "Live PyMOL structural review\n\n"
                    "Open the retained report view to inspect the structure interactively. "
                    "Exploration never changes approval state."
                )

        def _apply_session_selection(self, selection) -> None:
            """Mirror another window's presentation selection without approval."""
            self._render_results_session_status(selection)
            self._render_central_selection_status(selection)
            if self._applying_session_selection:
                return
            self._applying_session_selection = True
            try:
                if selection.compound:
                    for row in range(self.screening_results.rowCount()):
                        item = self.screening_results.item(row, 0)
                        if item and str(Path(str(item.data(QtCore.Qt.UserRole))).resolve()) == selection.compound:
                            self.screening_results.selectRow(row)
                            break
                if selection.pose_id is not None and selection.analysis_root:
                    self.pose_review_mode.setCurrentIndex(
                        self.pose_review_mode.findData("all_poses")
                    )
                    for row in range(self.pose_results.rowCount()):
                        item = self.pose_results.item(row, 0)
                        if item:
                            analysis_value, pose_id = item.data(QtCore.Qt.UserRole)
                            if (str(Path(str(analysis_value)).resolve()) == selection.analysis_root
                                    and int(pose_id) == selection.pose_id):
                                self.pose_results.selectRow(row)
                                break
                elif selection.cluster_id is not None and selection.analysis_root:
                    self.pose_review_mode.setCurrentIndex(
                        self.pose_review_mode.findData("clusters")
                    )
                    for index in range(self.interaction_diagram_choice.count()):
                        diagram = Path(str(self.interaction_diagram_choice.itemData(index)))
                        cluster = diagram.parent.parent
                        if (str(cluster.parent.resolve()) == selection.analysis_root
                                and int(cluster.name.removeprefix("cluster_")) == selection.cluster_id):
                            self.interaction_diagram_choice.setCurrentIndex(index)
                            break
            finally:
                self._applying_session_selection = False

        @staticmethod
        def _cluster_interaction_metadata(diagram: Path, compound: Path) -> dict:
            value = ResultsReviewModel.cluster_interaction(diagram, compound)
            return {
                "cluster_id": value.cluster_id, "site": value.site,
                "rank": value.rank, "score": value.score,
                "population": value.population,
            }

        @classmethod
        def _cluster_interaction_label(cls, diagram: Path, compound: Path) -> str:
            values = cls._cluster_interaction_metadata(diagram, compound)
            return (
                f"Energy rank {values['rank']} · Cluster {values['cluster_id']} · {values['site']} · "
                f"{values['score']} kcal/mol · {values['population']} poses"
            )

        def _screening_result_selection_changed(self) -> None:
            compound = self._selected_screening_compound()
            if not self._applying_session_selection:
                self.session.select_compound(compound)
            self.interaction_diagram_choice.blockSignals(True)
            self.interaction_diagram_choice.clear()
            if compound is not None:
                for interaction in self.results_model.cluster_interactions(self.state, compound):
                    self.interaction_diagram_choice.addItem(
                        interaction.label, str(interaction.diagram)
                    )
            control_root = self.state.workflow_data.get("latest_control_output")
            if control_root:
                for diagram in sorted((Path(control_root) / "report").glob("control_*_plip2d.png")):
                    view = pose_view(diagram)
                    if view is not None:
                        self.interaction_diagram_choice.addItem(view.label, str(diagram.resolve()))
            self.interaction_diagram_choice.blockSignals(False)
            self._populate_expanded_pose_results(compound)
            self._pose_review_mode_changed()

        def _pose_review_mode_changed(self, *_args) -> None:
            expanded = self.pose_review_mode.currentData() == "all_poses"
            self.interaction_diagram_choice.setVisible(not expanded)
            self.pose_results.setVisible(expanded)
            self.pose_cluster_filter.setVisible(expanded)
            self.sync_pose_button.setEnabled(bool(
                expanded and self.viewer_coordinator and self.viewer_coordinator.connected
                and self.pose_results.selectionModel().selectedRows()
            ))
            if expanded:
                self._linked_pose_active = False
                if getattr(self, 'cluster_contact_controls', None) is not None:
                    self.cluster_contact_controls.hide()
                    adapter = getattr(self.viewer_coordinator, 'adapter', None)
                    if adapter is not None and hasattr(adapter, 'clear_linked_contacts'):
                        adapter.clear_linked_contacts()
                self.interaction_context.setText("Expanded review — select an exact retained pose")
                self._interaction_source_pixmap = None
                self.interaction_diagram_view.clear()
                if not self.pose_results.rowCount():
                    self.interaction_diagram_view.setText(
                        "No retained all-pose inventory is available for this compound."
                    )
                elif not self.pose_results.selectionModel().selectedRows():
                    self.interaction_diagram_view.setText(
                        "Select a retained pose to inspect its exact cluster, score, and interaction view."
                    )
                return
            self.results_controller.clear()
            self.interaction_context.setText("Cluster synopsis")
            self._show_selected_interaction_diagram()

        def _populate_expanded_pose_results(self, compound: Path | None) -> None:
            rows = self.results_model.poses(compound)
            self.pose_results.blockSignals(True)
            self.pose_results.setRowCount(len(rows))
            for row, (analysis, record) in enumerate(rows):
                values = (
                    record.pose_id, record.cluster_id, f"{record.energy_kcal_per_mol:g} kcal/mol",
                    "yes" if record.selected_cluster else "no",
                    record.seed if record.seed is not None else "NA",
                    record.conformer or "NA", record.model if record.model is not None else "NA",
                )
                for column, value in enumerate(values):
                    item = QtWidgets.QTableWidgetItem(str(value))
                    item.setData(QtCore.Qt.UserRole, (str(analysis), record.pose_id))
                    self.pose_results.setItem(row, column, item)
            self.pose_results.blockSignals(False)
            self.pose_results.resizeColumnsToContents()
            restore = getattr(self, "_pose_selection_to_restore", None)
            if restore is not None:
                self.pose_results.blockSignals(True)
                for row in range(self.pose_results.rowCount()):
                    if self.pose_results.item(row, 0).data(QtCore.Qt.UserRole) == restore:
                        self.pose_results.selectRow(row)
                        break
                self.pose_results.blockSignals(False)
            clusters = sorted({record.cluster_id for _analysis, record in rows})
            selected_cluster = self.pose_cluster_filter.currentData()
            self.pose_cluster_filter.blockSignals(True)
            self.pose_cluster_filter.clear()
            self.pose_cluster_filter.addItem("All clusters", None)
            for cluster_id in clusters:
                self.pose_cluster_filter.addItem(f"Cluster {cluster_id}", cluster_id)
            index = self.pose_cluster_filter.findData(selected_cluster)
            self.pose_cluster_filter.setCurrentIndex(max(0, index))
            self.pose_cluster_filter.blockSignals(False)
            self._apply_pose_cluster_filter()

        def _apply_pose_cluster_filter(self, *_args) -> None:
            cluster = self.pose_cluster_filter.currentData()
            for row in range(self.pose_results.rowCount()):
                value = int(self.pose_results.item(row, 1).text())
                self.pose_results.setRowHidden(row, cluster is not None and value != int(cluster))

        def _expanded_pose_selection_changed(self) -> None:
            if self.pose_review_mode.currentData() != "all_poses":
                return
            selected = self.pose_results.selectionModel().selectedRows()
            if not selected:
                return
            item = self.pose_results.item(selected[0].row(), 0)
            analysis_value, pose_id = item.data(QtCore.Qt.UserRole)
            analysis = Path(str(analysis_value))
            compound = self._selected_screening_compound()
            mirrored_selection = self._applying_session_selection
            cluster_id = int(self.pose_results.item(selected[0].row(), 1).text())
            if compound is not None and not mirrored_selection:
                self.session.select_pose(
                    compound, analysis, cluster_id, int(pose_id), site=analysis.parent.name,
                )
            decision = self.results_controller.select_pose(
                compound=compound.name if compound else "compound",
                site=analysis.parent.name, analysis_root=analysis, pose_id=int(pose_id),
                mirrored=mirrored_selection, host_available=self.host_controller.available,
                renderer_available=self.poseedit_runtime["status"] == "available",
            )
            key = self.begin_pose_interaction_loading(*decision.key)
            row = selected[0].row()
            self.interaction_context.setText(
                f"Pose {pose_id} · Cluster {self.pose_results.item(row, 1).text()} · "
                f"{self.pose_results.item(row, 2).text()}"
            )
            self.sync_pose_button.setEnabled(bool(
                self.viewer_coordinator and self.viewer_coordinator.connected
            ))
            if decision.action == "cached":
                self.complete_pose_interaction_loading(key, decision.diagram)
                if not mirrored_selection:
                    self._sync_pose_if_connected(analysis, int(pose_id))
            else:
                if decision.action == "wait":
                    self.interaction_diagram_view.setText(
                        f"Pose {pose_id} was selected in another window. "
                        "Waiting for its saved interaction files; no duplicate analysis was started."
                    )
                    return
                if decision.action == "host_unavailable":
                    self.interaction_diagram_view.setText(
                        f"Pose {pose_id} selected. Connect the application host to generate its local PLIP view."
                    )
                    return
                if decision.action == "renderer_unavailable":
                    self.interaction_diagram_view.setText(
                        f"Pose {pose_id} cannot be rendered yet. "
                        + self.poseedit_runtime["detail"]
                        + ". Run docking-universal runtime-inventory for resolved paths."
                    )
                    return
                try:
                    self.host_controller.start_pose_interaction(
                        analysis, int(pose_id), self.state.revision,
                    )
                    self._sync_pose_if_connected(analysis, int(pose_id))
                except Exception as exc:
                    self.interaction_diagram_view.setText(
                        f"Pose {pose_id} interaction analysis could not start: {exc}"
                    )

        def _sync_pose_if_connected(self, analysis: Path, pose_id: int) -> bool:
            if self.viewer_widget is not None:
                diagram = self.results_model.cached_pose_diagram(analysis, pose_id)
                if diagram is not None:
                    return self._present_linked_diagram(diagram)
            if not self.viewer_coordinator or not self.viewer_coordinator.connected:
                return False
            try:
                self.viewer_coordinator.show_pose(analysis, pose_id)
            except Exception as exc:
                self._viewer_failed(exc)
                return False
            self.viewer_status.setText(
                f"{getattr(self.viewer_coordinator, 'backend_name', 'PyMOL viewer')} synchronized "
                f"to retained pose {pose_id} — viewing does not imply approval"
            )
            self.session.set_viewer_state(
                connected=True,
                report_view_available=bool(
                    getattr(self.viewer_coordinator, "report_view_available", False)
                ),
                detail=self.viewer_status.text(),
                lifecycle="connected",
            )
            return True

        def sync_selected_pose_to_pymol(self) -> None:
            selected = self.pose_results.selectionModel().selectedRows()
            if not selected:
                QtWidgets.QMessageBox.warning(self, "Pose required", "Select a retained pose first.")
                return
            item = self.pose_results.item(selected[0].row(), 0)
            analysis, pose_id = item.data(QtCore.Qt.UserRole)
            self._sync_pose_if_connected(Path(str(analysis)), int(pose_id))

        def _refresh_pending_pose_interaction(self, state: StudyState) -> None:
            artifact = self.results_controller.completed_artifact(state)
            if artifact is not None:
                self.complete_pose_interaction_loading(
                    self.results_controller.pending_key, artifact.path,
                )

        def _show_selected_interaction_diagram(self, *_args) -> None:
            path_value = self.interaction_diagram_choice.currentData()
            path = Path(str(path_value)) if path_value else None
            available = bool(path and path.is_file())
            compound = self._selected_screening_compound()
            if available and compound is not None and not self._applying_session_selection:
                cluster = path.parent.parent
                try:
                    cluster_id = int(cluster.name.removeprefix("cluster_"))
                except ValueError:
                    cluster_id = None
                if cluster_id is not None:
                    self.session.select_cluster(
                        compound, cluster.parent, cluster_id, site=cluster.parent.parent.name,
                    )
            self._current_interaction_diagram = path if available else None
            self.open_interaction_diagram_button.setEnabled(available)
            self._interaction_source_pixmap = None
            self.interaction_diagram_view.clear()
            if not available:
                if getattr(self, 'cluster_contact_controls', None) is not None:
                    self.cluster_contact_controls.hide()
                    if (getattr(self, '_linked_pose_active', False)
                            and getattr(self, '_paired_interaction_window', None) is None
                            and not getattr(self, '_evidence_2d_view', None)):
                        self.viewer_coordinator.adapter.clear_linked_contacts()
                        self._linked_pose_active = False
                if (self.viewer_widget is not None
                        and getattr(self, "_paired_interaction_window", None) is None
                        and not getattr(self, "_evidence_2d_record", None)
                        and not getattr(self, "_evidence_2d_view", None)):
                    self.linked_pose_panel.clear_pose("No 2D interaction diagram is available for this selection.")
                self.interaction_diagram_view.setText(
                    "No retained PLIP 2D diagram is available for this selection. "
                    "The raw PLIP record remains listed with the study files when generated."
                )
                return
            pixmap = QtGui.QPixmap(str(path))
            if pixmap.isNull():
                self.interaction_diagram_view.setText(f"Diagram could not be decoded: {path.name}")
                return
            self._display_interaction_pixmap(pixmap)
            if self.viewer_widget is not None:
                self._present_linked_diagram(path)

        def _activate_interaction_ligand(self) -> None:
            """Reveal the linked workspace before selecting the exact displayed ligand."""
            diagram = self._current_interaction_diagram
            if not diagram:
                return
            if self.viewer_widget is None:
                self.interaction_context.setText("Linked 2D/3D review requires the embedded structure viewer.")
                return
            self._present_linked_diagram(diagram, highlight=True)

        def _present_linked_diagram(self, diagram, *, highlight=False):
            view = pose_view(Path(diagram))
            if view is None:
                self.linked_pose_panel.clear_pose("Exact 3D coordinates are unavailable for this diagram.")
                return False
            if (getattr(self, "_linked_pose_active", False)
                    and self.linked_pose_panel.query == view and not highlight):
                return True
            reference = control_view(self.state)
            if reference and reference.receptor.read_bytes() != view.receptor.read_bytes():
                # An unaligned reference must never be overlaid on another receptor.
                reference = None
            self.linked_pose_panel.set_pose(view, reference)
            self.linked_pose_panel.hide()
            return self._highlight_linked_ligand(view, highlight=highlight)

        def _highlight_linked_ligand(self, view, *, highlight=True):
            if view == getattr(self, "_evidence_2d_view", None):
                return self._open_interaction_review(view)
            if getattr(self, "_paired_interaction_window", None) is not None:
                return self._open_interaction_review(view)
            if highlight:
                return self._open_interaction_review(view)
            try:
                adapter = self.viewer_coordinator.adapter
                if not self.viewer_coordinator.connected:
                    adapter.launch()
                # Use the exact representative report, not a report-level
                # overview or another cluster's contact record.
                try:
                    styles, residues = adapter.show_linked_interactions(view)
                    self.cluster_contact_controls.set_contacts(styles, residues)
                except (OSError, ValueError, ET.ParseError) as exc:
                    adapter.clear_linked_contacts()
                    self.cluster_contact_controls.unavailable(f'3D PLIP contacts unavailable for this pose: {exc}')
                self.viewer_coordinator.connected = True
            except Exception as exc:
                self.linked_pose_panel.status.setText(f"3D ligand could not be displayed: {exc}")
                return False
            self._linked_pose_active = True
            self.linked_pose_panel.status.setText(
                view.label + (" · highlighted in 3D" if highlight else " · shown in 3D")
            )
            self._show_embedded_viewer()
            return True

        def _export_ligand_comparison(self):
            from tempfile import TemporaryDirectory
            panel = self.linked_pose_panel
            if panel.query is None or panel.reference is None:
                return
            destination, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Save comparison report", "ligand-comparison.html", "HTML report (*.html)",
            )
            if not destination:
                return
            adapter = self.viewer_coordinator.adapter
            camera = adapter.cmd.get_view()
            shown = adapter.review_pose
            try:
                with TemporaryDirectory(prefix="du-comparison-") as temporary:
                    renders = []
                    for index, item in enumerate((panel.query, panel.reference)):
                        adapter.show_linked_pose(item.ligand, item.receptor,
                                                 ligand_color=getattr(item, "ligand_color", "gray70"))
                        adapter.cmd.set_view(camera)
                        output = Path(temporary) / f"view-{index}.png"
                        adapter.cmd.png(str(output), width=1800, height=1400, ray=1, quiet=1)
                        renders.append(output)
                    write_comparison_report(destination, panel.query, panel.reference, *renders)
                panel.status.setText(f"Comparison report saved: {Path(destination).name}")
            except Exception as exc:
                panel.status.setText(f"Comparison report could not be saved: {exc}")
            finally:
                restore = panel.reference if shown == panel.reference.ligand else panel.query
                adapter.show_linked_pose(restore.ligand, restore.receptor,
                                         ligand_color=getattr(restore, "ligand_color", "gray70"))
                adapter.cmd.set_view(camera)

        def begin_pose_interaction_loading(self, compound: str, site: str, pose_id: int) -> tuple:
            """Clear stale imagery before an exact-pose PLIP request starts."""
            key = (str(compound), str(site), int(pose_id))
            self.results_controller.pending_key = key
            self._current_interaction_diagram = None
            if self.viewer_widget is not None:
                self.linked_pose_panel.clear_pose(f"Generating 2D interactions for pose {pose_id}…")
                self.linked_pose_panel.show()
            self._interaction_source_pixmap = None
            self.open_interaction_diagram_button.setEnabled(False)
            self.interaction_diagram_view.clear()
            self.interaction_diagram_view.setText(
                f"Generating PLIP interactions for pose {pose_id}…\n"
                "The 3D pose remains available while this analysis runs."
            )
            return key

        def complete_pose_interaction_loading(self, key: tuple, diagram: Path | str) -> bool:
            """Display a completed diagram only if its pose is still selected."""
            if not self.results_controller.accepts(key):
                return False
            path = Path(diagram)
            pixmap = QtGui.QPixmap(str(path)) if path.is_file() else QtGui.QPixmap()
            self.interaction_diagram_view.clear()
            if pixmap.isNull():
                self.interaction_diagram_view.setText(
                    f"PLIP interaction analysis did not produce a readable diagram for pose {key[2]}."
                )
                self.open_interaction_diagram_button.setEnabled(False)
                return False
            self._display_interaction_pixmap(pixmap)
            self._current_interaction_diagram = path
            if self.viewer_widget is not None:
                self._present_linked_diagram(path)
            self.open_interaction_diagram_button.setEnabled(True)
            return True

        def _display_interaction_pixmap(self, pixmap) -> None:
            self._interaction_source_pixmap = pixmap
            self.interaction_diagram_view.setText("")
            self._interaction_zoom_changed()

        def _interaction_zoom_changed(self, *_args) -> None:
            pixmap = self._interaction_source_pixmap
            if pixmap is None or pixmap.isNull():
                return
            percent = int(self.interaction_zoom.currentData() or 0)
            if percent == 0:
                self.interaction_scroll.setWidgetResizable(True)
                viewport = self.interaction_scroll.viewport().size()
                width = max(520, viewport.width() - 8)
                height = max(320, viewport.height() - 8)
                shown = pixmap.scaled(
                    width, height, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation,
                )
                self.interaction_diagram_view.setPixmap(shown)
                return
            self.interaction_scroll.setWidgetResizable(False)
            shown = pixmap.scaled(
                max(1, pixmap.width() * percent // 100),
                max(1, pixmap.height() * percent // 100),
                QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation,
            )
            self.interaction_diagram_view.setPixmap(shown)
            self.interaction_diagram_view.resize(shown.size())

        def open_screening_report(self) -> None:
            report = next((
                artifact for artifact in self.state.artifacts
                if artifact.kind == "screening_report" and Path(artifact.path).is_file()
            ), None)
            if report:
                self._open_path(Path(report.path))

        def open_selected_pose_session(self) -> None:
            rows = self.screening_results.selectionModel().selectedRows()
            if not rows:
                QtWidgets.QMessageBox.warning(
                    self, "Compound required", "Select a screened compound first.",
                )
                return
            item = self.screening_results.item(rows[0].row(), 0)
            compound = Path(str(item.data(QtCore.Qt.UserRole)))
            session = next((path for path in sorted(compound.glob("**/*.pse")) if path.is_file()), None)
            if session is None:
                QtWidgets.QMessageBox.warning(
                    self, "Pose session unavailable",
                    "No retained PyMOL pose session is available for this compound and analysis level.",
                )
                return
            self._open_path(session)

        def open_selected_interaction_diagram(self) -> None:
            path = self._current_interaction_diagram
            if not path or not path.is_file():
                QtWidgets.QMessageBox.warning(
                    self, "Interaction diagram unavailable",
                    "Select a compound and an available cluster interaction diagram first.",
                )
                return
            self._activate_interaction_ligand()

        def open_artifact(self, item) -> None:
            path = Path(str(item.data(QtCore.Qt.UserRole) or ""))
            if not path.is_file():
                QtWidgets.QMessageBox.warning(self, "Artifact unavailable", f"Artifact does not exist: {path}")
                return
            self._open_path(path)

        def _open_path(self, path: Path) -> None:
            if path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.svg', '.webp', '.tif', '.tiff'}:
                QtWidgets.QMessageBox.information(
                    self, "Figures are in reports",
                    "Open the study report to view static figures. Use the linked 2D/3D review for interactions.",
                )
                return
            if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path.resolve()))):
                QtWidgets.QMessageBox.warning(self, "Artifact could not be opened", str(path))

        def show_scientific_detail(self) -> None:
            self.workflow_detail_dock.show()
            if self.workflow_detail_dock.isFloating():
                self.workflow_detail_dock.raise_()
                self.workflow_detail_dock.activateWindow()

        def _detail_changed(self, value: str) -> None:
            self.session.set_detail_level(value)
            self._render_events()

        def _apply_session_detail(self, value: str) -> None:
            expected = value.title()
            if self.detail.currentText() != expected:
                self.detail.setCurrentText(expected)
            self._render_events()

        def _render_events(self, *_args) -> None:
            if not hasattr(self, "state"):
                return
            self.scientific_detail_panel.render(self.state)

        def set_canvas_focus_mode(self, enabled: bool) -> None:
            """Give figures or the live structure the full workspace on demand."""
            for dock in (
                self.workflow_navigation_dock,
                self.study_setup_dock,
                self.pocket_evidence_dock,
            ):
                dock.setVisible(not enabled)
            self.focus_canvas_action.setText(
                "Show workflow panels" if enabled else "Focus canvas"
            )
            if not enabled:
                self._stabilize_workflow_rail()
                self.resizeDocks(
                    [self.pocket_evidence_dock], [360],
                    QtCore.Qt.Orientation.Horizontal,
                )

        def _poll_refresh(self) -> None:
            self.workspace_controller.poll()

        def showEvent(self, event) -> None:
            super().showEvent(event)
            self.workspace_controller.shown()
            QtCore.QTimer.singleShot(0, self._poll_refresh)
            self._schedule_initial_candidate_review()

        def closeEvent(self, event) -> None:
            self._close_interaction_review()
            panel = getattr(self, "linked_pose_panel", None)
            if panel is not None and panel._detached_window is not None:
                panel._detached_window.close()
            if self._detached_structure_window is not None:
                self._detached_structure_window.close()
            self.workspace_controller.save_layout()
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
                message.exec()
                if message.clickedButton() is not cancel_and_exit:
                    event.ignore()
                    return
                try:
                    self.host_controller.cancel_active_job(latest.revision, active.id)
                except Exception as exc:
                    QtWidgets.QMessageBox.critical(self, "Cancellation could not be requested", str(exc))
                    event.ignore()
                    return
                self._exit_after_cancel = True
                self.statusBar().showMessage("Cancelling the active stage before exit…")
                event.ignore()
                return
            process = getattr(self, "_evidence_2d_process", None)
            if process and process.state() != QtCore.QProcess.ProcessState.NotRunning:
                process.terminate()
                if not process.waitForFinished(5000):
                    process.kill()
                    process.waitForFinished(1000)
            self._close_evidence_render_progress()
            process = getattr(self, '_pocket_space_process', None)
            if process and process.state() != QtCore.QProcess.ProcessState.NotRunning:
                process.terminate()
                if not process.waitForFinished(5000):
                    process.kill()
                    process.waitForFinished(1000)
            self.workspace_controller.closed()
            self._save_form_values()
            super().closeEvent(event)
else:
    class StudyWindow:  # pragma: no cover
        def __init__(self, *_args, **_kwargs):
            require_qt()
