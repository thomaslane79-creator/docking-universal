"""Explicit model-change review; the host owns preview verification and execution."""
from .qt import QtCore, QtWidgets
from .explanations import ExplanationLabel


class ReceptorModelReviewDialog(QtWidgets.QDialog):
    def __init__(self, initial_preview, preview_callback, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Review receptor changes')
        self.resize(850, 730)
        self._preview_callback = preview_callback
        self._reviewed = None
        self._alternatives = []
        self._box_review_pending = bool(initial_preview.get('box_review_pending'))
        self._initial_backend = (initial_preview.get('preparation_backend')
            or (initial_preview.get('context') or {}).get('preparation_backend')
            or (initial_preview.get('choices') or {}).get('preparation_backend') or 'meeko')
        self._available_backends = set(initial_preview.get('available_preparation_backends', ['meeko']))
        guidance = initial_preview.get('recovery_guidance') or {}
        self.navigation_request = None
        self._guidance = guidance
        self._has_recovery_guidance = bool(guidance)
        self._suggested_backend = guidance.get('recommended_backend')
        if 'method_candidates' in guidance:
            self._suggested_backend = next((row['backend'] for row in guidance['method_candidates']
                if row['backend'] in self._available_backends and
                row['backend'] not in guidance.get('attempted_backends', [])), None)
        self._suggested_already_tried = bool(self._suggested_backend and guidance.get('last_backend') == self._suggested_backend)
        self._method_labels = {'meeko': 'Standard preparation', 'adfr': 'Alternative preparation'}
        outer = QtWidgets.QVBoxLayout(self)
        scroll = QtWidgets.QScrollArea()
        self._scroll_area = scroll
        scroll.setWidgetResizable(True)
        body = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        introduction = ExplanationLabel(
            'Exclusions change the scored receptor and are not recommended. Successful preparation does not validate the model.',
            'Reviewing receptor-model changes',
            'The original structure and reviewed docking boxes are retained. Choose only the exact changes '
            'you intend. Exclusion is not recommended: it changes the scored receptor. Successful preparation '
            'does not validate the model or binding pose. No missing residues, backbone atoms or loops are built here.')
        introduction.setWordWrap(True)
        if guidance:
            introduction.explanation_title = 'Preparation recovery guidance'
            next_step = guidance['next_step']
            if guidance.get('method_candidates') and not self._suggested_backend:
                next_step = 'No untried alternative method is available on this host. Use the guided review or corrected-input actions below.'
            if guidance.get('diagnosis_code') == 'unsupported_charge_assignment':
                next_step += (' Standard Vina scoring does not use the supplied partial charges; '
                    'AutoDock-GPU uses AD4 scoring, which does. Continuing with the retained '
                    'receptor for Vina is not yet enabled.')
            introduction.set_content(guidance['summary'] + '\n' + next_step,
                guidance['details'] + '\n\n' + introduction.details_text)
        self.recovery_guidance = introduction
        layout.addWidget(introduction)
        self.reported_exclusions = []
        inventory = {tuple(row.get(k, '') for k in ('resname', 'chain', 'number', 'insertion_code')): row
                     for row in initial_preview['residue_inventory']}
        reported = guidance.get('affected_residues') or []
        matching = []
        for identity in reported:
            key = tuple(identity.get(k, '') for k in ('resname', 'chain', 'number', 'insertion_code'))
            if key in inventory and key not in [item[0] for item in matching]:
                matching.append((key, inventory[key]))
        if matching:
            introduction.set_content('Preparation flagged these residues in this or an earlier attempt. Select any you want to remove.',
                guidance.get('details', ''))
            if guidance.get('diagnosis_code') == 'unsupported_charge_assignment':
                introduction.set_content('Some components could not be prepared. Select any you want to remove.\n'
                    'Vina ignores supplied partial charges; AD4 uses them. Continuing with all components '
                    'using Vina is not yet available.', guidance.get('details', ''))
            group = QtWidgets.QGroupBox('Select components to remove')
            group.setObjectName('reported_component_exclusions')
            group_layout = QtWidgets.QVBoxLayout(group)
            note = QtWidgets.QLabel('Leave a box unchecked to keep that component. Removed components are flagged during docking-box review. Removing one may not resolve every issue.')
            note.setWordWrap(True)
            group_layout.addWidget(note)
            selection_actions = QtWidgets.QHBoxLayout()
            select_all = QtWidgets.QPushButton('Select all')
            select_all.setObjectName('select_all_reported_exclusions')
            select_all.clicked.connect(lambda: self._set_reported_exclusions(True))
            clear_all = QtWidgets.QPushButton('Clear selection')
            clear_all.setObjectName('clear_reported_exclusions')
            clear_all.clicked.connect(lambda: self._set_reported_exclusions(False))
            selection_actions.addWidget(select_all)
            selection_actions.addWidget(clear_all)
            selection_actions.addStretch()
            group_layout.addLayout(selection_actions)
            for key, row in matching:
                problem = next((item.get('reason', '') for item in reported
                    if tuple(item.get(k, '') for k in ('resname', 'chain', 'number', 'insertion_code')) == key), '')
                checkbox = QtWidgets.QCheckBox(row['label'] + (' — ' + problem if problem else ''))
                checkbox.setObjectName('remove_reported_component')
                checkbox.toggled.connect(self._reported_exclusion_changed)
                group_layout.addWidget(checkbox)
                self.reported_exclusions.append((key, checkbox))
            layout.addWidget(group)
        self.recovery_actions = QtWidgets.QComboBox()
        self.recovery_actions.setObjectName('preparation_recovery_actions')
        for action in guidance.get('actions', []):
            if action['target'] == 'method' and not self._suggested_backend:
                continue
            self.recovery_actions.addItem(action['label'], action)
        self.recovery_action_note = ExplanationLabel('', 'Recovery steps', '')
        self.recovery_action_note.setWordWrap(True)
        self.recovery_action_button = QtWidgets.QPushButton()
        self.recovery_action_button.setObjectName('open_preparation_recovery_action')
        self.recovery_action_button.clicked.connect(self.open_recovery_action)
        self.recovery_actions.currentIndexChanged.connect(self.update_recovery_action)
        if self.recovery_actions.count():
            layout.addWidget(self.recovery_actions)
            layout.addWidget(self.recovery_action_note)
            layout.addWidget(self.recovery_action_button)
        self.box_review_notice = QtWidgets.QLabel(
            'Docking box not available yet; exclusions will be flagged when the box is generated.')
        self.box_review_notice.setWordWrap(True)
        self.box_review_notice.setVisible(self._box_review_pending)
        layout.addWidget(self.box_review_notice)
        method_row = QtWidgets.QHBoxLayout()
        self.method_summary = QtWidgets.QLabel()
        self.method_summary.setWordWrap(True)
        self.method_summary.setObjectName('reviewed_preparation_method_summary')
        self.method_summary.setToolTip('\n'.join(
            self._method_labels.get(row['backend'], row['backend']) + ': ' + row['basis']
            for row in guidance.get('method_candidates', [])))
        method_row.addWidget(self.method_summary, 1)
        self.advanced_backend_toggle = QtWidgets.QToolButton()
        self.advanced_backend_toggle.setText('Advanced…')
        self.advanced_backend_toggle.setCheckable(True)
        method_row.addWidget(self.advanced_backend_toggle)
        layout.addLayout(method_row)
        self.backend_controls = QtWidgets.QWidget()
        backend_row = QtWidgets.QHBoxLayout(self.backend_controls)
        backend_row.setContentsMargins(0, 0, 0, 0)
        backend_row.addWidget(QtWidgets.QLabel('Preparation tool'))
        self.preparation_backend = QtWidgets.QComboBox()
        self.preparation_backend.setObjectName('reviewed_receptor_preparation_backend')
        for label, value in (('Meeko', 'meeko'), ('ADFRsuite', 'adfr')):
            available = value in self._available_backends
            self.preparation_backend.addItem(label if available else label + ' — unavailable', value)
            self.preparation_backend.model().item(self.preparation_backend.count() - 1).setEnabled(available)
        self.preparation_backend.setCurrentIndex(self.preparation_backend.findData(self._initial_backend))
        if self._suggested_backend in self._available_backends and not matching:
            # This is a draft suggestion only. choices() includes the change,
            # and the host binds it to a fresh preview and explicit approval.
            self.preparation_backend.setCurrentIndex(self.preparation_backend.findData(self._suggested_backend))
        self.preparation_backend.setToolTip(
            'The selected method is included in the exact preview and requires approval. '
            'Advanced tool changes can alter atom typing and charges. '
            'Preparation success does not validate the changed receptor or binding pose.')
        self.preparation_backend.currentIndexChanged.connect(self.invalidate_preview)
        self.preparation_backend.currentIndexChanged.connect(self.update_method_summary)
        backend_row.addWidget(self.preparation_backend)
        layout.addWidget(self.backend_controls)
        roles = guidance.get('tool_roles') or {}
        if roles:
            self.tool_guide = ExplanationLabel('Cleanup pipeline and tool results',
                'Cleanup pipeline and recorded attempts',
                '1. Normalize and filter the input using the reviewed component and conformer choices.\n'
                '2. Use Reduce2 for hydrogen placement. Use PDB2PQR/PROPKA for protonation when selected by the runtime and settings.\n'
                '3. In the standard path, run strict Meeko atom typing and charge assignment. If eligible repair is needed, use PDBFixer, validate the new coordinates, then rerun strict Meeko.\n'
                '4. Validate the prepared output and flag reviewed removals using their original positions in every docking box.\n\n'
                + '\n\n'.join(roles.values()) + '\n\n' +
                '\n'.join(name + ': ' + str(status).replace('_', ' ')
                          for name, status in guidance.get('stage_statuses', {}).items()))
            self.tool_guide.setWordWrap(True)
            backend_row.addWidget(self.tool_guide, 1)
        self.backend_controls.hide()
        self.advanced_backend_toggle.toggled.connect(self.backend_controls.setVisible)
        self.update_method_summary()
        layout.addWidget(QtWidgets.QLabel('Deposited alternate conformations (no choice is selected automatically)'))
        rows = [r for r in initial_preview['residue_inventory'] if r['alternate_locations']]
        self.alternates = QtWidgets.QTableWidget(len(rows), 3)
        self.alternates.setObjectName('receptor_alternate_locations')
        self.alternates.setHorizontalHeaderLabels(['Residue', 'Deposited occupancies', 'Choice'])
        self.alternates.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.alternates.setMaximumHeight(185)
        self.alternates.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        for index, row in enumerate(rows):
            self.alternates.setItem(index, 0, QtWidgets.QTableWidgetItem(row['label']))
            occupancies = ', '.join(f"{a['altloc']}: {a['occupancy_min']:.2f}–{a['occupancy_max']:.2f}"
                                    for a in row['alternate_locations'])
            self.alternates.setItem(index, 1, QtWidgets.QTableWidgetItem(occupancies))
            choice = QtWidgets.QComboBox()
            choice.addItem('Leave unresolved', '')
            for alternative in row['alternate_locations']:
                choice.addItem('Use ' + alternative['altloc'], alternative['altloc'])
            choice.currentIndexChanged.connect(self.invalidate_preview)
            self.alternates.setCellWidget(index, 2, choice)
            self._alternatives.append((row, choice))
        if not rows:
            self.alternates.hide()
            layout.addWidget(QtWidgets.QLabel('No nonblank alternate-location labels were found in these input coordinates.'))
        else:
            layout.addWidget(self.alternates)
            explanation = ExplanationLabel('Occupancy is a deposited fraction, not a quality score.',
                'Alternate conformations and occupancy',
                'Occupancy is the deposited fraction for that conformation. A higher occupancy is not a docking score or proof of correctness. A and B are labels, not quality grades.')
            explanation.setWordWrap(True)
            layout.addWidget(explanation)
        partial = [r['label'] + ' missing ' + ', '.join(r['missing_backbone_atom_names'])
                   for r in initial_preview['residue_inventory'] if r['missing_backbone_atom_names']]
        self.partial_note = QtWidgets.QLabel(
            'Incomplete standard-residue backbone inventory: ' + '; '.join(partial[:5])
            + (f'; {len(partial) - 5} more in the retained inventory.' if len(partial) > 5 else '')
            if partial else 'Observed-backbone inventory found no missing N, CA, C or O names in standard amino acids. '
                            'This is not a complete chemistry check.')
        self.partial_note.setWordWrap(True)
        layout.addWidget(self.partial_note)
        manual_exclusions = QtWidgets.QWidget()
        manual_layout = QtWidgets.QVBoxLayout(manual_exclusions)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_layout.addWidget(QtWidgets.QLabel('Other exact omissions — leave blank to keep all components'))
        self.exclusions = QtWidgets.QPlainTextEdit()
        self.exclusions.setObjectName('receptor_exact_exclusions')
        self.exclusions.setPlaceholderText('One exact identity per line: NAG A 1\nOptional fourth field: insertion code. Use . for a blank chain.')
        self.exclusions.setFixedHeight(78)
        self.exclusions.textChanged.connect(self.invalidate_preview)
        manual_layout.addWidget(self.exclusions)
        self.manual_exclusion_toggle = None
        if matching:
            self.manual_exclusion_toggle = QtWidgets.QToolButton()
            self.manual_exclusion_toggle.setText('Remove other residues…')
            self.manual_exclusion_toggle.setCheckable(True)
            self.manual_exclusion_toggle.toggled.connect(manual_exclusions.setVisible)
            layout.addWidget(self.manual_exclusion_toggle)
            manual_exclusions.hide()
        layout.addWidget(manual_exclusions)
        self.repair_after_exclusions = QtWidgets.QCheckBox('Allow guarded side-chain repair after removals')
        self.repair_after_exclusions.setChecked(bool(guidance.get('prefer_guarded_sidechain_repair')))
        self.repair_after_exclusions.setToolTip('If strict Meeko requires it, repair missing side-chain atoms while preserving the retained heavy atoms.')
        self.repair_after_exclusions.toggled.connect(self.invalidate_preview)
        layout.addWidget(self.repair_after_exclusions)
        candidate_group = QtWidgets.QGroupBox('Local side-chain candidate — optional, explicit review required')
        candidate_layout = QtWidgets.QVBoxLayout(candidate_group)
        candidate_note = ExplanationLabel(
            'Import a locally generated candidate only after reviewing its exact added atoms.',
            'Local side-chain candidates',
            'Select a candidate receipt only after reviewing its exact missing side-chain atoms. '
            'The host verifies the parent/model hashes and every unchanged observed record. '
            'This imports a locally generated candidate; it does not generate atoms or prove chemical correctness.')
        candidate_note.setWordWrap(True)
        candidate_layout.addWidget(candidate_note)
        candidate_row = QtWidgets.QHBoxLayout()
        self.sidechain_candidate = QtWidgets.QLineEdit()
        self.sidechain_candidate.setObjectName('receptor_sidechain_candidate')
        self.sidechain_candidate.setPlaceholderText('Optional local candidate receipt (.json)')
        self.sidechain_candidate.textChanged.connect(self.invalidate_preview)
        candidate_row.addWidget(self.sidechain_candidate, 1)
        browse_candidate = QtWidgets.QPushButton('Browse…')
        browse_candidate.clicked.connect(self.browse_candidate)
        candidate_row.addWidget(browse_candidate)
        candidate_layout.addLayout(candidate_row)
        self.candidate_toggle = QtWidgets.QToolButton()
        self.candidate_toggle.setText('Local side-chain candidate…')
        self.candidate_toggle.setCheckable(True)
        self.candidate_toggle.setVisible(self._box_review_pending)
        self.candidate_toggle.toggled.connect(candidate_group.setVisible)
        layout.addWidget(self.candidate_toggle)
        layout.addWidget(candidate_group)
        candidate_group.setVisible(not self._box_review_pending)
        self.preview_button = QtWidgets.QPushButton('Preview method and optional changes' if guidance else
            'Preview exact changes' if self._box_review_pending else 'Preview exact changes and distances to selected boxes')
        self.preview_button.clicked.connect(self.preview)
        layout.addWidget(self.preview_button)
        self.details = QtWidgets.QPlainTextEdit()
        self.details.setObjectName('receptor_change_preview')
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(120)
        self.details.setPlainText('Preview the choices before approving. No receptor has been changed.')
        layout.addWidget(self.details, 1)
        self.rationale = QtWidgets.QLineEdit()
        self.rationale.setPlaceholderText('Why are these specific changes acceptable for this study?')
        self.rationale.textChanged.connect(self.update_accept)
        layout.addWidget(self.rationale)
        self.acknowledge = QtWidgets.QCheckBox(
            'I reviewed these exact changes; retain warnings when the docking box is generated.'
            if self._box_review_pending else
            'I reviewed these exact changes and box distances; retain the model-change warning.')
        self.acknowledge.toggled.connect(self.update_accept)
        layout.addWidget(self.acknowledge)
        self.protein_acknowledge = QtWidgets.QCheckBox('I understand that these exclusions remove standard amino acids from the scored receptor.')
        self.protein_acknowledge.hide()
        self.protein_acknowledge.toggled.connect(self.update_accept)
        layout.addWidget(self.protein_acknowledge)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.prepare_button = buttons.addButton('Use reviewed model and prepare', QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        self.prepare_button.setEnabled(False)
        buttons.rejected.connect(self.reject)
        self.prepare_button.clicked.connect(self.accept)
        outer.addWidget(buttons)
        if matching:
            self.details.setMaximumHeight(150)
            self.details.setPlainText('Select components above. The preview updates automatically.')
            self.acknowledge.setText('I reviewed the selected removals and understand they will be flagged in docking-box review.')
            # Keep the required confirmation next to the action, even when
            # the component list or advanced options need scrolling.
            layout.removeWidget(self.acknowledge)
            outer.insertWidget(outer.count() - 1, self.acknowledge)
            # Keep less common controls available without burying the direct
            # component choices in diagnostic and alternate-model options.
            advanced = QtWidgets.QWidget()
            advanced_layout = QtWidgets.QVBoxLayout(advanced)
            advanced_layout.setContentsMargins(0, 0, 0, 0)
            start = layout.indexOf(group) + 1
            while layout.indexOf(self.preview_button) > start:
                item = layout.takeAt(start)
                # addItem alone does not reparent widgets in Qt. They would
                # remain visible over the collapsed panel at stale positions.
                if item.widget() is not None:
                    advanced_layout.addWidget(item.widget())
                elif item.layout() is not None:
                    advanced_layout.addLayout(item.layout())
                else:
                    advanced_layout.addItem(item)
            layout.removeWidget(self.rationale)
            advanced_layout.addWidget(self.rationale)
            layout.removeWidget(self.preview_button)
            advanced_layout.addWidget(self.preview_button)
            toggle = QtWidgets.QToolButton()
            toggle.setText('More options and details…')
            toggle.setCheckable(True)
            toggle.toggled.connect(advanced.setVisible)
            options_position = layout.indexOf(self.details) + 1
            layout.insertWidget(options_position, toggle)
            layout.insertWidget(options_position + 1, advanced)
            advanced.hide()
            layout.addStretch(1)
            self.preview_button.setText('Update preview')
        self.update_recovery_action()

    def update_recovery_action(self, *_):
        action = self.recovery_actions.currentData()
        if not action:
            return
        target = action['target']
        buttons = {'method': 'Review alternative method', 'alternates': 'Choose conformation below',
                   'candidate': 'Select candidate receipt', 'new_study': 'Open new-study window',
                   'exclusions': 'Review exact omissions below',
                   'diagnostics': 'Show complete logs and study files', 'explanation': 'Read recovery steps…'}
        summary = action['instructions'].split('. ', 1)[0] + '.'
        if target == 'method':
            summary = ('Review an available method not yet tried. Its compatibility must be checked.'
                       if self._suggested_backend else 'No untried alternative method is available on this host.')
        if target == 'alternates' and not self._alternatives:
            summary = 'No selectable deposited alternatives were found. Use the corrected-structure action instead.'
        self.recovery_action_note.set_content(summary,
            action['instructions'] + '\n\n' + self._guidance.get('details', ''))
        self.recovery_action_button.setText(buttons[target])
        self.recovery_action_button.setEnabled(not (target == 'alternates' and not self._alternatives))

    def open_recovery_action(self):
        action = self.recovery_actions.currentData()
        if not action:
            return
        target = action['target']
        if target in {'diagnostics', 'new_study'}:
            self.navigation_request = target
            self.reject()
        elif target == 'method':
            self.advanced_backend_toggle.setChecked(True)
            self._scroll_area.ensureWidgetVisible(self.backend_controls)
            self.preparation_backend.setFocus()
        elif target == 'alternates' and self._alternatives:
            self._scroll_area.ensureWidgetVisible(self.alternates)
            self._alternatives[0][1].setFocus()
        elif target == 'exclusions':
            if self.manual_exclusion_toggle is not None:
                self.manual_exclusion_toggle.setChecked(True)
            self._scroll_area.ensureWidgetVisible(self.exclusions)
            self.exclusions.setFocus()
        elif target == 'candidate':
            self.candidate_toggle.setChecked(True)
            self._scroll_area.ensureWidgetVisible(self.sidechain_candidate)
            self.browse_candidate()
        else:
            self.recovery_action_note.show_explanation()

    def update_method_summary(self, *_):
        backend = self.preparation_backend.currentData()
        text = 'Method: ' + self._method_labels.get(backend, 'Unavailable')
        if self._suggested_backend:
            if backend == self._suggested_backend and backend in self._available_backends:
                text += (' (already tried; review remaining issues)' if self._suggested_already_tried
                         else ' (suggested for a checked attempt)')
            elif self._suggested_backend not in self._available_backends:
                text += ' — suggested alternative unavailable; see Explain…'
            else:
                text += ' (manual choice)'
        self.method_summary.setText(text)

    def choices(self):
        excluded = [dict(zip(('resname', 'chain', 'number', 'insertion_code'), key))
                    for key, checkbox in self.reported_exclusions if checkbox.isChecked()]
        for text in self.exclusions.toPlainText().splitlines():
            if not text.strip():
                continue
            fields = text.split()
            if len(fields) not in {3, 4}:
                raise ValueError('Use an exact residue name, chain and number, with optional insertion code.')
            excluded.append(dict(resname=fields[0], chain='' if fields[1] == '.' else fields[1],
                                 number=fields[2], insertion_code=fields[3] if len(fields) == 4 else ''))
        alternate = [{**{k: row[k] for k in ('resname', 'chain', 'number', 'insertion_code')},
                      'altloc': choice.currentData()} for row, choice in self._alternatives if choice.currentData()]
        choices = {'exclusions': excluded, 'alternate_locations': alternate}
        backend = self.preparation_backend.currentData()
        if backend not in self._available_backends:
            raise ValueError('The selected preparation backend is unavailable on this host.')
        if backend != self._initial_backend:
            choices['preparation_backend'] = backend
        candidate = self.sidechain_candidate.text().strip()
        if candidate:
            choices['sidechain_candidate'] = candidate
        elif excluded and backend == 'meeko' and self.repair_after_exclusions.isChecked():
            choices['repair_after_exclusions'] = True
        return choices

    def _set_reported_exclusions(self, checked):
        for _, checkbox in self.reported_exclusions:
            with QtCore.QSignalBlocker(checkbox):
                checkbox.setChecked(checked)
        self._reported_exclusion_changed()

    def _reported_exclusion_changed(self, *_):
        self.invalidate_preview()
        if any(checkbox.isChecked() for _, checkbox in self.reported_exclusions):
            self.preview()

    def browse_candidate(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Review local side-chain candidate receipt', '',
                                                       'Candidate receipt (*.json)')
        if path:
            self.sidechain_candidate.setText(path)

    def invalidate_preview(self, *_):
        self._reviewed = None
        self.acknowledge.setChecked(False)
        self.protein_acknowledge.setChecked(False)
        self.prepare_button.setEnabled(False)
        self.details.setPlainText('Choices changed. Preview again; nothing has been adopted or prepared.')

    def preview(self):
        try:
            record = self._preview_callback(self.choices())
            if not record['changes']:
                raise ValueError('No new recovery action was selected. Keep all components and review the recorded issues; nothing will run.'
                    if self._has_recovery_guidance else 'Select at least one explicit change, or cancel and use ordinary preparation.')
            descriptions = [row['description'] for row in record['changes']]
            text = ['HIGH-SEVERITY MODEL CHANGE' if record['severity'] == 'high' else 'Reviewed model change',
                    *descriptions,
                    f"Excluded atom records: {record['removed_atom_count']}. New modeled atoms in the candidate: "
                    f"{record.get('new_atoms_generated', 0)}. Retained coordinates are unchanged."]
            text.append('Preparation method: ' + self._method_labels[self.preparation_backend.currentData()] + '.')
            if record.get('choices', {}).get('repair_after_exclusions'):
                text.append('Guarded PDBFixer side-chain repair may run before a second strict Meeko attempt.')
            method_only = all(change.get('kind') == 'preparation_method_change' for change in record['changes'])
            self.prepare_button.setText('Keep structure and try this method' if method_only else
                'Remove selected and retry' if self.reported_exclusions else 'Use reviewed model and prepare')
            if record.get('box_review_pending'):
                text.append('Docking box not available yet; exclusions will be flagged when the box is generated.')
            for change in record['changes']:
                if change.get('kind') == 'sidechain_reconstruction':
                    generator = change['generator']
                    text.append(f"Declared local generator: {generator['software']}; {generator['method']}; "
                                f"seed {generator['seed']}. No backbone additions. Generation provenance is retained.")
            for box in record['selected_box_review']:
                text.append('Box ' + box['label'] + ':')
                text.extend(f"  {r['residue']} {r['chain'] or '.'}:{r['number']}: "
                            + ('inside this box' if r['inside_box'] else f"{r['minimum_distance_to_box_angstrom']:.2f} Å from the box")
                            for r in box['residues'])
            text.append('Distance is not permission to ignore an issue. The warning persists through protocol, docking and reports. '
                        'Only a new strict preparation attempt will run; no further automatic repair or residue deletion is allowed.')
            self.details.setPlainText('\n'.join(text))
            self._reviewed = record
            self.acknowledge.setChecked(False)
            self.protein_acknowledge.setChecked(False)
            self.protein_acknowledge.setVisible(record['severity'] == 'high')
        except (ValueError, RuntimeError, KeyError) as exc:
            self._reviewed = None
            self.details.setPlainText('Preview stopped: ' + str(exc))
        self.update_accept()

    def update_accept(self, *_):
        only_reported = (any(checkbox.isChecked() for _, checkbox in self.reported_exclusions)
            and not self.exclusions.toPlainText().strip() and not self.sidechain_candidate.text().strip()
            and not any(choice.currentData() for _, choice in self._alternatives)
            and self.preparation_backend.currentData() == self._initial_backend)
        self.prepare_button.setEnabled(bool(self._reviewed and (self.rationale.text().strip() or only_reported)
            and self.acknowledge.isChecked()
            and (self._reviewed['severity'] != 'high' or self.protein_acknowledge.isChecked())))

    def approved_change(self):
        if not self.prepare_button.isEnabled() or self._reviewed['choices'] != self.choices():
            raise ValueError('A current preview and explicit approval are required')
        rationale = self.rationale.text().strip() or 'Selected reported components for removal after review.'
        return self.choices(), self._reviewed['preview_sha256'], rationale
