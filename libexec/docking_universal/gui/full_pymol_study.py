"""Study navigation inside the full PyMOL shell; no second scientific state."""
from .qt import QtCore, QtWidgets
from .pocket_evidence import PocketEvidencePanel


class FullPyMOLStudyPanel(QtWidgets.QWidget):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self._syncing = False
        self._connections = []
        self.setMinimumWidth(300)
        layout = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel("Select regions and ligands. Viewing is not approval.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)

        evidence_page = QtWidgets.QWidget()
        evidence_layout = QtWidgets.QVBoxLayout(evidence_page)
        evidence_layout.addWidget(QtWidgets.QLabel("Docking region"))
        self.regions = QtWidgets.QComboBox()
        self.regions.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.regions.setMinimumContentsLength(12)
        evidence_layout.addWidget(self.regions)
        self.evidence = PocketEvidencePanel()
        self.evidence._detached_guide = True
        self.evidence.set_viewer_presentation(embedded=True)
        self.evidence.heading.setFixedHeight(self.evidence.heading.fontMetrics().lineSpacing() * 2)
        self.evidence.evidence_summary.setFixedHeight(
            self.evidence.evidence_header.height() + self.evidence.heading.height() + 16)
        self.evidence.warning_scroll.setFixedHeight(self.evidence.warning.fontMetrics().lineSpacing() * 2 + 24)
        self.evidence.warning.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.highlight_obstruction_button = self.evidence.highlight_obstruction_button
        self.evidence.residuesRequested.connect(self._highlight_obstruction)
        self.evidence.table.setMinimumHeight(150)
        for column in (0, 4, 5):
            self.evidence.table.setColumnHidden(column, True)
        self.evidence.compare_button.hide()
        self.evidence.note.hide()
        # 2D has its own independent detach route; do not offer a render action
        # here which would show its output only in the obscured main window.
        self.evidence.render_2d_button.hide()
        self.evidence.note.setText("Select observations to show their aligned ligands. Ctrl/Cmd-click selects several. Viewing does not approve a region.")
        evidence_layout.addWidget(self.evidence, 1)
        self.tabs.addTab(evidence_page, "Regions & evidence")

        poses_page = QtWidgets.QWidget()
        poses_layout = QtWidgets.QVBoxLayout(poses_page)
        self.compounds = QtWidgets.QComboBox()
        self.clusters = QtWidgets.QComboBox()
        for heading, widget in (("Screened compound", self.compounds), ("Cluster representative", self.clusters)):
            widget.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            widget.setMinimumContentsLength(12)
            poses_layout.addWidget(QtWidgets.QLabel(heading))
            poses_layout.addWidget(widget)
        poses_layout.addWidget(QtWidgets.QLabel("Exact retained poses"))
        self.poses = QtWidgets.QTableWidget(0, 4)
        self.poses.setHorizontalHeaderLabels(("Pose", "Cluster", "Score", "Representative"))
        self.poses.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.poses.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.poses.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        poses_layout.addWidget(self.poses, 1)
        # Borrow the same controls and adapter state, rather than maintaining
        # independent contact toggles in the detached PyMOL browser.
        self.contact_controls = getattr(owner, 'cluster_contact_controls', None)
        if self.contact_controls is not None:
            visible = not self.contact_controls.isHidden()
            poses_layout.addWidget(self.contact_controls)
            self.contact_controls.setVisible(visible)
        self.tabs.addTab(poses_page, "Docking poses")
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.regions.currentIndexChanged.connect(self._region_selected)
        self.evidence.selectionChanged.connect(self._evidence_selected)
        self.evidence.ligandRequested.connect(owner.show_evidence_ligand)
        self.evidence.ligandsRequested.connect(owner.show_evidence_ligands)
        self.evidence.interactionsRequested.connect(owner.render_evidence_interactions)
        self.compounds.currentIndexChanged.connect(self._compound_selected)
        self.clusters.currentIndexChanged.connect(self._cluster_selected)
        self.poses.itemSelectionChanged.connect(self._pose_selected)
        for signal in (owner.candidates.itemSelectionChanged,
                       owner.pocket_evidence_panel.selectionChanged,
                       owner.screening_results.itemSelectionChanged,
                       owner.interaction_diagram_choice.currentIndexChanged,
                       owner.pose_results.itemSelectionChanged):
            signal.connect(self.refresh)
            self._connections.append(signal)
        self.refresh()

    def dispose(self):
        if self.contact_controls is not None:
            visible = not self.contact_controls.isHidden()
            self.owner.live_layout.addWidget(self.contact_controls)
            self.contact_controls.setVisible(visible)
            self.contact_controls = None
        if self.evidence._obstruction_details_window is not None:
            self.evidence._obstruction_details_window.close()
        if self.evidence._guide_window is not None:
            self.evidence._guide_window.close()
        for signal in self._connections:
            signal.disconnect(self.refresh)
        self._connections.clear()

    @staticmethod
    def _copy_choice(target, records, current):
        blocker = QtCore.QSignalBlocker(target)
        if [(target.itemText(i), target.itemData(i)) for i in range(target.count())] != records:
            target.clear()
            for label, identity in records:
                target.addItem(label, identity)
        target.setCurrentIndex(target.findData(current))
        target.setEnabled(bool(records))
        del blocker

    def refresh(self, *_args):
        if self._syncing:
            return
        self._syncing = True
        try:
            owner = self.owner
            from ..services.pdb_lookup_status import lookup_status_for_state
            self.evidence.set_lookup_status(lookup_status_for_state(owner.state))
            candidates = owner.state.workflow_data.get("pocket_candidates", [])
            rows = owner.candidates.selectionModel().selectedRows()
            candidate = candidates[rows[0].row()] if rows and rows[0].row() < len(candidates) else None
            regions = []
            for item in candidates:
                score = item.get("evidence", {}).get("score")
                label = str(item.get("label") or item["id"])
                if score is not None:
                    label += f" · score {score}"
                regions.append((label, str(item["id"])))
            self._copy_choice(self.regions, regions, str(candidate["id"]) if candidate else None)
            self.evidence.set_candidate(candidate)
            experimental = (candidate or {}).get("evidence", {}).get("experimental_ligand_evidence") or {}
            observations = experimental.get("observations") or []
            self.evidence.heading.setText(f"{candidate['id'] if candidate else 'No region'} · {len(observations)} experimental ligand observations")
            conformation = (candidate or {}).get("evidence", {}).get("conformational_site_evidence") or {}
            self.evidence.warning.set_conformation_text(conformation, compact=True)
            self.evidence.sync_residue_highlight(getattr(owner.viewer_coordinator, "adapter", None))
            for row in range(self.evidence.table.rowCount()):
                observation = self.evidence.table.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole + 1) or {}
                tooltip = f"{observation.get('source_ligand_id', '')}\n{str(observation.get('evidence_class', '')).replace('_', ' ')}"
                for column in (1, 2, 3):
                    self.evidence.table.item(row, column).setToolTip(tooltip)
            source = owner.pocket_evidence_panel
            selected = source._selected_paths()
            if self.evidence._selected_paths() != selected:
                blocker = QtCore.QSignalBlocker(self.evidence.table)
                self.evidence.table.clearSelection()
                for row in range(self.evidence.table.rowCount()):
                    if self.evidence.table.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole) in selected:
                        self.evidence.table.selectionModel().select(self.evidence.table.model().index(row, 0),
                            QtCore.QItemSelectionModel.SelectionFlag.Select | QtCore.QItemSelectionModel.SelectionFlag.Rows)
                del blocker
            self.evidence.rendering_2d = getattr(source, "rendering_2d", False)
            self.evidence.compare_button.setEnabled(bool(selected))
            self.evidence._update_2d_action()
            compounds = [(owner.screening_results.item(row, 0).text(),
                          owner.screening_results.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole))
                         for row in range(owner.screening_results.rowCount())]
            current = owner._selected_screening_compound()
            self._copy_choice(self.compounds, compounds, str(current) if current else None)
            choice = owner.interaction_diagram_choice
            self._copy_choice(self.clusters, [(choice.itemText(i), choice.itemData(i)) for i in range(choice.count())], choice.currentData())
            pose_records = [[owner.pose_results.item(row, col).text() for col in range(4)] +
                            [owner.pose_results.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole)]
                            for row in range(owner.pose_results.rowCount())]
            if pose_records != getattr(self, "_pose_records", None):
                blocker = QtCore.QSignalBlocker(self.poses)
                self.poses.setRowCount(len(pose_records))
                for row, record in enumerate(pose_records):
                    for col in range(4):
                        item = QtWidgets.QTableWidgetItem(record[col])
                        item.setData(QtCore.Qt.ItemDataRole.UserRole, record[4])
                        self.poses.setItem(row, col, item)
                self.poses.resizeColumnsToContents()
                self._pose_records = pose_records
                del blocker
            source_rows = owner.pose_results.selectionModel().selectedRows()
            current_pose = owner.pose_results.item(source_rows[0].row(), 0).data(QtCore.Qt.ItemDataRole.UserRole) if source_rows else None
            blocker = QtCore.QSignalBlocker(self.poses)
            self.poses.clearSelection()
            for row, record in enumerate(pose_records):
                if record[4] == current_pose:
                    self.poses.selectRow(row)
            del blocker
            self.tabs.setTabVisible(0, bool(candidates))
            self.tabs.setTabVisible(1, bool(compounds))
            self.status.setText(owner.viewer_status.text())
        finally:
            self._syncing = False

    def _region_selected(self, *_args):
        if not self._syncing and self.regions.currentData() is not None:
            cmd = getattr(getattr(self.owner.viewer_coordinator, "adapter", None), "cmd", None)
            view = cmd.get_view() if cmd is not None else None
            try:
                self.owner._select_plotted_candidate(self.regions.currentData())
            finally:
                if view is not None:
                    cmd.set_view(view)
                    adapter = self.owner.viewer_coordinator.adapter
                    if hasattr(adapter, 'expand_scene_clipping'):
                        adapter.expand_scene_clipping()
            self.refresh()

    def _highlight_obstruction(self, residues):
        if not residues:
            return
        adapter = getattr(self.owner.viewer_coordinator, "adapter", None)
        try:
            if adapter is None or not hasattr(adapter, "highlight_obstruction_residues"):
                raise ValueError("Residue highlighting requires the embedded PyMOL backend")
            result = adapter.highlight_obstruction_residues(residues)
            self.owner._sync_residue_highlight_actions()
            self.evidence.sync_residue_highlight(adapter)
            shown = result.get("highlighted", True) if isinstance(result, dict) else True
            self.status.setText(f"Residue highlight {'shown' if shown else 'hidden'}. Camera unchanged.")
        except Exception as exc:
            self.evidence.sync_residue_highlight(adapter)
            self.status.setText(f"Residue highlight unavailable: {exc}")

    def _evidence_selected(self, paths):
        if self._syncing:
            return
        source = self.owner.pocket_evidence_panel
        blocker = QtCore.QSignalBlocker(source.table)
        source.table.clearSelection()
        for row in range(source.table.rowCount()):
            if source.table.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole) in paths:
                source.table.selectionModel().select(source.table.model().index(row, 0),
                    QtCore.QItemSelectionModel.SelectionFlag.Select | QtCore.QItemSelectionModel.SelectionFlag.Rows)
        del blocker
        source._selection_changed()
        self.refresh()

    def _compound_selected(self, *_args):
        if self._syncing:
            return
        table = self.owner.screening_results
        for row in range(table.rowCount()):
            if table.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole) == self.compounds.currentData():
                table.selectRow(row)
                break
        self.refresh()

    def _cluster_selected(self, *_args):
        if not self._syncing:
            self.owner.interaction_diagram_choice.setCurrentIndex(self.owner.interaction_diagram_choice.findData(self.clusters.currentData()))

    def _pose_selected(self):
        if self._syncing:
            return
        rows = self.poses.selectionModel().selectedRows()
        if not rows:
            return
        identity = self.poses.item(rows[0].row(), 0).data(QtCore.Qt.ItemDataRole.UserRole)
        table = self.owner.pose_results
        self.owner.pose_review_mode.setCurrentIndex(self.owner.pose_review_mode.findData("all_poses"))
        for row in range(table.rowCount()):
            if table.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole) == identity:
                table.selectRow(row)
                break
        self.refresh()
