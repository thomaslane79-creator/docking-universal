"""Reusable presentation surface for retained docking and interaction results."""

from __future__ import annotations

try:
    from .qt import QtCore, QtWidgets
except ImportError as exc:  # pragma: no cover - diagnosed by desktop runtime inventory
    QtCore = QtWidgets = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None


if QtWidgets is not None:
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
            self.session_status = QtWidgets.QLabel("Shared study · no pose selected")
            self.session_status.setObjectName("results_session_status")
            self.session_status.setToolTip(
                "This recoverable selection is shared with every view of this study; it is not an approval."
            )
            self.window_button = QtWidgets.QPushButton("Detach review")
            self.window_button.setObjectName("detach_results_review_button")
            session_row.addWidget(self.session_status, 1)
            session_row.addWidget(self.window_button)

            warning = QtWidgets.QLabel(
                "Docking scores rank computational poses; they do not establish affinity or biological activity."
            )
            warning.setObjectName("results_scientific_warning")
            warning.setWordWrap(True)
            warning.setStyleSheet("background:#fff1b8;color:#332600;padding:6px")

            self.screening_results = QtWidgets.QTableWidget(0, 6)
            self.screening_results.setHorizontalHeaderLabels((
                "Compound", "Status", "Sites", "Planned jobs", "Best score", "Clusters",
            ))
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

            interaction_note = QtWidgets.QLabel(
                "PLIP view: one lowest-energy representative per distinct pose cluster. "
                "Clusters are ordered by representative energy; the diagram summarizes contacts, "
                "not binding affinity."
            )
            interaction_note.setObjectName("results_interaction_note")
            interaction_note.setWordWrap(True)

            self.renderer_status = QtWidgets.QLabel()
            self.renderer_status.setObjectName("poseedit_runtime_status")
            self.renderer_status.setWordWrap(True)
            if renderer_status["status"] == "available":
                self.renderer_status.setText("Local interaction renderer ready")
                self.renderer_status.setStyleSheet("color:#176b35")
            else:
                self.renderer_status.setText(
                    "Local interaction renderer unavailable — "
                    + ", ".join(renderer_status["missing"])
                )
                self.renderer_status.setStyleSheet("color:#8b1e1e")

            self.review_mode = QtWidgets.QComboBox()
            self.review_mode.setObjectName("pose_review_mode")
            self.review_mode.addItem("Cluster synopsis", "clusters")
            self.review_mode.addItem("Expanded all-pose review", "all_poses")
            self.cluster_filter = QtWidgets.QComboBox()
            self.cluster_filter.setObjectName("pose_cluster_filter")
            self.cluster_filter.addItem("All clusters", None)
            self.cluster_filter.setVisible(False)
            self.diagram_choice = QtWidgets.QComboBox()
            self.diagram_choice.setObjectName("interaction_diagram_choice")

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
            zoom_row.addWidget(QtWidgets.QLabel("Diagram zoom:"))
            zoom_row.addWidget(self.interaction_zoom)

            self.pose_results = QtWidgets.QTableWidget(0, 7)
            self.pose_results.setObjectName("expanded_pose_results")
            self.pose_results.setHorizontalHeaderLabels((
                "Pose", "Cluster", "Score", "Representative", "Seed", "Conformer", "Model",
            ))
            self.pose_results.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.pose_results.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
            self.pose_results.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.pose_results.setVisible(False)

            buttons = QtWidgets.QGridLayout()
            self.open_report_button = QtWidgets.QPushButton("Open screening report")
            self.open_pose_session_button = QtWidgets.QPushButton("Open selected pose session")
            self.sync_pose_button = QtWidgets.QPushButton("Show selected pose in PyMOL")
            self.sync_pose_button.setObjectName("sync_selected_pose_button")
            self.sync_pose_button.setEnabled(False)
            self.open_diagram_button = QtWidgets.QPushButton("Open PLIP 2D full size")
            self.open_diagram_button.setObjectName("open_interaction_diagram_button")
            buttons.addWidget(self.open_report_button, 0, 0)
            buttons.addWidget(self.open_pose_session_button, 0, 1)
            buttons.addWidget(self.sync_pose_button, 1, 0)
            buttons.addWidget(self.open_diagram_button, 1, 1)

            layout.addLayout(session_row)
            layout.addWidget(warning)
            layout.addWidget(self.screening_results)
            layout.addWidget(interaction_note)
            layout.addWidget(self.renderer_status)
            layout.addWidget(self.review_mode)
            layout.addWidget(self.cluster_filter)
            layout.addWidget(self.diagram_choice)
            layout.addWidget(self.pose_results)
            layout.addLayout(zoom_row)
            layout.addWidget(self.diagram_scroll)
            layout.addLayout(buttons)

        def set_viewer_presentation(self, *, embedded: bool) -> None:
            """Keep external-session actions out of the embedded-viewer workflow."""
            self.open_pose_session_button.setVisible(not embedded)
            self.diagram_scroll.setVisible(not embedded)
            self.interaction_zoom.setVisible(not embedded)
            self.sync_pose_button.setText(
                "Show selected pose in interactive structure"
                if embedded else "Show selected pose in PyMOL"
            )
else:
    class ResultsReviewPanel:  # pragma: no cover
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError(f"The selected PyQt6 runtime is unavailable: {QT_IMPORT_ERROR}")
