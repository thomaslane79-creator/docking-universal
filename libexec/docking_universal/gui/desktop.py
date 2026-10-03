"""Dockable read-only workspace for one persisted scientific study."""

from __future__ import annotations

import json
import subprocess
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
    from .pocket_evidence import PocketEvidencePanel
    from .pocket_plot import PocketScorePlot
    from .decision_dialog import DecisionDialog
    from .linked_pose_review import LinkedPosePanel, pose_view, control_view, write_comparison_report
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
            if self.viewer_widget is not None and self.review_tabs.count() > 1:
                if self.review_tabs.currentIndex() != 1:
                    self.review_tabs.setCurrentIndex(1)
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
            self._show_runtime_identity()
            self.workspace_controller = WorkspaceWindowController(
                self, self.settings, self.refresh,
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
            self.refresh()

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
            self.running_indicator.setFixedHeight(10)
            self.running_indicator.hide()
            feedback_layout.addWidget(self.running_indicator)
            self.running_elapsed = QtWidgets.QLabel()
            self.running_elapsed.setObjectName("central_running_elapsed")
            self.running_elapsed.hide()
            feedback_layout.addWidget(self.running_elapsed)
            self.feedback_card.setStyleSheet(
                "QFrame#scientific_feedback_card { background:#eef5ff; "
                "border:1px solid #8bb7e8; border-radius:5px; }"
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
            figure_page = QtWidgets.QWidget()
            figure_layout = QtWidgets.QVBoxLayout(figure_page)
            figure_layout.setContentsMargins(0, 0, 0, 0)
            self.decision_figure_choice = QtWidgets.QComboBox()
            self.decision_figure_choice.setObjectName("decision_figure_choice")
            self.decision_figure_choice.currentIndexChanged.connect(
                self._show_selected_decision_figure
            )
            self.scene_figure_choice = QtWidgets.QComboBox()
            self.scene_figure_choice.setObjectName("scene_figure_choice")
            self.scene_figure_choice.setToolTip("Choose the retained figure whose 3D scene you want to inspect")
            self.scene_figure_choice.currentIndexChanged.connect(self._scene_figure_changed)
            self.figure_controls_widget = QtWidgets.QWidget()
            figure_controls = QtWidgets.QHBoxLayout(self.figure_controls_widget)
            figure_controls.setContentsMargins(0, 0, 0, 0)
            self.figure_fit_button = QtWidgets.QPushButton("Fit")
            self.figure_fit_button.setObjectName("decision_figure_fit")
            self.figure_fit_button.clicked.connect(self._fit_decision_figure)
            self.figure_actual_size_button = QtWidgets.QPushButton("100%")
            self.figure_actual_size_button.setObjectName("decision_figure_actual_size")
            self.figure_actual_size_button.clicked.connect(
                lambda: self._set_decision_figure_zoom(1.0)
            )
            self.figure_zoom_out_button = QtWidgets.QPushButton("−")
            self.figure_zoom_out_button.setObjectName("decision_figure_zoom_out")
            self.figure_zoom_out_button.clicked.connect(
                lambda: self._change_decision_figure_zoom(1 / 1.25)
            )
            self.figure_zoom_in_button = QtWidgets.QPushButton("+")
            self.figure_zoom_in_button.setObjectName("decision_figure_zoom_in")
            self.figure_zoom_in_button.clicked.connect(
                lambda: self._change_decision_figure_zoom(1.25)
            )
            self.figure_zoom_status = QtWidgets.QLabel("Fit")
            self.figure_zoom_status.setMinimumWidth(44)
            self.figure_full_screen_button = QtWidgets.QPushButton("Full screen")
            self.figure_full_screen_button.setObjectName("decision_figure_full_screen")
            self.figure_full_screen_button.clicked.connect(self._show_figure_full_screen)
            figure_controls.addWidget(self.decision_figure_choice, 1)
            figure_controls.addWidget(self.figure_fit_button)
            figure_controls.addWidget(self.figure_actual_size_button)
            figure_controls.addWidget(self.figure_zoom_out_button)
            figure_controls.addWidget(self.figure_zoom_in_button)
            figure_controls.addWidget(self.figure_zoom_status)
            figure_controls.addWidget(self.figure_full_screen_button)
            self.decision_figure_caption = QtWidgets.QLabel()
            self.decision_figure_caption.setObjectName("decision_figure_caption")
            self.decision_figure_caption.setWordWrap(True)
            self.decision_figure_view = QtWidgets.QLabel(
                "Decision-support figures will appear here as they are retained."
            )
            self.decision_figure_view.setObjectName("decision_figure_view")
            self.decision_figure_view.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.decision_figure_view.setMinimumHeight(180)
            self.decision_figure_view.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
            self.decision_figure_view.setContextMenuPolicy(
                QtCore.Qt.ContextMenuPolicy.CustomContextMenu
            )
            self.decision_figure_view.customContextMenuRequested.connect(
                self._show_decision_figure_context_menu
            )
            self.decision_figure_scroll = QtWidgets.QScrollArea()
            self.decision_figure_scroll.setWidgetResizable(False)
            self.decision_figure_scroll.setWidget(self.decision_figure_view)
            self.decision_figure_scroll.viewport().installEventFilter(self)
            self.decision_figure_legend = QtWidgets.QWidget()
            self.decision_figure_legend.setObjectName("decision_figure_legend")
            self.decision_figure_legend_layout = QtWidgets.QVBoxLayout(
                self.decision_figure_legend
            )
            self.decision_figure_legend_layout.setContentsMargins(5, 5, 5, 5)
            self.decision_figure_legend_layout.setSpacing(8)
            self.decision_figure_legend_layout.addStretch(1)
            self.decision_figure_legend_scroll = QtWidgets.QScrollArea()
            self.decision_figure_legend_scroll.setObjectName("decision_figure_guidance")
            self.decision_figure_legend_scroll.setWidgetResizable(True)
            self.decision_figure_legend_scroll.setWidget(self.decision_figure_legend)
            self.decision_figure_legend_scroll.setMinimumWidth(220)
            self.decision_figure_legend_scroll.setMaximumWidth(290)
            self.figure_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
            self.figure_split.setObjectName("decision_figure_splitter")
            self.figure_split.addWidget(self.decision_figure_scroll)
            self.figure_split.addWidget(self.decision_figure_legend_scroll)
            self.figure_split.setStretchFactor(0, 5)
            self.figure_split.setStretchFactor(1, 2)
            self.figure_split.setSizes([840, 250])
            figure_layout.addWidget(self.figure_controls_widget)
            figure_layout.addWidget(self.decision_figure_caption)
            figure_layout.addWidget(self.figure_split, 1)
            self.review_tabs.addTab(figure_page, "Decision figures")
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
                self.live_layout.addWidget(self.pose_split, 1)
                self.review_tabs.addTab(self.live_page, "Interactive structure")
            else:
                self.live_page = None
                self.live_layout = None
            self._detached_structure_window = None
            # Do not present an empty pseudo-viewer for the companion fallback.
            self._decision_figure_pixmap = None
            self._decision_figure_zoom = None
            self._decision_figure_source = None
            self._decision_figure_artifacts = None
            self.central_selection_status = QtWidgets.QLabel("No shared structural selection")
            self.central_selection_status.setObjectName("central_selection_status")
            self.central_selection_status.setWordWrap(True)
            self.candidates = QtWidgets.QTableWidget(0, 4)
            self.candidates.setHorizontalHeaderLabels(("Candidate", "Rank", "Summary", "Evidence"))
            self.candidates.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.candidates.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
            self.candidates.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.candidates.itemDoubleClicked.connect(self._show_candidate_evidence_details)
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
            self.detach_viewer_button = QtWidgets.QPushButton("Detach full screen")
            self.detach_viewer_button.setObjectName("detach_embedded_viewer_button")
            self.detach_viewer_button.setVisible(self.viewer_widget is not None)
            self.detach_viewer_button.clicked.connect(self.detach_embedded_viewer)
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
            viewer_row.addWidget(QtWidgets.QLabel("Scene:"), 0, 0)
            viewer_row.addWidget(self.scene_figure_choice, 0, 1)
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
            self.rationale.setPlaceholderText("Optional scientific rationale for the audit trail")
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
            full_screen = self.view_toolbar.addAction("Full Screen")
            full_screen.setShortcut("F11")
            full_screen.triggered.connect(self.toggle_full_screen)
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
            self.reports_dock = self._dock("Reports and Artifacts", self.report_list, QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, "reports_dock")
            self.tabifyDockWidget(self.logs_dock, self.reports_dock)
            self.logs_dock.hide()
            self.reports_dock.hide()
            self.logs_action = self._add_auxiliary_dock_action(
                "Logs", self.logs_dock, QtCore.Qt.DockWidgetArea.BottomDockWidgetArea,
            )
            self.artifacts_action = self._add_auxiliary_dock_action(
                "Artifacts", self.reports_dock, QtCore.Qt.DockWidgetArea.BottomDockWidgetArea,
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
            self._render_results_session_status(self.session.selection)
            self._render_central_selection_status(self.session.selection)
            self.statusBar().showMessage("Selections are proposals until explicitly approved through the application host")

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
                "final/output_directory": self.final_output_directory.text(),
                "final/engine": self.protocol_engine.currentData(),
                "final/ph": self.protocol_ph.value(),
                "final/conformers": self.protocol_conformers.value(),
                "final/seeds": self.protocol_seeds.value(),
                "final/base_seed": self.protocol_base_seed.value(),
                "final/exhaustiveness": self.protocol_exhaustiveness.value(),
                "final/modes": self.protocol_modes.value(),
                "final/energy_range": self.protocol_energy_range.value(),
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
        def _decision_figure_label(path: Path) -> str | None:
            name = path.stem.lower()
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

        @staticmethod
        def _decision_figure_explanation(label: str) -> str:
            if label.startswith("Top receptor pose — Panel"):
                return (
                    "HOW TO READ THIS FIGURE\n\n"
                    f"{label.split('— ', 1)[1]}: one retained pose in its receptor context.\n\n"
                    "Compare orientation, pocket occupancy, and contacts rather than relying only on rank."
                )
            if label.startswith("Pose interaction diagram —"):
                return (
                    "HOW TO READ THIS FIGURE\n\n"
                    "This is the full-resolution PoseEdit-style PLIP diagram for one exact retained pose. "
                    "The embedded line legend identifies interaction classes.\n\n"
                    "PLIP contacts follow geometric definitions; they do not demonstrate binding affinity."
                )
            explanations = {
                "Interactive pocket review required": (
                    "HOW TO REVIEW THIS DECISION\n\n"
                    "No static figure was retained at this checkpoint. Select a candidate row and "
                    "open Review selected region in 3D. Confirm that the colored pocket and matching "
                    "box cover the intended site on the retained receptor before approval.\n\n"
                    "Opening the structure does not approve the candidate."
                ),
                "Pocket scores and ranking — Panel A": (
                    "HOW TO READ THIS FIGURE\n\n"
                    "Panel A: candidates are ordered by P2Rank rank. The vertical axis is the P2Rank "
                    "prediction score; higher values indicate stronger predicted-pocket evidence.\n\n"
                    "Colors identify the same pockets in the structural views. Deposited-ligand "
                    "correspondence is supporting evidence, not automatic approval.\n\n"
                    "P2Rank scores are not binding affinities."
                ),
                "Pocket structural evidence — Panel B": (
                    "HOW TO READ THIS FIGURE\n\n"
                    "Panel B: color-matched pocket surfaces and proposed docking boxes on the receptor.\n\n"
                    "Filled color = predicted pocket surface\n"
                    "Matching outline = proposed docking box\n"
                    "Green = deposited-ligand evidence"
                ),
                "Pocket ranking and structural evidence": (
                    "HOW TO READ THIS FIGURE\n\n"
                    "Panel A: predicted-pocket ranking and P2Rank scores.\n"
                    "Panel B: the same color-matched pocket surfaces and proposed docking boxes "
                    "on the receptor.\n\n"
                    "Filled color = predicted pocket surface\n"
                    "Matching outline = proposed docking box\n"
                    "Green = deposited-ligand evidence\n\n"
                    "Choose a region only after comparing its score, geometry, and experimental evidence."
                ),
                "Deposited-ligand site evidence": (
                    "HOW TO READ THIS FIGURE\n\n"
                    "Panel A: the deposited ligand aligned onto the current receptor, together with "
                    "the corresponding predicted pocket and docking box.\n"
                    "Panel B: the deposited ligand's 2D chemical identity.\n\n"
                    "The ligand was observed experimentally in a related PDB structure. Its aligned "
                    "location supports site plausibility.\n\n"
                    "A mismatch or inaccessible cavity can indicate a conformational or rotamer difference. "
                    "It does not by itself prove that flexible docking is required."
                ),
                "Deposited-ligand alignment — Panel A": (
                    "HOW TO READ THIS FIGURE\n\n"
                    "Panel A: the deposited ligand aligned onto the current receptor, together with the "
                    "corresponding predicted pocket and docking box. Its location supports site plausibility."
                ),
                "Deposited-ligand identity — Panel B": (
                    "HOW TO READ THIS FIGURE\n\n"
                    "Panel B: the 2D chemical identity of the deposited ligand used as structural evidence."
                ),
                "Selected docking region": (
                    "HOW TO READ THIS FIGURE\n\n"
                    "The colored surface is the retained predicted pocket. The matching wireframe is "
                    "the docking box approved for the protocol.\n\n"
                    "The box records the searched volume; it does not establish biological validity."
                ),
                "Docking scores and cluster distribution": (
                    "HOW TO READ THIS FIGURE\n\n"
                    "Panel A: docking energies and cluster assignments for retained poses.\n\n"
                    "More negative docking energies rank more favorably within this run. Clusters group "
                    "geometrically similar poses, helping distinguish repeated solutions from alternatives.\n\n"
                    "Docking scores are computational rankings, not measured affinity or activity."
                ),
                "Docking scores and clusters — Panel A": (
                    "HOW TO READ THIS FIGURE\n\n"
                    "Panel A: docking energies and cluster assignments for retained poses. More negative "
                    "energies rank more favorably within this run. Scores are not measured affinity."
                ),
                "Docking pose representatives — Panel B": (
                    "HOW TO READ THIS FIGURE\n\n"
                    "Panel B: lowest-energy representatives from the selected pose clusters, shown together "
                    "in the receptor for direct geometric comparison."
                ),
                "Docking clusters and representative poses": (
                    "HOW TO READ THIS FIGURE\n\n"
                    "Panel A: docking energy and cluster membership for the retained poses.\n"
                    "Panel B: the lowest-energy representative from each selected cluster.\n\n"
                    "Review both score and pose geometry; energy alone should not determine the conclusion."
                ),
                "Top three poses in the receptor": (
                    "HOW TO READ THIS FIGURE\n\n"
                    "Panel A: highest-ranked retained pose.\n"
                    "Panel B: second-ranked retained pose.\n"
                    "Panel C: third-ranked retained pose.\n"
                    "Each is shown in receptor context and labeled with docking energy.\n\n"
                    "Compare orientation, pocket occupancy, and contacts rather than relying only on rank."
                ),
                "Top-pose interaction diagrams": (
                    "HOW TO READ THIS FIGURE\n\n"
                    "Panel A: interactions for the highest-ranked retained pose.\n"
                    "Panel B: interactions for the second-ranked retained pose.\n"
                    "Panel C: interactions for the third-ranked retained pose.\n"
                    "The embedded line legend identifies interaction classes.\n\n"
                    "PLIP contacts follow geometric definitions; they do not demonstrate binding affinity."
                ),
            }
            return explanations.get(
                label,
                "HOW TO READ THIS FIGURE\n\nThis is a retained scientific figure from the report.",
            )

        def _refresh_decision_figures(self, state: StudyState) -> None:
            retained = []
            seen = set()
            top_pose_sources = []
            for artifact in state.artifacts:
                if artifact.kind not in {
                    "scientific_image", "final_report_figure", "screening_report_figure",
                    "screening_interaction_diagram",
                }:
                    continue
                path = Path(artifact.path)
                if path.stem.lower().endswith("_top3_3d_snapshots"):
                    manifest = path.with_suffix(".manifest.json")
                    try:
                        record = json.loads(manifest.read_text())
                    except (OSError, json.JSONDecodeError):
                        record = {}
                    for index, source in enumerate(record.get("sources") or []):
                        source_path = Path(str(source))
                        if source_path.is_file():
                            top_pose_sources.append((
                                f"Top receptor pose — Panel {'ABC'[index]}",
                                str(source_path.resolve()),
                            ))
                label = self._decision_figure_label(path)
                figure_key = (label, path.name)
                if label is None or not path.is_file() or figure_key in seen:
                    continue
                seen.add(figure_key)
                retained.append((label, str(path.resolve())))
            retained.extend(top_pose_sources)
            available_labels = {label for label, _path in retained}
            if "Pocket ranking and structural evidence" in available_labels:
                retained = [item for item in retained if item[0] not in {
                    "Pocket scores and ranking — Panel A",
                    "Pocket structural evidence — Panel B",
                }]
            if "Deposited-ligand site evidence" in available_labels:
                retained = [item for item in retained if not item[0].startswith(
                    ("Deposited-ligand alignment", "Deposited-ligand identity")
                )]
            if "Docking clusters and representative poses" in available_labels:
                retained = [item for item in retained if item[0] not in {
                    "Docking scores and clusters — Panel A",
                    "Docking pose representatives — Panel B",
                }]
            if "Top three poses in the receptor" in available_labels:
                retained = [item for item in retained if not item[0].startswith(
                    "Top receptor pose — Panel"
                )]
            if "Top-pose interaction diagrams" in available_labels:
                retained = [item for item in retained if not item[0].startswith(
                    "Pose interaction diagram —"
                )]
            retained.sort(key=lambda item: (
                0 if item[0].startswith("Pocket ranking") else
                1 if item[0].startswith("Pocket scores") else
                2 if item[0].startswith("Deposited") else
                3 if item[0].startswith("Selected") else
                4 if item[0].startswith("Docking scores") else
                5 if item[0].startswith("Docking pose") else
                6 if item[0].startswith("Top receptor") else
                7 if item[0].startswith("Pose interaction") else 8,
                item[1],
            ))
            current = self.decision_figure_choice.currentData()
            current_scene = self.scene_figure_choice.currentData()
            existing = [
                self.decision_figure_choice.itemData(index)
                for index in range(self.decision_figure_choice.count())
            ]
            self.decision_figure_choice.blockSignals(True)
            self.decision_figure_choice.clear()
            for label, path in retained:
                self.decision_figure_choice.addItem(label, path)
            if current:
                index = self.decision_figure_choice.findData(current)
                if index >= 0:
                    self.decision_figure_choice.setCurrentIndex(index)
            self.decision_figure_choice.blockSignals(False)
            self.scene_figure_choice.blockSignals(True)
            self.scene_figure_choice.clear()
            retained_scenes = []
            for label, path in retained:
                scenes = self._scenes_for_decision_figure(Path(path))
                for panel, scene in scenes:
                    scene_label = label if len(scenes) == 1 else f"{label} — {panel}"
                    retained_scenes.append((scene_label, str(scene), path))
            for label, scene, figure in retained_scenes:
                self.scene_figure_choice.addItem(label, scene)
                self.scene_figure_choice.setItemData(
                    self.scene_figure_choice.count() - 1,
                    figure,
                    QtCore.Qt.ItemDataRole.UserRole + 1,
                )
            if current_scene:
                scene_index = self.scene_figure_choice.findData(current_scene)
                if scene_index >= 0:
                    self.scene_figure_choice.setCurrentIndex(scene_index)
            self.scene_figure_choice.blockSignals(False)
            self._show_selected_decision_figure()

        def _select_decision_figure(self, label: str) -> None:
            index = self.decision_figure_choice.findText(label)
            if index >= 0:
                self.decision_figure_choice.setCurrentIndex(index)
                self.review_tabs.setCurrentIndex(0)

        def _scene_figure_changed(self, index: int) -> None:
            if index < 0:
                return
            scene = self.scene_figure_choice.itemData(index)
            if not scene:
                return
            if self.viewer_widget is not None:
                self._open_visual_scene(Path(str(scene)))
                self.review_tabs.setCurrentIndex(1)
                return
            figure = self.scene_figure_choice.itemData(
                index, QtCore.Qt.ItemDataRole.UserRole + 1,
            )
            decision_index = self.decision_figure_choice.findData(figure)
            if decision_index >= 0:
                self.decision_figure_choice.setCurrentIndex(decision_index)

        def _review_mode_changed(self, index: int) -> None:
            """Reserve structural controls for a genuine embedded workspace."""
            embedded = self.viewer_widget is not None and index == 1
            self.pymol_controls.setVisible(embedded)
            # The molecular viewport is the primary work surface in this mode.
            # Retain the scene chooser and compact candidate navigation while
            # reclaiming explanatory/status rows that duplicate nearby panels.
            self.workspace_context.setVisible(not embedded)
            self.central_selection_status.setVisible(not embedded)
            self.viewer_status.setVisible(not embedded)
            self.candidates.setMaximumHeight(82 if embedded else 125)
            if index == 0:
                QtCore.QTimer.singleShot(0, self._rescale_decision_figure)
            elif embedded and not getattr(self, "_linked_pose_active", False):
                scene = self.scene_figure_choice.currentData()
                if scene:
                    selected = Path(str(scene)).resolve()
                    current = getattr(
                        getattr(self.viewer_coordinator, "adapter", None),
                        "report_session", None,
                    )
                    if current is None or Path(current).resolve() != selected:
                        self._open_visual_scene(selected)

        def detach_embedded_viewer(self) -> None:
            """Move the one live embedded engine into a dedicated full-screen window."""
            if self.viewer_widget is None or self.live_layout is None:
                return
            existing = self._detached_structure_window
            if existing is not None:
                existing.raise_()
                existing.activateWindow()
                return

            dialog = QtWidgets.QDialog(self, QtCore.Qt.WindowType.Window)
            dialog.setObjectName("detached_embedded_pymol_window")
            dialog.setWindowTitle("Docking Universal — Full-screen interactive structure")
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

            self.live_layout.removeWidget(self.pose_split)
            layout.addWidget(self.pose_split, 1)
            self._detached_structure_window = dialog

            restored = {"done": False}

            def restore_viewer(*_args) -> None:
                if restored["done"]:
                    return
                restored["done"] = True
                layout.removeWidget(self.pose_split)
                self.live_layout.addWidget(self.pose_split, 1)
                self.viewer_widget.show()
                self._detached_structure_window = None
                self.review_tabs.setCurrentWidget(self.live_page)
                self.raise_()
                self.activateWindow()

            dialog.finished.connect(restore_viewer)
            return_button.clicked.connect(dialog.close)
            QtGui.QShortcut(QtGui.QKeySequence("Escape"), dialog).activated.connect(dialog.close)
            dialog.showFullScreen()
            self.viewer_widget.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)

        @staticmethod
        def _decision_figure_explanation_sections(label: str) -> list[tuple[str, str]]:
            sections = {
                "Pocket ranking and structural evidence": [
                    ("Panel A", "Predicted-pocket ranking and P2Rank scores."),
                    ("Panel B", "The same color-matched pocket surfaces and proposed docking boxes on the receptor."),
                    ("Key", "Filled color: predicted pocket surface. Matching outline: proposed docking box. Green: deposited-ligand evidence."),
                ],
                "Deposited-ligand site evidence": [
                    ("Panel A", "Deposited ligand aligned onto the current receptor with the corresponding predicted pocket and docking box."),
                    ("Panel B", "The deposited ligand's 2D chemical identity."),
                    ("Interpretation", "The aligned location supports site plausibility. A mismatch can indicate a conformational or rotamer difference, but does not prove flexible docking is required."),
                ],
                "Docking clusters and representative poses": [
                    ("Panel A", "Docking energy and cluster membership for the retained poses."),
                    ("Panel B", "Lowest-energy representatives from the selected clusters in receptor context."),
                    ("Interpretation", "Review score and geometry together; energy alone should not determine the conclusion."),
                ],
                "Top three poses in the receptor": [
                    ("Panel A", "Highest-ranked retained pose in receptor context."),
                    ("Panel B", "Second-ranked retained pose in receptor context."),
                    ("Panel C", "Third-ranked retained pose in receptor context."),
                    ("Interpretation", "Compare orientation, pocket occupancy, contacts, and the displayed docking energies."),
                ],
                "Top-pose interaction diagrams": [
                    ("Panel A", "PoseEdit-style PLIP interactions for the highest-ranked retained pose."),
                    ("Panel B", "Interactions for the second-ranked retained pose."),
                    ("Panel C", "Interactions for the third-ranked retained pose."),
                    ("Key", "The embedded line legend identifies interaction classes. PLIP contacts follow geometric definitions and do not demonstrate affinity."),
                ],
            }
            if label in sections:
                return sections[label]
            explanation = StudyWindow._decision_figure_explanation(label)
            body = explanation.removeprefix("HOW TO READ THIS FIGURE\n\n")
            return [("How to read this figure", body)]

        def _render_decision_figure_explanations(self, label: str) -> None:
            layout = self.decision_figure_legend_layout
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            for heading, body in self._decision_figure_explanation_sections(label):
                card = QtWidgets.QFrame()
                card.setObjectName("figure_explanation_card")
                card.setStyleSheet(
                    "QFrame#figure_explanation_card {background:#e7e7e7;color:#202020;"
                    "border:1px solid #b8b8b8;border-radius:4px;}"
                )
                card_layout = QtWidgets.QVBoxLayout(card)
                card_layout.setContentsMargins(10, 8, 10, 9)
                title = QtWidgets.QLabel(heading)
                title_font = title.font()
                title_font.setBold(True)
                title.setFont(title_font)
                text = QtWidgets.QLabel(body)
                text.setWordWrap(True)
                text.setTextInteractionFlags(
                    QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
                )
                card_layout.addWidget(title)
                card_layout.addWidget(text)
                layout.addWidget(card)
            layout.addStretch(1)

        def _show_selected_decision_figure(self, *_args) -> None:
            value = self.decision_figure_choice.currentData()
            path = Path(str(value)) if value else None
            if path is None or not path.is_file():
                self._decision_figure_pixmap = None
                self._decision_figure_source = None
                for control in (
                    self.figure_fit_button, self.figure_actual_size_button,
                    self.figure_zoom_out_button, self.figure_zoom_in_button,
                    self.figure_full_screen_button,
                ):
                    control.setEnabled(False)
                pocket_review = any(
                    decision.kind == "select_pockets"
                    for decision in self.state.pending_decisions
                )
                self._render_decision_figure_explanations(
                    "Interactive pocket review required"
                    if pocket_review else "No retained decision figure"
                )
                self.decision_figure_caption.setText(
                    "No static pocket-review figure was retained for this preparation."
                    if pocket_review else
                    "No retained decision figure is available for this stage yet."
                )
                self.decision_figure_view.clear()
                self.decision_figure_view.setText(
                    "Select a candidate below, then choose ‘Review selected region in 3D’ "
                    "to inspect the retained receptor, pocket, and docking box before approval."
                    if pocket_review else
                    "Figures appear here after the corresponding scientific stage completes."
                )
                self._update_figure_scene_action(None)
                return
            for control in (
                self.figure_fit_button, self.figure_actual_size_button,
                self.figure_zoom_out_button, self.figure_zoom_in_button,
                self.figure_full_screen_button,
            ):
                control.setEnabled(True)
            stat = path.stat()
            source = (str(path), stat.st_mtime_ns, stat.st_size)
            if source == self._decision_figure_source and self._decision_figure_pixmap is not None:
                return
            pixmap = QtGui.QPixmap(str(path))
            if pixmap.isNull():
                self._decision_figure_pixmap = None
                self.decision_figure_view.setText(f"Figure could not be decoded: {path.name}")
                return
            self._decision_figure_pixmap = pixmap
            self._decision_figure_source = source
            self._decision_figure_zoom = None
            self.decision_figure_caption.setText(
                f"{self.decision_figure_choice.currentText()} · retained report figure"
            )
            self._render_decision_figure_explanations(
                self.decision_figure_choice.currentText()
            )
            self._update_figure_scene_action(path)
            self._rescale_decision_figure()

        @staticmethod
        def _scenes_for_decision_figure(path: Path | None) -> list[tuple[str, Path]]:
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
        def _scene_for_decision_figure(path: Path | None) -> Path | None:
            scenes = StudyWindow._scenes_for_decision_figure(path)
            return scenes[0][1] if len(scenes) == 1 else None

        def _update_figure_scene_action(self, path: Path | None) -> None:
            self._selected_figure_scenes = self._scenes_for_decision_figure(path)
            self._selected_figure_scene = (
                self._selected_figure_scenes[0][1]
                if len(self._selected_figure_scenes) == 1 else None
            )
            if self.viewer_widget is not None and self._selected_figure_scene is not None:
                scene_index = next((
                    index for index in range(self.scene_figure_choice.count())
                    if self.scene_figure_choice.itemData(index) == str(self._selected_figure_scene)
                    and self.scene_figure_choice.itemData(
                        index, QtCore.Qt.ItemDataRole.UserRole + 1,
                    ) == str(path)
                ), -1)
                if scene_index < 0:
                    scene_index = self.scene_figure_choice.findData(
                        str(self._selected_figure_scene)
                    )
                if scene_index >= 0:
                    self.scene_figure_choice.blockSignals(True)
                    self.scene_figure_choice.setCurrentIndex(scene_index)
                    self.scene_figure_choice.blockSignals(False)
            available = bool(self._selected_figure_scenes)
            self.viewer_button.setMenu(None)
            if self.viewer_widget is None and len(self._selected_figure_scenes) > 1:
                scene_menu = QtWidgets.QMenu(self.viewer_button)
                for panel, scene in self._selected_figure_scenes:
                    verb = "Load" if self.viewer_widget is not None else "Open"
                    suffix = "" if self.viewer_widget is not None else " in PyMOL"
                    action = scene_menu.addAction(f"{verb} {panel}{suffix}")
                    action.triggered.connect(
                        lambda _checked=False, selected=scene: self._open_visual_scene(selected)
                    )
                self.viewer_button.setMenu(scene_menu)
                self.viewer_button.setText(
                    "Choose 3D panel to load…" if self.viewer_widget is not None
                    else "Choose 3D panel to open in PyMOL…"
                )
            else:
                self.viewer_button.setText(
                    ("Load selected 3D scene" if self.viewer_widget is not None
                     else "Open selected 3D scene in PyMOL")
                    if available else "No 3D scene for this figure"
                )
            companion_action_available = available and self.viewer_widget is None
            self.viewer_button.setEnabled(companion_action_available)
            self.viewer_button.setVisible(companion_action_available)
            if available:
                if self.viewer_widget is not None:
                    self.structural_view.setText(
                        "Interactive 3D scene ready\n\n"
                        "Choose the retained scene in the Interactive structure tab. "
                        "Viewing does not change approval."
                    )
                else:
                    self.structural_view.setText(
                        "Interactive 3D scene ready\n\n"
                        "Open the retained scene in the PyMOL companion. "
                        "Viewing does not change approval."
                    )
            else:
                self.structural_view.setText(
                    "No 3D scene selected\n\n"
                    "Choose a figure with a retained 3D scene in Decision Figures. "
                    "This panel is not a drag-and-drop area."
                )
                self.viewer_status.setText(
                    "This figure is 2D only; use Full screen or zoom for closer inspection"
                )

        def _show_decision_figure_context_menu(self, position) -> None:
            if self._decision_figure_pixmap is None:
                return
            menu = QtWidgets.QMenu(self)
            scene = getattr(self, "_selected_figure_scene", None)
            if scene is not None:
                label = (
                    "View corresponding 3D scene"
                    if self.viewer_widget is not None
                    else "Open this figure in PyMOL"
                )
                open_pymol = menu.addAction(label)
                open_pymol.triggered.connect(self.open_visual_review)
                menu.addSeparator()
            elif getattr(self, "_selected_figure_scenes", None):
                for panel, panel_scene in self._selected_figure_scenes:
                    label = (
                        f"View {panel} in Interactive structure"
                        if self.viewer_widget is not None
                        else f"Open {panel} in PyMOL"
                    )
                    action = menu.addAction(label)
                    action.triggered.connect(
                        lambda _checked=False, selected=panel_scene: self._open_visual_scene(selected)
                    )
                menu.addSeparator()
            full_screen = menu.addAction("Open full screen")
            full_screen.triggered.connect(self._show_figure_full_screen)
            fit = menu.addAction("Fit figure")
            fit.triggered.connect(self._fit_decision_figure)
            actual = menu.addAction("View at 100%")
            actual.triggered.connect(lambda: self._set_decision_figure_zoom(1.0))
            menu.exec(self.decision_figure_view.mapToGlobal(position))

        def _fit_decision_figure(self) -> None:
            self._decision_figure_zoom = None
            self._rescale_decision_figure()

        def _set_decision_figure_zoom(self, zoom: float) -> None:
            self._decision_figure_zoom = max(0.1, min(4.0, zoom))
            self._rescale_decision_figure()

        def _change_decision_figure_zoom(self, factor: float) -> None:
            pixmap = getattr(self, "_decision_figure_pixmap", None)
            if pixmap is None or pixmap.isNull():
                return
            current = self._decision_figure_zoom
            if current is None:
                viewport = self.decision_figure_scroll.viewport().size()
                current = min(
                    max(1, viewport.width() - 8) / pixmap.width(),
                    max(1, viewport.height() - 8) / pixmap.height(),
                )
            self._set_decision_figure_zoom(current * factor)

        def _rescale_decision_figure(self) -> None:
            pixmap = getattr(self, "_decision_figure_pixmap", None)
            if pixmap is None or pixmap.isNull():
                return
            viewport = self.decision_figure_scroll.viewport().size()
            zoom = self._decision_figure_zoom
            if zoom is None:
                zoom = min(
                    max(1, viewport.width() - 8) / pixmap.width(),
                    max(1, viewport.height() - 8) / pixmap.height(),
                )
            shown = pixmap.scaled(
                max(1, round(pixmap.width() * zoom)),
                max(1, round(pixmap.height() * zoom)),
                QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            self.decision_figure_view.clear()
            self.decision_figure_view.setPixmap(shown)
            self.decision_figure_view.resize(shown.size())
            self.figure_zoom_status.setText(
                "Fit" if self._decision_figure_zoom is None else f"{round(zoom * 100)}%"
            )

        def _show_figure_full_screen(self) -> None:
            pixmap = getattr(self, "_decision_figure_pixmap", None)
            if pixmap is None or pixmap.isNull():
                return
            dialog = QtWidgets.QDialog(self)
            dialog.setWindowTitle(self.decision_figure_choice.currentText())
            dialog.setWindowFlags(dialog.windowFlags() | QtCore.Qt.WindowType.Window)
            layout = QtWidgets.QVBoxLayout(dialog)
            controls = QtWidgets.QHBoxLayout()
            title = QtWidgets.QLabel(self.decision_figure_choice.currentText())
            title_font = title.font()
            title_font.setBold(True)
            title.setFont(title_font)
            fit_button = QtWidgets.QPushButton("Fit")
            actual_button = QtWidgets.QPushButton("100%")
            zoom_out = QtWidgets.QPushButton("−")
            zoom_in = QtWidgets.QPushButton("+")
            close_button = QtWidgets.QPushButton("Exit full screen")
            controls.addWidget(title, 1)
            for button in (fit_button, actual_button, zoom_out, zoom_in, close_button):
                controls.addWidget(button)
            layout.addLayout(controls)
            image = QtWidgets.QLabel()
            image.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(False)
            scroll.setWidget(image)
            guidance = QtWidgets.QWidget()
            guidance.setObjectName("full_screen_figure_guidance")
            guidance_layout = QtWidgets.QVBoxLayout(guidance)
            guidance_layout.setContentsMargins(6, 6, 6, 6)
            guidance_layout.setSpacing(10)
            for heading, body in self._decision_figure_explanation_sections(
                self.decision_figure_choice.currentText()
            ):
                card = QtWidgets.QFrame()
                card.setObjectName("full_screen_figure_explanation_card")
                card.setStyleSheet(
                    "QFrame#full_screen_figure_explanation_card {background:#e7e7e7;"
                    "color:#202020;border:1px solid #b8b8b8;border-radius:5px;}"
                )
                card_layout = QtWidgets.QVBoxLayout(card)
                card_layout.setContentsMargins(13, 11, 13, 12)
                card_title = QtWidgets.QLabel(heading)
                card_title_font = card_title.font()
                card_title_font.setBold(True)
                card_title_font.setPointSize(card_title_font.pointSize() + 1)
                card_title.setFont(card_title_font)
                card_text = QtWidgets.QLabel(body)
                card_text.setWordWrap(True)
                card_text.setTextInteractionFlags(
                    QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
                )
                card_layout.addWidget(card_title)
                card_layout.addWidget(card_text)
                guidance_layout.addWidget(card)
            guidance_layout.addStretch(1)
            guidance_scroll = QtWidgets.QScrollArea()
            guidance_scroll.setObjectName("full_screen_figure_guidance_scroll")
            guidance_scroll.setWidgetResizable(True)
            guidance_scroll.setWidget(guidance)
            guidance_scroll.setMinimumWidth(270)
            guidance_scroll.setMaximumWidth(340)
            full_screen_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
            full_screen_split.setObjectName("full_screen_figure_splitter")
            full_screen_split.addWidget(scroll)
            full_screen_split.addWidget(guidance_scroll)
            full_screen_split.setStretchFactor(0, 1)
            full_screen_split.setStretchFactor(1, 0)
            full_screen_split.setSizes([1500, 310])
            layout.addWidget(full_screen_split, 1)
            zoom = {"value": None}

            def render() -> None:
                value = zoom["value"]
                if value is None:
                    viewport = scroll.viewport().size()
                    value = min(
                        max(1, viewport.width() - 8) / pixmap.width(),
                        max(1, viewport.height() - 8) / pixmap.height(),
                    )
                shown = pixmap.scaled(
                    max(1, round(pixmap.width() * value)),
                    max(1, round(pixmap.height() * value)),
                    QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                )
                image.setPixmap(shown)
                image.resize(shown.size())

            def change(factor: float) -> None:
                if zoom["value"] is None:
                    viewport = scroll.viewport().size()
                    zoom["value"] = min(
                        max(1, viewport.width() - 8) / pixmap.width(),
                        max(1, viewport.height() - 8) / pixmap.height(),
                    )
                zoom["value"] = max(0.1, min(4.0, zoom["value"] * factor))
                render()

            fit_button.clicked.connect(lambda: (zoom.update(value=None), render()))
            actual_button.clicked.connect(lambda: (zoom.update(value=1.0), render()))
            zoom_out.clicked.connect(lambda: change(1 / 1.25))
            zoom_in.clicked.connect(lambda: change(1.25))
            close_button.clicked.connect(dialog.close)
            dialog.showFullScreen()
            QtCore.QTimer.singleShot(0, render)
            self._figure_full_screen_dialog = dialog
            self._figure_full_screen_guidance = guidance

        def eventFilter(self, watched, event):
            if (
                hasattr(self, "decision_figure_scroll")
                and watched is self.decision_figure_scroll.viewport()
                and event.type() == QtCore.QEvent.Type.Resize
            ):
                QtCore.QTimer.singleShot(0, self._rescale_decision_figure)
            return super().eventFilter(watched, event)

        def _build_workflow_navigation_dock(self) -> None:
            navigation_panel = QtWidgets.QWidget()
            navigation_layout = QtWidgets.QVBoxLayout(navigation_panel)
            navigation_layout.setContentsMargins(8, 8, 8, 8)
            self.next_required_action = QtWidgets.QLabel()
            self.next_required_action.setObjectName("next_required_action")
            self.next_required_action.setWordWrap(True)
            self.next_required_action.setStyleSheet(
                "QLabel { background: #eef5ff; border: 1px solid #8bb7e8; "
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
                QtWidgets.QDockWidget.DockWidgetMovable
                | QtWidgets.QDockWidget.DockWidgetFloatable
            )
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
            regions_approved = (
                state.workflow_data.get("latest_control_status") == "approved"
                if control_path else bool(state.selected_pocket_ids and not pending_pockets)
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
                    "control_validation": 1,
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
            elif has_bundle and not screening_started:
                active_row = 4
                next_action = "Protocol validated. Choose ligands to begin sequential screening." if control_path else "Protocol finalized. Choose ligands to begin sequential screening."
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
                elapsed_text = "Calculation active"
                if state.active_job.started_at:
                    try:
                        started = datetime.fromisoformat(state.active_job.started_at.replace("Z", "+00:00"))
                        seconds = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
                        elapsed_text += f" · elapsed {seconds // 60}:{seconds % 60:02d}"
                    except (ValueError, TypeError):
                        pass
                self.running_elapsed.setText(elapsed_text)
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
                        else f"Docking outputs %v/{active.progress_total}"
                    )
                else:
                    self.active_stage_progress.setRange(0, 0)

        def _activate_workflow_target(self, target: str) -> None:
            self._workflow_target = target
            self._update_stage_review_visibility()
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
            if target == "screening_results_dock":
                self.right_review_stack.setCurrentWidget(self.results_review_panel)
                self._select_decision_figure("Docking clusters and representative poses")
                if self.screening_results_dock.isFloating():
                    self.screening_results_dock.raise_()
                    self.screening_results_dock.activateWindow()
            else:
                if target == "central":
                    self.right_review_stack.setCurrentWidget(self.pocket_evidence_panel)
                    if self.viewer_widget is not None:
                        self.review_tabs.setCurrentIndex(1)
                    else:
                        self._select_decision_figure("Pocket ranking and structural evidence")
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
            embedded = self.viewer_widget is not None and self.review_tabs.currentIndex() == 1
            self.workspace_context.setVisible(review and not embedded)
            self.central_selection_status.setVisible(review and not embedded)
            self.pymol_controls.setVisible(review and embedded)
            self.candidates.setVisible(pocket_review)
            self.region_approval_controls.setVisible(pocket_review)
            if hasattr(self, "stage_form_scroll"):
                self.stage_form_heading.setVisible(not review)
                self.stage_form_scroll.setVisible(not review)
                self.study_setup_dock.hide()
                self.pocket_evidence_dock.setVisible(review)
            figures_available = self.decision_figure_choice.count() > 0
            self.figure_controls_widget.setVisible(figures_available)
            self.figure_split.setVisible(figures_available)
            self.decision_figure_legend_scroll.setVisible(figures_available)
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
            if setup.get("record_origin") == "reconstructed_from_retained_artifacts":
                self.study_setup_panel.lock_notice.setText(
                    "This completed study predates the setup record. Available values were recovered "
                    "from retained artifacts and are read-only. Create a new study to change them."
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

        def refresh(self) -> None:
            self._refresh_host_lifecycle()
            self.session.refresh()
            self.state = self.session.state
            state = self.state
            self._apply_retained_study_setup(state)
            if self.viewer_coordinator is not None:
                if hasattr(self.viewer_coordinator, "refresh_health"):
                    self.viewer_coordinator.refresh_health()
                self.session.set_viewer_state(
                    connected=bool(self.viewer_coordinator.connected),
                    report_view_available=bool(
                        self.viewer_coordinator.connected
                        and getattr(self.viewer_coordinator, "report_view_available", False)
                    ),
                    lifecycle=getattr(
                        self.viewer_coordinator, "status",
                        "connected" if self.viewer_coordinator.connected else "disconnected",
                    ),
                    error=getattr(self.viewer_coordinator, "last_error", None),
                )
            self.summary.setText(
                f"Study: {state.name}    Workflow: {state.workflow}    "
                f"Status: {state.completion_status.value}    Revision: {state.revision}"
            )
            self._update_workflow_progress(state)
            figure_artifacts = tuple(
                (artifact.kind, artifact.path) for artifact in state.artifacts
                if artifact.kind in {
                    "scientific_image", "final_report_figure", "screening_report_figure",
                    "screening_interaction_diagram",
                }
            )
            if figure_artifacts != self._decision_figure_artifacts:
                self._refresh_decision_figures(state)
                self._decision_figure_artifacts = figure_artifacts
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
                and bool(getattr(self, "_selected_figure_scenes", None))
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
            bundle_artifact = next((
                artifact for artifact in state.artifacts
                if artifact.kind == "protocol_bundle" and Path(artifact.path).is_file()
            ), None)
            self.open_final_report_button.setEnabled(final_report is not None)
            self.open_bundle_location_button.setEnabled(bundle_artifact is not None)
            approved_regions = bool(state.selected_pocket_ids and not pending)
            self.finalize_button.setEnabled(bool(
                self.host_controller.available and approved_regions and not active and not has_bundle
                and self.exploratory_approval.isChecked()
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
            self._render_candidates(state)
            self._render_artifacts(state)
            self._render_screening_results(state)
            self._refresh_pending_pose_interaction(state)
            self._render_events()
            self._update_stage_review_visibility()
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
                self, "Choose ligand SDF", "", "Structure Data File (*.sdf)",
            )
            if path:
                self.screen_ligands.setText(path)

        def choose_screen_ligand_directory(self) -> None:
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose ligand SDF directory")
            if path:
                self.screen_ligands.setText(path)

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

        def start_preparation(self) -> None:
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
            if report:
                self._open_path(Path(report.path))

        def open_bundle_location(self) -> None:
            bundle = next((
                artifact for artifact in self.state.artifacts
                if artifact.kind == "protocol_bundle" and Path(artifact.path).is_file()
            ), None)
            if bundle:
                self._open_path(Path(bundle.path).parent)

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
            self.start_screening_button.setEnabled(bool(plan and authorization_ready and not active))

        def preview_screening(self) -> None:
            if not self.host_controller.available:
                return
            try:
                self._screening_plan = self.host_controller.screening_plan(
                    self.screen_ligands.text().strip(),
                )
            except Exception as exc:
                self._screening_plan = None
                QtWidgets.QMessageBox.critical(self, "Screening inputs were rejected", str(exc))
                self._update_screening_controls()
                return
            plan = self._screening_plan
            self.screening_status.setText(
                f"{plan['compound_count']} compound(s) × {plan['conformers_per_compound']} conformers "
                f"× {plan['independent_seed_count']} seeds × {plan['docking_site_count']} sites = "
                f"{plan['total_docking_jobs']} sequential docking jobs. Engine: {plan['engine']}."
            )
            self.screen_exploratory_approval.setVisible(
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
            try:
                self.host_controller.start_screening(payload, self.state.revision)
            except Exception as exc:
                self.screening_status.setText(f"Screening could not start: {exc}")
                QtWidgets.QMessageBox.critical(self, "Screening could not start", str(exc))
                return
            self._screening_plan = None
            self.refresh()

        def _open_visual_scene(self, scene: Path) -> None:
            self._linked_pose_active = False
            if self.viewer_widget is not None:
                self.linked_pose_panel.clear_pose("Select a docked pose to view linked 2D interactions.")
                self.linked_pose_panel.hide()
            self._selected_figure_scene = Path(scene)
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
                scene = getattr(self, "_selected_figure_scene", None)
                if scene is None:
                    raise ValueError("The selected figure has no retained 3D PyMOL scene")
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

        def show_evidence_ligand(self, path: str) -> None:
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

        def _render_candidates(self, state: StudyState) -> None:
            # Polling repaints evidence; only user navigation should reload 3D.
            blocker = QtCore.QSignalBlocker(self.candidates)
            self.pocket_score_plot.set_study(state)
            self.pocket_score_scroll.setVisible(bool(self.pocket_score_plot.points))
            values = state.workflow_data.get("pocket_candidates", [])
            self.candidates.setRowCount(len(values))
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
            del blocker

        @staticmethod
        def _candidate_evidence_digest(candidate: dict, evidence: dict) -> tuple[str, str]:
            """Return a decision-sized summary; never serialize nested evidence into the table."""
            parts = []
            details = []
            conformational = evidence.get("conformational_site_evidence") or {}
            residues = ", ".join(
                f"{item.get('name', 'UNK')}{item.get('number', '?')}{item.get('chain', '')}"
                for item in conformational.get("occluding_residues", [])
            )
            status = conformational.get("status")
            if status == "conformationally_incompatible":
                parts.append(f"Rotamer conflict: {residues or 'review residues'}")
                details.append(
                    "The current receptor differs from a ligand-bound conformation; "
                    "review whether rigid docking is appropriate."
                )
            elif status == "reviewed_no_geometric_incompatibility":
                parts.append("No rotamer conflict found")
            elif status == "not_evaluated":
                parts.append("Rotamers not evaluated")

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
                item = QtWidgets.QListWidgetItem(f"{artifact.kind}: {artifact.path}")
                item.setData(QtCore.Qt.UserRole, artifact.path)
                item.setToolTip("Double-click to open this retained artifact")
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
                and bool(getattr(self, "_selected_figure_scenes", None))
                and viewer.lifecycle != "connecting"
            )
            self.viewer_button.setVisible(
                not embedded and bool(getattr(self, "_selected_figure_scenes", None))
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
                        "Waiting for its retained interaction artifact; no duplicate analysis was started."
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
                if self.viewer_widget is not None:
                    self.linked_pose_panel.clear_pose("No 2D interaction diagram is available for this selection.")
                self.interaction_diagram_view.setText(
                    "No retained PLIP 2D diagram is available for this selection. "
                    "The raw PLIP record remains listed with the study artifacts when generated."
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
            self.linked_pose_panel.show()
            return self._highlight_linked_ligand(view, highlight=highlight)

        def _highlight_linked_ligand(self, view, *, highlight=True):
            try:
                adapter = self.viewer_coordinator.adapter
                if not self.viewer_coordinator.connected:
                    adapter.launch()
                adapter.show_linked_pose(view.ligand, view.receptor, highlight=highlight)
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
                        adapter.show_linked_pose(item.ligand, item.receptor)
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
                adapter.show_linked_pose(restore.ligand, restore.receptor)
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
            self._open_path(path)

        def open_artifact(self, item) -> None:
            path = Path(str(item.data(QtCore.Qt.UserRole) or ""))
            if not path.is_file():
                QtWidgets.QMessageBox.warning(self, "Artifact unavailable", f"Artifact does not exist: {path}")
                return
            self._open_path(path)

        def _open_path(self, path: Path) -> None:
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

        def toggle_full_screen(self) -> None:
            self.showNormal() if self.isFullScreen() else self.showFullScreen()

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

        def showEvent(self, event) -> None:
            """Poll persisted state only while this workspace is actually open."""
            self.workspace_controller.shown()
            super().showEvent(event)

        def _poll_refresh(self) -> None:
            self.workspace_controller.poll()

        def closeEvent(self, event) -> None:
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
            self.workspace_controller.closed()
            self._save_form_values()
            super().closeEvent(event)
else:
    class StudyWindow:  # pragma: no cover
        def __init__(self, *_args, **_kwargs):
            require_qt()
