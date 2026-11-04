"""One molecule list shared by local 2D and 3D inspection."""

from .qt import QtCore, QtGui, QtWidgets
from .ligand_library_panel import CompoundPreview, LibraryReadTask
from ..services.molecule_inspection import (
    input_molecules, library_molecules, drawing_for_entry, verify_input,
    compound_3d_block, molecule_for_entry,
)


class MoleculeInspectorPanel(QtWidgets.QWidget):
    bothRequested = QtCore.pyqtSignal()
    referenceRequested = QtCore.pyqtSignal(dict)

    def __init__(self, window):
        super().__init__()
        self.setObjectName('input_structure_preview')
        self._window = window
        self._adapter = getattr(window.viewer_coordinator, 'adapter', None)
        self._viewer = window.viewer_widget
        self._borrowed = False
        self._preview_key = None
        self._preview_object_name = None
        self._picking = False
        self._overview = False
        self._split_sizes = None
        self._loading = False
        self._source_signature = None
        self._extras = []
        self._entries = []
        self._paired = False
        self._read_task = LibraryReadTask()
        self._read_task.finished.connect(self._local_file_loaded)
        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title = QtWidgets.QLabel('Molecule')
        self.title.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.choices = QtWidgets.QComboBox()
        self.choices.setObjectName('inspector_molecule_list')
        self.choices.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.choices.setMinimumContentsLength(35)
        self.choices.setMaxVisibleItems(15)
        self.open_file = QtWidgets.QPushButton('Add a local SDF/MOL file to the list…')
        self.open_file.clicked.connect(self.choose_file)
        self.add_options_button = QtWidgets.QPushButton('Add a molecule…')
        self.add_options_button.setCheckable(True)
        self.source_bar = QtWidgets.QWidget()
        source_bar_layout = QtWidgets.QHBoxLayout(self.source_bar)
        source_bar_layout.setContentsMargins(0, 0, 0, 0)
        source_bar_layout.addWidget(self.add_options_button)
        self.all_components = QtWidgets.QCheckBox('All components')
        self.all_components.setObjectName('show_all_input_components')
        self.all_components.setToolTip('Reveal common additives, detergents, sugars and supporting cofactors in the list and 3D overview. This is a display filter, not a determination of inhibitor/agonist activity; no atoms are removed from the input.')
        self.all_components.toggled.connect(self._apply_component_filter)
        source_bar_layout.addWidget(self.all_components)
        source_bar_layout.addStretch(1)
        self.source_options = QtWidgets.QWidget()
        source_layout = QtWidgets.QVBoxLayout(self.source_options)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.addWidget(self.open_file)
        smiles_row = QtWidgets.QHBoxLayout()
        self.smiles = QtWidgets.QLineEdit()
        self.smiles.setPlaceholderText('Or add a molecule by SMILES')
        self.draw_smiles_button = QtWidgets.QPushButton('Add SMILES')
        self.draw_smiles_button.clicked.connect(self.draw_smiles)
        self.smiles.returnPressed.connect(self.draw_smiles)
        smiles_row.addWidget(self.smiles, 1)
        smiles_row.addWidget(self.draw_smiles_button)
        source_layout.addLayout(smiles_row)
        self.source_options.hide()
        self.add_options_button.toggled.connect(self.source_options.setVisible)
        self.views = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.views.setObjectName('inspector_side_by_side_views')
        self.views.setChildrenCollapsible(False)
        self.picture = CompoundPreview()
        self.picture.setText('Choose an individual molecule from the list for its 2D chemical structure.')
        self.views.addWidget(self.picture)
        self.three_d_page = QtWidgets.QWidget()
        self._three_d_layout = QtWidgets.QVBoxLayout(self.three_d_page)
        self._three_d_layout.setContentsMargins(0, 0, 0, 0)
        three_d_controls = QtWidgets.QHBoxLayout()
        self.receptor_context = QtWidgets.QCheckBox('Show receptor')
        self.receptor_context.setChecked(True)
        self.receptor_context.setToolTip('Show the selected deposited ligand with its original receptor. Uncheck to view the same deposited ligand conformation alone. Screening coordinates are not overlaid on an unrelated receptor.')
        self.receptor_context.toggled.connect(self._show_current)
        three_d_controls.addWidget(self.receptor_context)
        pick_hint = QtWidgets.QLabel('Click a ligand to select it')
        pick_hint.setToolTip('The selected ligand is highlighted in cyan. Its exact chain and residue are selected in the molecule list. Use the bound-reference button to apply it for docking.')
        three_d_controls.addWidget(pick_hint)
        three_d_controls.addStretch(1)
        self._three_d_layout.addLayout(three_d_controls)
        self.three_d_message = QtWidgets.QLabel('Select a molecule to inspect its supplied 3D coordinates.')
        self.three_d_message.setWordWrap(True)
        self.three_d_message.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._three_d_layout.addWidget(self.three_d_message, 1)
        self.views.addWidget(self.three_d_page)
        self.three_d_page.hide()
        self.view_frame = QtWidgets.QWidget()
        frame_layout = QtWidgets.QVBoxLayout(self.view_frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetNoConstraint)
        self.origin = QtWidgets.QLabel()
        self.origin.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.origin.setWordWrap(True)
        self.origin.setMinimumWidth(0)
        self.origin.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
        self.action_bar = QtWidgets.QWidget()
        actions = QtWidgets.QHBoxLayout(self.action_bar)
        actions.setContentsMargins(0, 0, 0, 0)
        self.reference_button = QtWidgets.QPushButton('Use as bound reference ligand')
        self.reference_button.setObjectName('use_inspected_bound_reference')
        self.reference_button.clicked.connect(lambda: self.referenceRequested.emit(self.choices.currentData() or {}))
        self.both_button = QtWidgets.QPushButton('2D + 3D window…')
        self.both_button.setObjectName('open_paired_input_preview')
        self.both_button.clicked.connect(self.bothRequested)
        actions.addWidget(self.reference_button)
        actions.addWidget(self.both_button)
        self.choices.currentIndexChanged.connect(self._show_current)
        if self._viewer is not None and hasattr(self._viewer, 'inputMoleculePicked'):
            self._viewer.inputMoleculePicked.connect(self._picked_molecule)
        window.study_setup_panel.ligand_resname.currentTextChanged.connect(self.update_reference_action)
        window.study_setup_panel.site_mode.currentIndexChanged.connect(self.update_reference_action)
        self._arrange(False)

    def _arrange(self, paired):
        layout = self.layout()
        for widget in (self.title, self.choices, self.source_bar, self.source_options,
                       self.view_frame, self.origin, self.action_bar):
            layout.removeWidget(widget)
        for row in range(8):
            layout.setRowStretch(row, 0)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 0)
        self.add_options_button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Maximum, QtWidgets.QSizePolicy.Policy.Fixed)
        if paired:
            self.setMaximumWidth(16777215)
            self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
            self.view_frame.layout().removeWidget(self.picture)
            self.views.insertWidget(0, self.picture)
            self.view_frame.layout().addWidget(self.views)
            self.views.show()
            self.view_frame.setMinimumSize(0, 300)
            self.view_frame.setMaximumSize(16777215, 16777215)
            for row, widget in enumerate((self.title, self.choices, self.source_bar,
                                          self.source_options, self.view_frame, self.origin, self.action_bar)):
                layout.addWidget(widget, row, 0)
            layout.setRowStretch(4, 1)
        else:
            self.setMaximumWidth(780)
            self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Maximum, QtWidgets.QSizePolicy.Policy.Preferred)
            self.view_frame.layout().removeWidget(self.views)
            self.views.hide()
            self.view_frame.layout().addWidget(self.picture)
            self.view_frame.setFixedSize(280, 190)
            for row, widget in enumerate((self.title, self.choices, self.action_bar,
                                          self.source_bar, self.origin)):
                layout.addWidget(widget, row, 0)
            layout.addWidget(self.view_frame, 0, 1, 5, 1)
            layout.addWidget(self.source_options, 5, 0, 1, 2)

    @staticmethod
    def entry_key(entry):
        if not entry:
            return None
        return tuple(entry.get(key) for key in ('origin', 'path', 'sha256', 'kind', 'resname', 'chain', 'resi', 'segment', 'source', 'fingerprint', 'record_id', 'smiles'))

    def refresh_sources(self, path, library=None):
        from pathlib import Path
        source = Path(path).expanduser()
        try:
            stat = source.stat()
            signature = (str(source), stat.st_mtime_ns, stat.st_size, (library or {}).get('fingerprint'))
        except OSError:
            signature = (str(source), None, None, (library or {}).get('fingerprint'))
        if signature == self._source_signature:
            self.update_reference_action()
            return
        current = self.entry_key(self.choices.currentData())
        entries = []
        try:
            entries = input_molecules(path) if path else []
        except Exception as exc:
            self.origin.setText('Input component list unavailable: ' + str(exc))
        entries += library_molecules(library) + self._extras
        self._source_signature = signature
        self._entries = entries
        self._populate_entries(current)
        self._show_current()

    def _populate_entries(self, current=None):
        """Keep one filtered list for the drawing, native picks and 3D visibility."""
        entries = [entry for entry in self._entries
                   if self.all_components.isChecked() or not entry.get('supporting_component')]
        hidden = sum(bool(entry.get('supporting_component')) for entry in self._entries)
        self.all_components.setVisible(bool(hidden))
        self.all_components.setText('All components' + (f' ({hidden} hidden)' if hidden and not self.all_components.isChecked() else ''))
        with QtCore.QSignalBlocker(self.choices):
            self.choices.clear()
            self._append_entries(entries)
            selected = next((i for i, entry in enumerate(entries) if self.entry_key(entry) == current), None)
            if selected is None:
                selected = next((i for i, entry in enumerate(entries) if entry['kind'] != 'whole'), 0 if entries else -1)
            self.choices.setCurrentIndex(selected)

    def _apply_component_filter(self, *_args):
        current = self.entry_key(self.choices.currentData())
        self._populate_entries(current)
        self._picking = True  # Changing a display filter preserves the overview/camera.
        try:
            self._show_current()
        finally:
            self._picking = False

    def select_reference(self, identity):
        """Reveal an explicitly retained reference even if normally filtered."""
        for entry in self._entries:
            if (entry.get('origin') == 'input' and entry.get('kind') == 'component'
                    and entry.get('resname') == identity.get('resname')
                    and (entry.get('chain') or '_') == identity.get('chain_id')
                    and entry.get('residue_number') == identity.get('residue_number')
                    and entry.get('insertion_code') == identity.get('insertion_code')):
                if entry.get('supporting_component'):
                    self.all_components.setChecked(True)
                for index in range(self.choices.count()):
                    if self.entry_key(self.choices.itemData(index)) == self.entry_key(entry):
                        self.choices.setCurrentIndex(index)
                        return

    def update_reference_action(self, *_args):
        allowed, reason = self._window.reference_eligibility(self.choices.currentData())
        self.reference_button.setEnabled(allowed)
        self.reference_button.setToolTip(reason)
        panel = self._window.study_setup_panel
        identity = panel.ligand_identity()
        value = panel.ligand_value()
        reference = 'none selected'
        if panel.site_mode.currentData() == 'ligand' and value:
            reference = value
            if identity:
                reference += ' ' + identity['chain_id'] + ':' + identity['residue_number'] + identity.get('insertion_code', '')
            else:
                reference += ' (choose an instance)'
        self.title.setText('Molecule · reference: ' + reference)

    def set_paired(self, paired):
        self._paired = paired
        self.both_button.setVisible(not paired)
        self.three_d_page.setVisible(paired)
        self._arrange(paired)
        if paired:
            self.views.setSizes([500, 500])
        else:
            self._release_viewer()
        self._show_current()

    def _append_entries(self, entries):
        for entry in entries:
            self.choices.addItem(entry['label'], entry)
            index = self.choices.count() - 1
            tooltip = entry['label'] + ('\n' + entry['display_reason'] if entry.get('display_reason') else '')
            self.choices.setItemData(index, tooltip, QtCore.Qt.ItemDataRole.ToolTipRole)

    def _show_current(self, *_args):
        entry = self.choices.currentData()
        if not self._picking:
            self._overview = bool(entry and entry.get('origin') == 'input' and entry.get('kind') == 'whole')
        if entry and entry.get('kind') == 'whole':
            with QtCore.QSignalBlocker(self.receptor_context):
                self.receptor_context.setChecked(True)
        self.update_reference_action()
        self.receptor_context.setEnabled(bool(entry and entry.get('origin') == 'input' and entry.get('kind') == 'component'))
        if not entry:
            self.picture.setText('No molecules are loaded. Add a local molecule file or SMILES to the list.')
            self.three_d_message.setText('No molecule is selected.')
            return
        self.origin.setText(entry['label'])
        try:
            png, basis = drawing_for_entry(entry)
            image = QtGui.QPixmap()
            if not image.loadFromData(png):
                raise ValueError('The chemical drawing could not be displayed.')
            self.picture.setPixmap(image)
            self.origin.setText(basis)
            self.origin.setToolTip(entry['label'] + '\n' + basis)
        except Exception as exc:
            self.picture.setText(str(exc))
        if not self._paired:
            return
        try:
            self._show_3d(entry)
        except Exception as exc:
            self._release_viewer()
            self.three_d_message.setText(str(exc))
            self.three_d_message.show()

    def _show_3d(self, entry):
        if self._viewer is None or not callable(getattr(self._adapter, 'begin_input_preview', None)):
            raise ValueError('3D inspection requires the embedded PyMOL viewer. The 2D view remains available.')
        if self._window._detached_structure_window is not None or self._window._paired_interaction_window is not None:
            raise ValueError('Return the detached structural viewer to the workspace before using 3D inspection.')
        state = getattr(self._window, 'state', None)
        if state and state.active_job:
            raise ValueError('Wait for the active scientific stage to finish before borrowing its 3D viewer.')
        if entry['origin'] == 'input':
            path = verify_input(entry)
            key = ('input', str(path), entry['sha256'])
            block = None
        else:
            key = ('compound', entry.get('record_id'), entry.get('fingerprint'), entry.get('smiles'))
            block = compound_3d_block(entry)
        if key != self._preview_key:
            self._release_viewer()
            self._split_sizes = self._window.pose_split.sizes()
            self._three_d_layout.addWidget(self._viewer, 1)
            self._borrowed = True
            if entry['origin'] == 'input':
                result = self._adapter.begin_input_preview(path)
            else:
                result = self._adapter.begin_compound_preview(block)
            self._preview_object_name = result.get('object_name') if isinstance(result, dict) else None
            self._preview_key = key
            enable_picking = getattr(self._adapter, 'enable_input_preview_picking', None)
            if callable(enable_picking):
                enable_picking()
        if entry['origin'] == 'input':
            self._adapter.focus_input_preview(entry, show_receptor=self.receptor_context.isChecked(),
                                              preserve_view=self._picking,
                                              show_all_components=self._overview,
                                              visible_components=[self.choices.itemData(i) for i in range(self.choices.count())
                                                                  if self.choices.itemData(i).get('origin') == 'input'
                                                                  and self.choices.itemData(i).get('kind') == 'component'])
        self.three_d_message.hide()
        self._viewer.show()

    def _picked_molecule(self, picked):
        """Map a live atom pick to one source instance without committing it."""
        if (not self._paired or not self._borrowed or not self._preview_object_name
                or picked.get('object') != self._preview_object_name
                or not self._preview_key or self._preview_key[0] != 'input'):
            return
        matches = []
        for index in range(self.choices.count()):
            entry = self.choices.itemData(index)
            if (entry.get('origin') == 'input' and entry.get('kind') == 'component'
                    and (entry['path'], entry['sha256']) == self._preview_key[1:]
                    and (entry['resname'], entry['chain'], entry['resi'], entry.get('segment', ''))
                    == (picked.get('name'), picked.get('chain'), picked.get('number'), picked.get('segment', ''))):
                matches.append(index)
        if len(matches) != 1:
            return
        try:
            verify_input(self.choices.itemData(matches[0]))
        except (ValueError, OSError) as exc:
            self._release_viewer()
            self.three_d_message.setText(str(exc))
            self.three_d_message.show()
            return
        self._picking = True
        try:
            self.choices.setCurrentIndex(matches[0])
        finally:
            self._picking = False

    def _release_viewer(self):
        if not self._borrowed:
            return
        self._borrowed = False
        self._preview_key = None
        self._preview_object_name = None
        try:
            self._adapter.end_input_preview()
        finally:
            self._three_d_layout.removeWidget(self._viewer)
            self._window.pose_split.insertWidget(0, self._viewer)
            self._window.pose_split.setSizes(self._split_sizes)
            self._viewer.show()

    def choose_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Add molecules for inspection', '', 'Molecule files (*.sdf *.mol *.SDF *.MOL)',
        )
        if path:
            self.load_file(path)

    def load_file(self, path):
        if self._loading:
            return
        from ..services.ligand_library import inspect_ligand_library
        self._loading = True
        self.open_file.setEnabled(False)
        self.origin.setText('Reading local molecule file…')
        self._read_task.start(lambda: inspect_ligand_library(path))

    def _local_file_loaded(self, library, error):
        self._loading = False
        self.open_file.setEnabled(True)
        if error:
            self.origin.setText('Could not read molecule file: ' + error)
            return
        entries = library_molecules(library)
        for entry in entries:
            entry['label'] = entry['label'].replace('Screening compound — ', 'Local compound — ', 1)
        if not entries:
            self.origin.setText('No readable compounds were found in the local file.')
            return
        self._extras.extend(entries)
        self._entries.extend(entries)
        self._populate_entries(self.entry_key(entries[0]))
        self._show_current()

    def draw_smiles(self):
        text = self.smiles.text().strip()
        entry = {'origin': 'smiles', 'kind': 'compound', 'smiles': text,
                 'label': 'Entered SMILES — ' + text}
        try:
            molecule_for_entry(entry)
        except Exception as exc:
            self.picture.setText(str(exc))
            self.origin.setText('SMILES could not be read; the list was not changed.')
            return
        self._extras.append(entry)
        self._entries.append(entry)
        self._populate_entries(self.entry_key(entry))
        self._show_current()


class InputStructurePreview(QtWidgets.QDialog):
    """Temporarily detach the same inline panel and add the existing 3D viewer."""

    def __init__(self, window, path=None, **_options):
        super().__init__(window)
        self.setWindowTitle('Docking Universal — 2D and 3D molecule view')
        self.setObjectName('paired_input_structure_preview')
        self.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(1150, 800)
        self._window = window
        self.inspector = window.molecule_inspector
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.inspector, 1)
        close = QtWidgets.QPushButton('Return to interface')
        close.clicked.connect(self.close)
        layout.addWidget(close)
        self.finished.connect(self.restore_viewer)

    def show_structure(self, path=None):
        self.show()
        self.inspector.set_paired(True)

    def restore_viewer(self, *_args):
        self.inspector.set_paired(False)
        self.layout().removeWidget(self.inspector)
        self._window.study_setup_panel.molecule_preview_slot.layout().addWidget(self.inspector, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        self.inspector.show()
        self._window._input_preview_dialog = None
