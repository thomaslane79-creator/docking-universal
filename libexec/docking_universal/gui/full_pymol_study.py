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
        note = QtWidgets.QLabel("Review predicted pockets, ligand evidence and docking regions.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)

        evidence_page = QtWidgets.QWidget()
        evidence_layout = QtWidgets.QVBoxLayout(evidence_page)
        evidence_layout.addWidget(QtWidgets.QLabel("Predicted pockets and ligand-defined sites · select to review"))
        self.box_toggle = QtWidgets.QCheckBox('Show docking search boxes')
        self.box_toggle.setToolTip('A docking box defines the search volume. A P2Rank pocket is a predicted cavity, not the box.')
        self.box_toggle.toggled.connect(self._update_box_visibility)
        evidence_layout.addWidget(self.box_toggle)
        self.regions = QtWidgets.QComboBox()
        self.regions.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.regions.setMinimumContentsLength(12)
        # Keep the existing single-site synchronization path for callers that
        # select a site programmatically; the visible list supports multiple sites.
        self.regions.hide()
        self.site_list = QtWidgets.QListWidget()
        self.site_list.setObjectName('full_pymol_docking_sites')
        self.site_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.site_list.setToolTip('Click to view a site; double-click a pocket to center it. Use Ctrl/Command-click or Shift-click to select several.')
        self.site_list.setMinimumHeight(90)
        self.site_list.setMaximumHeight(130)
        evidence_layout.addWidget(self.site_list)
        self.animate_center = QtWidgets.QCheckBox('Animate centering')
        self.animate_center.setToolTip('Pan smoothly when centering a pocket or ligand. Zoom and orientation stay unchanged.')
        self.animate_center.setChecked(owner.smooth_site_pan.isChecked())
        self.animate_center.toggled.connect(owner.smooth_site_pan.setChecked)
        owner.smooth_site_pan.toggled.connect(self.animate_center.setChecked)
        evidence_layout.addWidget(self.animate_center)
        self.clear_sites = QtWidgets.QPushButton('Clear site selection')
        self.clear_sites.clicked.connect(self.site_list.clearSelection)
        evidence_layout.addWidget(self.clear_sites)
        self.ligand_labels = QtWidgets.QCheckBox('Label pockets and ligands')
        self.ligand_labels.setToolTip('Show pocket IDs and compound names; deposited ligand identifiers are used when names are unavailable.')
        self.ligand_labels.toggled.connect(self._update_ligand_labels)
        self.ligand_labels.hide()
        evidence_layout.addWidget(self.ligand_labels)
        self.approval_selection = QtWidgets.QLabel()
        self.approval_selection.setWordWrap(True)
        evidence_layout.addWidget(self.approval_selection)
        self.approval_note = QtWidgets.QLineEdit()
        self.approval_note.setPlaceholderText('Optional decision note')
        self.approval_note.setText(owner.rationale.text())
        self.approval_note.textChanged.connect(owner.rationale.setText)
        owner.rationale.textChanged.connect(self.approval_note.setText)
        evidence_layout.addWidget(self.approval_note)
        self.approve_regions = QtWidgets.QPushButton('Approve selected docking region(s)')
        self.approve_regions.clicked.connect(self._approve_regions)
        evidence_layout.addWidget(self.approve_regions)
        self.detail_context = QtWidgets.QLabel()
        self.detail_context.setWordWrap(True)
        evidence_layout.addWidget(self.detail_context)
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
        self.evidence.note.setText("Click a ligand to show it; click again to hide it. Ctrl/Cmd-click selects several. Viewing is not approval.")
        evidence_layout.addWidget(self.evidence, 1)
        self.tabs.addTab(evidence_page, "Pockets and sites")

        poses_page = QtWidgets.QWidget()
        poses_layout = QtWidgets.QVBoxLayout(poses_page)
        self.compounds = QtWidgets.QComboBox()
        self.clusters = QtWidgets.QComboBox()
        for heading, widget in (("Screened compound", self.compounds),):
            widget.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            widget.setMinimumContentsLength(12)
            poses_layout.addWidget(QtWidgets.QLabel(heading))
            poses_layout.addWidget(widget)
        self.clusters.hide()
        self.result_mode = QtWidgets.QComboBox()
        self.result_mode.addItem('Cluster representatives', 'clusters')
        self.result_mode.addItem('All poses', 'all_poses')
        poses_layout.addWidget(self.result_mode)
        self.animate_pose_center = QtWidgets.QCheckBox('Animate centering')
        self.animate_pose_center.setToolTip('Pan smoothly when centering a pose; uncheck for immediate centering.')
        self.animate_pose_center.setChecked(self.animate_center.isChecked())
        self.animate_pose_center.toggled.connect(self.animate_center.setChecked)
        self.animate_center.toggled.connect(self.animate_pose_center.setChecked)
        poses_layout.addWidget(self.animate_pose_center)
        self.poses = QtWidgets.QTableWidget()
        self.poses.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.poses.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.poses.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.poses.setSortingEnabled(True)
        self.poses.setToolTip('Select rows to view structures. Ctrl/Cmd-click or Shift-click to compare several; click column headings to sort.')
        poses_layout.addWidget(self.poses, 1)
        self.plip_status = QtWidgets.QLabel('Select one cluster or pose to review PLIP interactions.')
        self.plip_status.setWordWrap(True)
        poses_layout.addWidget(self.plip_status)
        self.plip_progress = QtWidgets.QProgressBar()
        self.plip_progress.setRange(0, 0)
        self.plip_progress.setTextVisible(False)
        self.plip_progress.setFixedHeight(6)
        self.plip_progress.hide()
        poses_layout.addWidget(self.plip_progress)
        self.auto_plip = QtWidgets.QCheckBox('Automatically calculate PLIP interactions')
        self.auto_plip.setToolTip('When unchecked, select Calculate PLIP to analyze a pose. Calculations already running are not stopped.')
        self.auto_plip.setChecked(getattr(owner, '_auto_plip_enabled', True))
        self.auto_plip.toggled.connect(owner._set_auto_plip_enabled)
        poses_layout.addWidget(self.auto_plip)
        self.calculate_plip = QtWidgets.QPushButton('Calculate PLIP for selected pose')
        self.calculate_plip.clicked.connect(self._calculate_selected_plip)
        poses_layout.addWidget(self.calculate_plip)
        self.paired_review = QtWidgets.QPushButton("Open 2D/3D review")
        self.paired_review.clicked.connect(lambda _checked: owner.open_selected_interaction_diagram())
        poses_layout.addWidget(self.paired_review)
        # Borrow the same controls and adapter state, rather than maintaining
        # independent contact toggles in the detached PyMOL browser.
        self.contact_controls = getattr(owner, 'cluster_contact_controls', None)
        if self.contact_controls is not None:
            visible = not self.contact_controls.isHidden()
            # Contacts can remain visible while Regions & evidence is active.
            # Keep their controls outside the tabs, next to the shared viewport.
            layout.addWidget(self.contact_controls)
            self.contact_controls.setVisible(visible)
        self.tabs.addTab(poses_page, "Docking poses")
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.regions.currentIndexChanged.connect(self._region_selected)
        self.tabs.currentChanged.connect(self._update_contact_context)
        self.site_list.itemSelectionChanged.connect(self._site_list_selected)
        self.site_list.itemClicked.connect(self._center_site)
        self.evidence.selectionChanged.connect(self._evidence_selected)
        self.evidence.ligandRequested.connect(owner.show_evidence_ligand)
        self.evidence.ligandCenterRequested.connect(self._center_evidence_ligand)
        self.evidence.ligandsRequested.connect(owner.show_evidence_ligands)
        self.evidence.interactionsRequested.connect(owner.render_evidence_interactions)
        self.compounds.currentIndexChanged.connect(self._compound_selected)
        self.clusters.currentIndexChanged.connect(self._cluster_selected)
        self.result_mode.currentIndexChanged.connect(self._result_mode_selected)
        self.poses.itemSelectionChanged.connect(self._pose_selected)
        self.poses.itemDoubleClicked.connect(self._center_pose)
        for signal in (owner.candidates.itemSelectionChanged,
                       owner.pocket_evidence_panel.selectionChanged,
                       owner.screening_results.itemSelectionChanged,
                       owner.interaction_diagram_choice.currentIndexChanged,
                       owner.pose_review_mode.currentIndexChanged,
                       owner.cluster_comparison.itemSelectionChanged,
                       owner.pose_results.itemSelectionChanged):
            signal.connect(self.refresh)
            self._connections.append(signal)
        self._plip_timer = QtCore.QTimer(self)
        self._plip_timer.setInterval(500)
        self._plip_timer.timeout.connect(self._update_plip_status)
        self._plip_timer.start()
        self.refresh()
        if getattr(owner, '_workflow_target', '') == 'screening_results_dock' and self.tabs.isTabVisible(1):
            self.tabs.setCurrentIndex(1)
        self._update_contact_context()

    def _update_contact_context(self, *_args):
        if self.contact_controls is not None:
            # PLIP contacts and their residue labels describe a selected docked
            # pose; they are not evidence for an independently selected pocket.
            self.contact_controls.setVisible(self.tabs.currentIndex() == 1 and bool(getattr(self.owner, '_linked_pose_active', False)))

    def _approve_regions(self):
        # Both windows share the same selected rows, note and approval path.
        self.owner.approve_selected_regions(dialog_parent=self.window())
        self.refresh()

    def dispose(self):
        self.owner.smooth_site_pan.toggled.disconnect(self.animate_center.setChecked)
        self.owner.rationale.textChanged.disconnect(self.approval_note.setText)
        if self.contact_controls is not None:
            self.contact_controls.set_ligand_label_mode(False)
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
        index = target.findData(current)
        if index != target.currentIndex():
            target.setCurrentIndex(index)
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
            rows = sorted(owner.candidates.selectionModel().selectedRows(), key=lambda row: row.row())
            ids = [str(candidates[row.row()]['id']) for row in rows
                   if row.row() < len(candidates)]
            from ..pocket_metadata import candidate_display_label
            visible_ids = [candidate_display_label(candidates[row.row()]) for row in rows
                           if row.row() < len(candidates)]
            pending = any(item.kind == 'select_pockets' for item in owner.state.pending_decisions)
            selected_candidates = [candidates[row.row()] for row in rows if row.row() < len(candidates)]
            ligand_only = bool(selected_candidates) and all((candidate.get('evidence') or {}).get('kind') == 'ligand_defined' for candidate in selected_candidates)
            self.ligand_labels.setVisible(bool(selected_candidates))
            if self.contact_controls is not None:
                self.contact_controls.set_ligand_label_mode(ligand_only, self._shared_labels_toggled)
            for control in (self.approval_selection, self.approval_note, self.approve_regions):
                control.setVisible(pending)
            self.approval_selection.setText('Selected for approval: ' + (', '.join(visible_ids) if visible_ids else 'none'))
            self.detail_context.setText(f'Evidence below: {visible_ids[0]}' if len(visible_ids) > 1 else '')
            self.detail_context.setVisible(len(ids) > 1)
            self.approve_regions.setEnabled(bool(ids and pending and owner.host_controller.available))
            self.approval_note.setEnabled(bool(pending and owner.host_controller.available))
            candidate = candidates[rows[0].row()] if rows and rows[0].row() < len(candidates) else None
            from ..services.preparation_site_issues import candidate_with_model_change_review
            candidate = candidate_with_model_change_review(owner.state, candidate)
            regions = []
            for item in candidates:
                score = item.get("evidence", {}).get("score")
                label = candidate_display_label(item)
                if score is not None:
                    label += f" · score {score}"
                regions.append((label, str(item["id"])))
            self._copy_choice(self.regions, regions, str(candidate["id"]) if candidate else None)
            blocker = QtCore.QSignalBlocker(self.site_list)
            existing = [(self.site_list.item(i).text(), self.site_list.item(i).data(QtCore.Qt.ItemDataRole.UserRole))
                        for i in range(self.site_list.count())]
            if existing != regions:
                self.site_list.clear()
                for label, identity in regions:
                    item = QtWidgets.QListWidgetItem(label)
                    item.setData(QtCore.Qt.ItemDataRole.UserRole, identity)
                    self.site_list.addItem(item)
            for i in range(self.site_list.count()):
                item = self.site_list.item(i)
                item.setSelected(item.data(QtCore.Qt.ItemDataRole.UserRole) in ids)
            del blocker
            self.evidence.set_candidate(candidate)
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
            mode = owner.pose_review_mode.currentData()
            self._copy_choice(self.result_mode, [('Cluster representatives', 'clusters'), ('All poses', 'all_poses')], mode)
            source_table = owner.pose_results if mode == 'all_poses' else owner.cluster_comparison
            self._sync_results_table(source_table)
            self.tabs.setTabVisible(0, bool(candidates))
            self.tabs.setTabVisible(1, bool(compounds))
            self.tabs.tabBar().setVisible(bool(candidates and compounds))
            diagram = getattr(owner, '_current_interaction_diagram', None)
            self.paired_review.setEnabled(bool(diagram and diagram.is_file()))
            self.paired_review.setToolTip(
                "Open the selected pose beside its retained 2D interactions."
                if self.paired_review.isEnabled() else
                "Select a compound and a cluster with retained 2D interactions first.")
            self._update_plip_status()
            self.status.setText(owner.viewer_status.text())
        finally:
            self._syncing = False

    def _update_plip_status(self):
        selected = self.poses.selectionModel().selectedRows()
        if len(selected) != 1:
            text = ('PLIP interactions are shown for one selection at a time.' if selected else
                    'Select one cluster or pose to review PLIP interactions.')
            running = False
        else:
            diagram = getattr(self.owner, '_current_interaction_diagram', None)
            message = self.owner.interaction_diagram_view.text().strip()
            if diagram and diagram.is_file():
                text, running = 'PLIP interactions are ready for the selected pose.', False
            elif message:
                text = message.replace('\n', ' ')
                running = ('generating' in message.lower() or 'waiting for' in message.lower())
            else:
                text, running = 'PLIP interactions are not yet available for this selection.', False
        self.plip_status.setText(text)
        self.plip_progress.setVisible(running)
        self.calculate_plip.setEnabled(len(selected) == 1 and not running and not (diagram and diagram.is_file()) if len(selected) == 1 else False)

    def _calculate_selected_plip(self):
        if len(self.poses.selectionModel().selectedRows()) != 1:
            return
        self.owner._force_plip_for_selection = True
        try:
            self._pose_selected()
        finally:
            self.owner._force_plip_for_selection = False
        self._update_plip_status()

    def _site_list_selected(self):
        if self._syncing:
            return
        identities = {item.data(QtCore.Qt.ItemDataRole.UserRole) for item in self.site_list.selectedItems()}
        candidates = self.owner.state.workflow_data.get('pocket_candidates', [])
        table = self.owner.candidates
        blocker = QtCore.QSignalBlocker(table)
        table.clearSelection()
        selection = table.selectionModel()
        for row, candidate in enumerate(candidates):
            if str(candidate['id']) in identities:
                selection.select(table.model().index(row, 0),
                    QtCore.QItemSelectionModel.SelectionFlag.Select | QtCore.QItemSelectionModel.SelectionFlag.Rows)
        del blocker
        self.owner._candidate_highlight_changed(clear_empty_overlays=True)
        self._update_contact_context()
        self._update_ligand_labels(self.ligand_labels.isChecked())
        self._update_box_visibility()
        self.refresh()

    def _center_site(self, item):
        if not item.isSelected():
            return
        identity = str(item.data(QtCore.Qt.ItemDataRole.UserRole))
        candidate = next((row for row in self.owner.state.workflow_data.get('pocket_candidates', [])
                          if str(row.get('id')) == identity), None)
        if candidate is not None:
            self.owner._center_candidate(candidate)

    def _center_evidence_ligand(self, path):
        self.owner.center_evidence_ligand(path, animate=self.animate_center.isChecked())

    def _shared_labels_toggled(self, visible):
        if not self.ligand_labels.isHidden():
            self.ligand_labels.setChecked(visible)

    def _update_ligand_labels(self, visible):
        adapter = getattr(self.owner.viewer_coordinator, 'adapter', None)
        if not callable(getattr(adapter, 'label_evidence_ligands', None)):
            return
        previous = getattr(self, '_labelled_ligands', [])
        adapter.label_evidence_ligands(previous, False)
        old_pockets = getattr(self, '_labelled_pockets', [])
        if callable(getattr(adapter, 'label_pockets', None)):
            adapter.label_pockets(old_pockets, False)
        selected = {str(item.data(QtCore.Qt.ItemDataRole.UserRole)) for item in self.site_list.selectedItems()}
        candidates = [candidate for candidate in self.owner.state.workflow_data.get('pocket_candidates', []) if str(candidate.get('id')) in selected]
        from ..pocket_metadata import candidate_pocket_number
        pockets = sorted({number for candidate in candidates if (number := candidate_pocket_number(candidate)) is not None})
        if callable(getattr(adapter, 'label_pockets', None)):
            adapter.label_pockets(pockets, bool(visible))
        self._labelled_pockets = pockets if visible else []
        has_ligand_site = any((candidate.get('evidence') or {}).get('kind') == 'ligand_defined' for candidate in candidates)
        records = list(getattr(self.owner, '_selected_ligand_label_records', [])) if has_ligand_site else []
        for index in self.evidence.table.selectionModel().selectedRows():
            item = self.evidence.table.item(index.row(), 0)
            if not item:
                continue
            observation = item.data(QtCore.Qt.ItemDataRole.UserRole + 1) or {}
            path = item.data(QtCore.Qt.ItemDataRole.UserRole)
            name = observation.get('compound_name') or observation.get('ligand_name') or observation.get('ligand')
            if path and name and not any(str(path) == str(existing[0]) for existing in records):
                records.append((str(path), str(name)))
        adapter.label_evidence_ligands(records, bool(visible))
        self._labelled_ligands = list(records) if visible else []

    def _update_box_visibility(self, *_args):
        adapter = getattr(self.owner.viewer_coordinator, 'adapter', None)
        set_visibility = getattr(adapter, 'set_site_review_visibility', None)
        if not callable(set_visibility):
            return
        selected = [str(item.data(QtCore.Qt.ItemDataRole.UserRole)) for item in self.site_list.selectedItems()]
        candidates = self.owner.state.workflow_data.get('pocket_candidates', [])
        chosen = [candidate for candidate in candidates if str(candidate.get('id')) in selected]
        set_visibility(has_selection=bool(chosen), show_boxes=self.box_toggle.isChecked())

    def _region_selected(self, *_args):
        if not self._syncing and self.regions.currentData() is not None:
            self.owner._select_plotted_candidate(self.regions.currentData())
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
        self._update_ligand_labels(self.ligand_labels.isChecked())
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

    def _result_mode_selected(self, *_args):
        if not self._syncing:
            if self.result_mode.currentData() == 'all_poses':
                self.owner.pose_cluster_filter.setCurrentIndex(self.owner.pose_cluster_filter.findData(None))
            self.owner.pose_review_mode.setCurrentIndex(self.owner.pose_review_mode.findData(self.result_mode.currentData()))
            self.refresh()

    def _sync_results_table(self, source):
        from .results_review import NumericTableItem
        headers = [source.horizontalHeaderItem(col).text() for col in range(source.columnCount())]
        rows = [[source.item(row, col) for col in range(source.columnCount())]
                for row in range(source.rowCount()) if not source.isRowHidden(row)]
        records = (tuple(headers), tuple(tuple((item.text(), str(item.data(QtCore.Qt.ItemDataRole.UserRole)),
                   str(item.data(QtCore.Qt.ItemDataRole.UserRole + 1))) if item else None for item in row) for row in rows))
        with QtCore.QSignalBlocker(self.poses):
            if records != getattr(self, '_pose_records', None):
                self.poses.setSortingEnabled(False)
                self.poses.setColumnCount(len(headers))
                self.poses.setHorizontalHeaderLabels(headers)
                self.poses.setRowCount(len(rows))
                for row_index, row in enumerate(rows):
                    for col, original in enumerate(row):
                        if original is not None:
                            item = NumericTableItem(original.text()) if isinstance(original, NumericTableItem) else QtWidgets.QTableWidgetItem(original.text())
                            for role in (QtCore.Qt.ItemDataRole.UserRole, QtCore.Qt.ItemDataRole.UserRole + 1):
                                item.setData(role, original.data(role))
                            item.setBackground(original.background())
                            item.setForeground(original.foreground())
                            item.setFont(original.font())
                            item.setToolTip(original.toolTip())
                            self.poses.setItem(row_index, col, item)
                self.poses.setSortingEnabled(True)
                self._pose_records = records
            selected = [source.item(index.row(), 0).data(QtCore.Qt.ItemDataRole.UserRole)
                        for index in source.selectionModel().selectedRows() if source.item(index.row(), 0)]
            self.poses.clearSelection()
            for row in range(self.poses.rowCount()):
                item = self.poses.item(row, 0)
                if item and item.data(QtCore.Qt.ItemDataRole.UserRole) in selected:
                    self.poses.selectionModel().select(self.poses.model().index(row, 0), QtCore.QItemSelectionModel.SelectionFlag.Select | QtCore.QItemSelectionModel.SelectionFlag.Rows)

    def _pose_selected(self):
        if self._syncing:
            return
        rows = self.poses.selectionModel().selectedRows()
        identities = [self.poses.item(row.row(), 0).data(QtCore.Qt.ItemDataRole.UserRole) for row in rows]
        table = self.owner.pose_results if self.result_mode.currentData() == 'all_poses' else self.owner.cluster_comparison
        blocker = QtCore.QSignalBlocker(table)
        table.clearSelection()
        for row in range(table.rowCount()):
            if table.item(row, 0) and table.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole) in identities:
                table.selectionModel().select(table.model().index(row, 0), QtCore.QItemSelectionModel.SelectionFlag.Select | QtCore.QItemSelectionModel.SelectionFlag.Rows)
        del blocker
        if identities:
            if table is self.owner.pose_results:
                self.owner._expanded_pose_selection_changed()
            else:
                self.owner._cluster_comparison_selected()
        self.refresh()

    def _center_pose(self, item):
        table = self.owner.pose_results if self.result_mode.currentData() == 'all_poses' else self.owner.cluster_comparison
        identity_item = self.poses.item(item.row(), 0)
        identity = identity_item.data(QtCore.Qt.ItemDataRole.UserRole) if identity_item else None
        selected = [table.item(index.row(), 0).data(QtCore.Qt.ItemDataRole.UserRole)
                    for index in table.selectionModel().selectedRows() if table.item(index.row(), 0)]
        try:
            if identity not in selected:
                raise ValueError('Select the pose before centering it')
            adapter = getattr(self.owner.viewer_coordinator, 'adapter', None)
            adapter.center_displayed_pose(selected.index(identity), animate=self.animate_pose_center.isChecked())
            self.status.setText('Centered on the selected pose; zoom unchanged')
        except (AttributeError, OSError, ValueError, RuntimeError) as exc:
            self.status.setText(f'Could not center the selected pose: {exc}')
