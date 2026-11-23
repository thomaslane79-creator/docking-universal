"""Reusable presentation surface for retained docking and interaction results."""

from __future__ import annotations

try:
    from .qt import QtCore, QtWidgets
    from .explanations import ExplanationLabel
except ImportError as exc:  # pragma: no cover - diagnosed by desktop runtime inventory
    QtCore = QtWidgets = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None


if QtWidgets is not None:
    class NumericTableItem(QtWidgets.QTableWidgetItem):
        def __lt__(self, other):
            try:
                return float(self.data(QtCore.Qt.ItemDataRole.UserRole + 1)) < float(other.data(QtCore.Qt.ItemDataRole.UserRole + 1))
            except (TypeError, ValueError):
                return super().__lt__(other)

    class InteractionDiagramLabel(QtWidgets.QLabel):
        """Clickable PLIP diagram surface for 2D-to-3D pose synchronization."""

        activated = QtCore.pyqtSignal()

        def mousePressEvent(self, event):
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                self.activated.emit()
            super().mousePressEvent(event)

    class ResultsReviewPanel(QtWidgets.QWidget):
        """Own results-review widgets without owning scientific workflow state."""

        def __init__(self, renderer_status: dict, parent=None):
            super().__init__(parent)
            self.setObjectName("results_review_panel")
            layout = QtWidgets.QVBoxLayout(self)

            session_row = QtWidgets.QHBoxLayout()
            self.session_status = QtWidgets.QLabel("No compound selected")
            self.session_status.setObjectName("results_session_status")
            self.session_status.setToolTip(
                "This recoverable selection is shared with every view of this study; it is not an approval."
            )
            session_row.addWidget(self.session_status, 1)

            warning = QtWidgets.QLabel(
                "Docking scores rank computational poses; they do not establish affinity or biological activity."
            )
            warning.setObjectName("results_scientific_warning")
            warning.setWordWrap(True)
            warning.setStyleSheet("background:#fff1b8;color:#332600;padding:6px")

            self.screening_results = QtWidgets.QTableWidget(0, 7)
            self.screening_results.setHorizontalHeaderLabels((
                "Compound", "Status", "Sites", "Planned jobs", "Best energy (kcal/mol)",
                "Scoring function", "Clusters",
            ))
            self.screening_results.horizontalHeaderItem(4).setToolTip(
                "Lowest retained estimated binding energy for this compound, not a measured affinity."
            )
            self.screening_results.horizontalHeaderItem(5).setToolTip(
                "Recorded energy model: Vina for AutoDock Vina/QuickVina-W, AD4 for AutoDock-GPU. "
                "The two scales are not interchangeable. Missing historical identities are not guessed."
            )
            self.screening_results.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.screening_results.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
            self.screening_results.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.screening_results.setHorizontalScrollMode(
                QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
            )
            screening_header = self.screening_results.horizontalHeader()
            screening_header.setSectionResizeMode(
                QtWidgets.QHeaderView.ResizeMode.ResizeToContents
            )
            screening_header.setStretchLastSection(True)

            self.cluster_comparison = QtWidgets.QTableWidget(0, 9)
            self.cluster_comparison.setObjectName('cluster_comparison_table')
            self.cluster_comparison.setHorizontalHeaderLabels(('Rank', 'Cluster', 'Site', 'Best energy', 'Median energy', 'Poses', 'Seeds', 'Starting shapes', 'PLIP'))
            self.cluster_comparison.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.cluster_comparison.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
            self.cluster_comparison.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.cluster_comparison.setSortingEnabled(True)
            self.cluster_comparison.sortItems(0, QtCore.Qt.SortOrder.AscendingOrder)
            self.cluster_comparison.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
            self.cluster_comparison.horizontalHeader().setStretchLastSection(True)
            self.cluster_comparison.setToolTip('Compare retained pose clusters. Ctrl/Cmd-click or Shift-click to overlay several; the 2D panel is hidden for a multiple selection. Click column headings to sort.')
            # Tables scroll internally; empty rows should not occupy the
            # structural review and interaction-diagram area.
            self.screening_results.setMinimumHeight(70)
            self.screening_results.setMaximumHeight(120)
            self.cluster_comparison.setMinimumHeight(75)
            self.cluster_comparison.setMaximumHeight(220)

            interaction_note = ExplanationLabel(
                'Select a cluster above to view or generate its interactions.',
                'Reading docking results and interactions',
                "Cluster comparison columns:\n"
                "Rank: the cluster's position when clusters are ordered by their best docking score; 1 is lowest.\n"
                "Cluster: the identifier for a group of similar docked poses.\n"
                "Site: the docking region where the poses were generated.\n"
                "Best energy: the lowest docking score among poses in the cluster.\n"
                "Median energy: the middle score after sorting the cluster's pose scores; for an even number, the upper middle score is used.\n"
                "Poses: how many retained docked poses are in the cluster.\n"
                "Seeds: how many distinct random-seed searches contributed poses to the cluster.\n"
                "Starting shapes: how many distinct prepared ligand conformations contributed poses to the cluster. A starting shape is not itself a docked pose.\n"
                "PLIP: whether a saved interaction diagram is available for the cluster's representative pose.\n\n"
                "The run initially prepares PLIP diagrams for the requested number of lowest-energy clusters. "
                "Other clusters can be calculated on demand, and saved interactions are reused. "
                "More seeds or starting shapes supporting a cluster do not prove that its pose is correct. "
                "Docking scores and predicted contacts do not establish binding affinity. Vina and AD4 use different "
                "energy scales and should not be combined into one ranking. All-pose review shows retained alternatives."
            )
            interaction_note.setObjectName("results_interaction_note")
            interaction_note.setWordWrap(True)

            self.renderer_status = QtWidgets.QLabel()
            self.renderer_status.setObjectName("poseedit_runtime_status")
            self.renderer_status.setWordWrap(True)
            if renderer_status["status"] == "available":
                self.renderer_status.setText("Local interaction renderer ready")
                self.renderer_status.setStyleSheet("color:#176b35")
                self.renderer_status.hide()
                interaction_note.set_content(interaction_note.summary_text,
                                             interaction_note.details_text + '\n\nLocal interaction renderer ready.')
            else:
                self.renderer_status.setText(
                    "Local interaction renderer unavailable — "
                    + ", ".join(renderer_status["missing"])
                )
                self.renderer_status.setStyleSheet("color:#8b1e1e")

            self.review_mode = QtWidgets.QComboBox()
            self.review_mode.setObjectName("pose_review_mode")
            self.review_mode.addItem("Clusters", "clusters")
            self.review_mode.addItem("All poses", "all_poses")
            self.review_mode.hide()
            self.review_mode_buttons = QtWidgets.QWidget()
            mode_layout = QtWidgets.QHBoxLayout(self.review_mode_buttons)
            mode_layout.setContentsMargins(0, 0, 0, 0)
            mode_layout.addWidget(QtWidgets.QLabel('Show:'))
            self.clusters_mode = QtWidgets.QRadioButton('Clusters')
            self.poses_mode = QtWidgets.QRadioButton('All poses')
            mode_layout.addWidget(self.clusters_mode)
            mode_layout.addWidget(self.poses_mode)
            mode_layout.addStretch(1)
            self.clusters_mode.setChecked(True)
            self.clusters_mode.toggled.connect(lambda checked: self.review_mode.setCurrentIndex(0) if checked else None)
            self.poses_mode.toggled.connect(lambda checked: self.review_mode.setCurrentIndex(1) if checked else None)
            self.review_mode.currentIndexChanged.connect(lambda index: self.clusters_mode.setChecked(True) if index == 0 else self.poses_mode.setChecked(True))
            self.cluster_filter = QtWidgets.QComboBox()
            self.cluster_filter.setObjectName("pose_cluster_filter")
            self.cluster_filter.addItem("All clusters", None)
            self.cluster_filter.setVisible(False)
            self.diagram_choice = QtWidgets.QComboBox()
            self.diagram_choice.setObjectName("interaction_diagram_choice")
            self.diagram_choice.setToolTip('Saved interaction diagrams. Select another cluster in the comparison table to generate its interactions.')
            self.diagram_choice.setAccessibleName('Saved interaction diagrams')
            self.diagram_choice_label = QtWidgets.QLabel('Saved interaction diagrams')
            self.diagram_choice_label.setBuddy(self.diagram_choice)
            self.diagram_choice.hide()
            self.diagram_choice_label.hide()

            self.diagram_view = InteractionDiagramLabel(
                "Select a screened compound to review its retained PLIP diagrams."
            )
            self.diagram_view.setObjectName("interaction_diagram_view")
            self.diagram_view.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.diagram_view.setWordWrap(True)
            self.diagram_view.setMinimumHeight(220)
            self.diagram_view.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
            self.diagram_view.setToolTip(
                "Click the ligand diagram to highlight the matching retained pose in the 3D viewer."
            )
            self.diagram_scroll = QtWidgets.QScrollArea()
            self.diagram_scroll.setObjectName("interaction_diagram_scroll")
            self.diagram_scroll.setWidgetResizable(True)
            self.diagram_scroll.setWidget(self.diagram_view)
            self.diagram_scroll.setMinimumHeight(240)

            zoom_row = QtWidgets.QHBoxLayout()
            self.interaction_context = QtWidgets.QLabel("No pose selected")
            self.interaction_context.setObjectName("interaction_pose_context")
            self.interaction_zoom = QtWidgets.QComboBox()
            self.interaction_zoom.setObjectName("interaction_zoom")
            for label, value in (("Fit", 0), ("50%", 50), ("100%", 100), ("200%", 200)):
                self.interaction_zoom.addItem(label, value)
            zoom_row.addWidget(self.interaction_context, 1)
            self.interaction_zoom_label = QtWidgets.QLabel("Diagram zoom:")
            zoom_row.addWidget(self.interaction_zoom_label)
            zoom_row.addWidget(self.interaction_zoom)

            self.pose_results = QtWidgets.QTableWidget(0, 8)
            self.pose_results.setObjectName("expanded_pose_results")
            self.pose_results.setSortingEnabled(True)
            self.pose_results.sortItems(0, QtCore.Qt.SortOrder.AscendingOrder)
            self.pose_results.setHorizontalHeaderLabels((
                "Pose", "Cluster", "Energy", "Representative", "Seed", "Conformer", "Model", "PLIP",
            ))
            self.pose_results.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.pose_results.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
            self.pose_results.setToolTip('Ctrl/Cmd-click or Shift-click to overlay several poses. Click column headings to sort.')
            self.pose_results.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.pose_results.setVisible(False)

            buttons = QtWidgets.QGridLayout()
            self.open_report_button = QtWidgets.QPushButton("Open screening report")
            self.dock_more_button = QtWidgets.QPushButton('Start another docking run…')
            self.dock_more_button.setToolTip('Dock the same compounds again or select different compounds using this project’s approved protocol.')
            self.choose_run_reports_button = QtWidgets.QPushButton('Choose runs for reports…')
            self.dock_more_button.setToolTip('Screen additional compounds using this project’s retained protocol in a separate results folder.')
            self.open_pose_session_button = QtWidgets.QPushButton("Open selected pose session")
            self.sync_pose_button = QtWidgets.QPushButton("Show selected pose in PyMOL")
            self.sync_pose_button.setObjectName("sync_selected_pose_button")
            self.sync_pose_button.setEnabled(False)
            self.open_diagram_button = QtWidgets.QPushButton("Open 2D/3D review")
            self.open_diagram_button.setObjectName("open_interaction_diagram_button")
            buttons.addWidget(self.open_report_button, 0, 0)
            buttons.addWidget(self.dock_more_button, 2, 0, 1, 2)
            buttons.addWidget(self.choose_run_reports_button, 3, 0, 1, 2)
            buttons.addWidget(self.open_pose_session_button, 0, 1)
            buttons.addWidget(self.sync_pose_button, 1, 0)
            buttons.addWidget(self.open_diagram_button, 1, 1)

            layout.addLayout(session_row)
            layout.addWidget(warning)
            summary_label = QtWidgets.QLabel('Compound summary · all clusters')
            summary_label.setToolTip('One row per compound. Best energy is the lowest score across its retained poses; changing clusters does not change this summary.')
            layout.addWidget(summary_label)
            layout.addWidget(self.screening_results)
            layout.addWidget(self.review_mode)
            layout.addWidget(self.review_mode_buttons)
            selection_hint = QtWidgets.QLabel('Ctrl/Cmd-click to show several in 3D · click a column heading to sort')
            selection_hint.setWordWrap(True)
            layout.addWidget(selection_hint)
            self.cluster_comparison_label = QtWidgets.QLabel('Cluster comparison · green = lowest energy')
            layout.addWidget(self.cluster_comparison_label)
            layout.addWidget(self.cluster_comparison)
            layout.addWidget(self.cluster_filter)
            layout.addWidget(self.pose_results)
            layout.addSpacing(8)
            layout.addWidget(interaction_note)
            layout.addWidget(self.renderer_status)
            layout.addWidget(self.diagram_choice_label)
            layout.addWidget(self.diagram_choice)
            self.smooth_site_pan = QtWidgets.QCheckBox("Animate movement between sites")
            self.smooth_site_pan.setObjectName("animate_site_changes")
            self.smooth_site_pan.setChecked(True)
            self.smooth_site_pan.setToolTip("Uncheck to move immediately between docking sites.")
            layout.addWidget(self.smooth_site_pan)
            layout.addLayout(zoom_row)
            layout.addWidget(self.diagram_scroll)
            layout.addLayout(buttons)

        def set_viewer_presentation(self, *, embedded: bool) -> None:
            """Keep external-session actions out of the embedded-viewer workflow."""
            self.smooth_site_pan.setVisible(embedded)
            self.open_pose_session_button.setVisible(not embedded)
            # Embedded pose selection already updates the structure directly.
            # The companion viewer retains the manual synchronization action.
            self.sync_pose_button.setVisible(not embedded)
            self.diagram_scroll.setVisible(not embedded)
            self.interaction_zoom.setVisible(not embedded)
            self.interaction_zoom_label.setVisible(not embedded)
            self.sync_pose_button.setText(
                "Show selected pose in interactive structure"
                if embedded else "Show selected pose in PyMOL"
            )
else:
    class ResultsReviewPanel:  # pragma: no cover
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError(f"The selected PyQt6 runtime is unavailable: {QT_IMPORT_ERROR}")
