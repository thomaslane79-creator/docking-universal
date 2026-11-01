"""Explicit model-change review; the host owns preview verification and execution."""
from .qt import QtCore, QtWidgets


class ReceptorModelReviewDialog(QtWidgets.QDialog):
    def __init__(self, initial_preview, preview_callback, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Review receptor changes — exploratory preparation')
        self.resize(850, 730)
        self._preview_callback = preview_callback
        self._reviewed = None
        self._alternatives = []
        outer = QtWidgets.QVBoxLayout(self)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        body = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        introduction = QtWidgets.QLabel(
            'The original structure and reviewed docking boxes are retained. Choose only the exact changes '
            'you intend. Exclusion is not recommended: it changes the scored receptor. Successful preparation '
            'does not validate the model or binding pose. No missing residues, backbone atoms or loops are built here.')
        introduction.setWordWrap(True)
        layout.addWidget(introduction)
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
            explanation = QtWidgets.QLabel('Occupancy is the deposited fraction for that conformation. A higher occupancy is not a docking score or proof of correctness. A and B are labels, not quality grades.')
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
        layout.addWidget(QtWidgets.QLabel('Exact residues/components to exclude — optional, not recommended'))
        self.exclusions = QtWidgets.QPlainTextEdit()
        self.exclusions.setObjectName('receptor_exact_exclusions')
        self.exclusions.setPlaceholderText('One exact identity per line: NAG A 1\nOptional fourth field: insertion code. Use . for a blank chain.')
        self.exclusions.setFixedHeight(78)
        self.exclusions.textChanged.connect(self.invalidate_preview)
        layout.addWidget(self.exclusions)
        candidate_group = QtWidgets.QGroupBox('Local side-chain candidate — optional, explicit review required')
        candidate_layout = QtWidgets.QVBoxLayout(candidate_group)
        candidate_note = QtWidgets.QLabel(
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
        layout.addWidget(candidate_group)
        self.preview_button = QtWidgets.QPushButton('Preview exact changes and distances to selected boxes')
        self.preview_button.clicked.connect(self.preview)
        layout.addWidget(self.preview_button)
        self.details = QtWidgets.QPlainTextEdit()
        self.details.setObjectName('receptor_change_preview')
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(120)
        self.details.setPlainText('Preview the choices before approving. No receptor has been changed.')
        layout.addWidget(self.details, 1)
        self.rationale = QtWidgets.QLineEdit()
        self.rationale.setPlaceholderText('Why are these specific changes acceptable for this exploratory study?')
        self.rationale.textChanged.connect(self.update_accept)
        layout.addWidget(self.rationale)
        self.acknowledge = QtWidgets.QCheckBox('I reviewed these exact changes and box distances; retain the model-change warning.')
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

    def choices(self):
        excluded = []
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
        if self.sidechain_candidate.text().strip():
            choices['sidechain_candidate'] = self.sidechain_candidate.text().strip()
        return choices

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
                raise ValueError('Select at least one explicit change, or cancel and use ordinary preparation.')
            descriptions = [row['description'] for row in record['changes']]
            text = ['HIGH-SEVERITY MODEL CHANGE' if record['severity'] == 'high' else 'Reviewed model change',
                    *descriptions,
                    f"Excluded atom records: {record['removed_atom_count']}. New modeled atoms in the candidate: "
                    f"{record.get('new_atoms_generated', 0)}. Retained coordinates are unchanged."]
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
        self.prepare_button.setEnabled(bool(self._reviewed and self.rationale.text().strip()
            and self.acknowledge.isChecked()
            and (self._reviewed['severity'] != 'high' or self.protein_acknowledge.isChecked())))

    def approved_change(self):
        if not self.prepare_button.isEnabled() or self._reviewed['choices'] != self.choices():
            raise ValueError('A current preview and explicit approval are required')
        return self.choices(), self._reviewed['preview_sha256'], self.rationale.text().strip()
