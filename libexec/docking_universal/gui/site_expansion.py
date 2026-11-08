"""Exact box-expansion preview, before the existing region-approval decision."""
from .qt import QtCore, QtWidgets
from .explanations import ExplanationLabel


class SiteExpansionDialog(QtWidgets.QDialog):
    def __init__(self, candidate_ids, preview, show_box=None, parent=None):
        super().__init__(parent, QtCore.Qt.WindowType.Window)
        self.setModal(False)
        self.setWindowTitle('Combine experimental ligand sites')
        self.resize(740, 520)
        self.preview = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(ExplanationLabel(
            'Extend a starting box to cover the selected experimental ligands.',
            'How ligand-covering expansion works',
            'The engine reads the hash-verified retained experimental ligand coordinates. '
            'It moves only the faces needed to cover those ligands with the existing 4 Å '
            'bound-ligand margin. No face moves inward. The resulting size is shown below; '
            'there is no hidden overlap or maximum-expansion cutoff.\n\n'
            'Choosing this proposal replaces the selected suggestions with one unscored site. '
            'All source boxes, detector scores and ligand identities remain in its expanded '
            'evidence. This does not approve docking or change a previously approved protocol. '
            'The normal region approval is still required.'))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel('Starting box'))
        self.base = QtWidgets.QComboBox()
        self.base.addItems(candidate_ids)
        row.addWidget(self.base, 1)
        self.show_box = QtWidgets.QPushButton('Preview in 3D')
        self.show_box.setEnabled(show_box is not None)
        row.addWidget(self.show_box)
        layout.addLayout(row)
        self.geometry_table = QtWidgets.QTableWidget(3, 5)
        self.geometry_table.setHorizontalHeaderLabels(('Axis', 'Old center (Å)', 'New center (Å)', 'Old size (Å)', 'New size (Å)'))
        self.geometry_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.geometry_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.geometry_table.setMaximumHeight(140)
        layout.addWidget(self.geometry_table)
        self.details = QtWidgets.QPlainTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 1)
        self.rationale = QtWidgets.QLineEdit()
        self.rationale.setPlaceholderText('Why these ligands should share one site')
        layout.addWidget(self.rationale)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.use_box = buttons.addButton('Use box for review', QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        self.use_box.clicked.connect(self.accept)
        layout.addWidget(buttons)

        def refresh():
            try:
                self.preview = preview(self.base.currentText())
                old, new = self.preview['original_geometry'], self.preview['geometry']
                for row, axis in enumerate('xyz'):
                    values = (axis.upper(), old['center_' + axis], new['center_' + axis],
                              old['size_' + axis], new['size_' + axis])
                    for col, value in enumerate(values):
                        self.geometry_table.setItem(row, col, QtWidgets.QTableWidgetItem(
                            value if isinstance(value, str) else f'{value:.3f}'))
                lines = [f"{len(self.preview['ligands'])} complete experimental ligand(s); 4 Å margin."]
                for axis, faces in self.preview['face_extensions'].items():
                    lines.append(f"{axis.upper()} faces: −{faces['lower_extension_angstrom']:.3f} Å / +{faces['upper_extension_angstrom']:.3f} Å outward")
                review = self.preview.get('receptor_model_review') or {}
                if review:
                    lines.append('\n' + review['warning'])
                    for residue in review.get('residues', []):
                        lines.append(f"{residue['residue']} {residue['chain']}:{residue['number']}: "
                                     + ('inside proposed box' if residue['inside_box'] else
                                        f"{residue['minimum_distance_to_box_angstrom']:.2f} Å outside proposed box"))
                self.details.setPlainText('\n'.join(lines))
            except Exception as exc:
                self.preview = None
                self.geometry_table.clearContents()
                self.details.setPlainText(str(exc))
            self.show_box.setEnabled(bool(show_box and self.preview))
            self.use_box.setEnabled(bool(self.preview and self.rationale.text().strip()))

        self.base.currentIndexChanged.connect(refresh)
        self.rationale.textChanged.connect(lambda: self.use_box.setEnabled(bool(self.preview and self.rationale.text().strip())))
        def show_preview():
            try:
                show_box(self.preview['geometry'], self.preview['base_id'])
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, '3D preview unavailable', str(exc))
        self.show_box.clicked.connect(show_preview)
        refresh()
