"""Passive, independently testable forms for the three workflow stages."""

from __future__ import annotations

from dataclasses import dataclass

from .qt import QtCore, QtWidgets
from .protocol_help import SETTINGS_HELP, INLINE_HELP, settings_guide_html


def _path_row(field, button_text):
    row = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    button = QtWidgets.QPushButton(button_text)
    layout.addWidget(field)
    layout.addWidget(button)
    return row, button


@dataclass(frozen=True)
class PreparationValues:
    receptor: str
    output_directory: str
    site_mode: str
    ligand_resname: str
    ligand_identity: dict[str, str]
    pocket_engine: str
    pdb_pocket_evidence: str
    pathway: str = "exploratory"
    predict_pockets_with_ligand: bool = False


class StudySetupPanel(QtWidgets.QWidget):
    chooseProtocolRequested = QtCore.pyqtSignal()
    reviewProtocolRequested = QtCore.pyqtSignal()
    chooseInputRequested = QtCore.pyqtSignal()
    fetchInputRequested = QtCore.pyqtSignal()
    detectLigandsRequested = QtCore.pyqtSignal()
    chooseOutputRequested = QtCore.pyqtSignal()
    prepareRequested = QtCore.pyqtSignal()
    cancelRequested = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("study_setup_panel")
        self._locked = False
        form = QtWidgets.QFormLayout(self)
        self._form = form
        self.input_pdb = QtWidgets.QLineEdit()
        self.input_pdb.setPlaceholderText("Local .cif/.mmCIF/.pdb path or RCSB ID, e.g. 2R8N")
        self.output_directory = QtWidgets.QLineEdit()
        self.output_directory.setPlaceholderText("Choose where this study will be saved")
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapAllRows)
        self.pathway = QtWidgets.QComboBox(self)
        self.pathway.addItem("Exploratory — no redocking control", "exploratory")
        self.pathway.addItem("Redock experimental ligand — recommended when available", "control")
        self.pathway.addItem("Use a saved protocol", "reuse")
        self.pathway.setToolTip(
            "Redocking is recommended when a suitable experimental bound ligand is available: "
            "it checks whether the protocol can recover that known pose. "
            "Leave redocking unchecked to save a protocol without this control; it remains explicitly exploratory and unvalidated by pose recovery."
        )
        # Keep the stable serialized pathway for the controller, not a visible
        # menu of combinations. Independent analysis options own the visible UI.
        self.pathway.hide()
        self.study_source = QtWidgets.QComboBox()
        self.study_source.addItem("New study from a structure", "structure")
        self.study_source.addItem("Use a saved protocol", "reuse")
        self.redock_ligand = QtWidgets.QCheckBox("Redock experimental ligand (recommended when available)")
        self.redock_ligand.setObjectName("redock_experimental_ligand")
        self.redock_ligand.setToolTip(self.pathway.toolTip())
        self.redock_note = QtWidgets.QLabel()
        self.redock_note.setWordWrap(True)
        self.protocol_bundle = QtWidgets.QLineEdit()
        self.protocol_bundle.setPlaceholderText("Choose a saved .duprotocol bundle")
        protocol_row, protocol_button = _path_row(self.protocol_bundle, "Browse…")
        self.protocol_note = QtWidgets.QLabel(
            "Reuse the saved receptor, docking regions, program and settings without preparing them again. "
            "Review the verified bundle before importing. Exploratory protocols remain exploratory; "
            "importing is not a new pose-recovery control. Select compounds in Screen ligands next."
        )
        self.protocol_note.setWordWrap(True)
        self.review_protocol_button = QtWidgets.QPushButton("Review imported settings…")
        self.review_protocol_button.clicked.connect(self.reviewProtocolRequested)
        protocol_button.clicked.connect(self.chooseProtocolRequested)
        self.site_mode = QtWidgets.QComboBox()
        self.site_mode.addItem("Predicted pockets", "pockets")
        self.site_mode.addItem("Selected bound ligand", "ligand")
        self.site_guidance_note = QtWidgets.QLabel(
            "This is a starting point, not the final docking location. "
            "After review, choose one or more docking regions here or elsewhere, "
            "including sites supported by other structures."
        )
        self.site_guidance_note.setWordWrap(True)
        self.site_mode.setToolTip(self.site_guidance_note.text())
        self.pocket_engine = QtWidgets.QComboBox()
        self.pocket_engine.addItem("P2Rank — primary", "p2rank")
        self.pocket_engine.addItem("fpocket — fallback", "fpocket")
        self.pocket_engine.addItem("Automatic capability selection", "auto")
        self.predict_with_ligand = QtWidgets.QCheckBox("Also run P2Rank to look for other pockets? (recommended)")
        self.predict_with_ligand.setToolTip(
            "Runs the selected pocket detector (P2Rank by default) on the prepared receptor without the ligand. "
            "The exact bound-ligand site remains available separately, without an invented prediction score. "
            "Recommended for reviewing alternative sites, but not required to use the known ligand site. "
            "Leave unchecked to skip prediction: related-structure ligand locations still provide selectable boxes. "
            "Review and choose one or more regions before docking. Prediction is local; public-PDB lookup is independent."
        )
        self.predict_with_ligand.toggled.connect(self._update_mode)
        self.control_engine = QtWidgets.QComboBox()
        self.control_engine.addItem("AutoDock Vina", "vina")
        self.control_engine.addItem("QuickVina-W", "qvinaw")
        self.control_tier = QtWidgets.QComboBox()
        for label, value in (
            ("Quick diagnostic", "quick"), ("Repeatability", "repeatability"),
            ("Broader search", "broader"), ("More conformers", "conformers"),
            ("Robust sampling", "robust"),
        ):
            self.control_tier.addItem(label, value)
        self.pdb_evidence = QtWidgets.QCheckBox(
            "Search related public PDB structures (recommended; internet required)"
        )
        self.pdb_evidence.setChecked(True)
        self.pdb_evidence.setToolTip(
            "Sends the receptor protein sequence to RCSB PDB; no receptor coordinates, docked pose or screening ligand is shared. "
            "Recommended for finding other experimentally observed ligand sites. "
            "Uncheck for local-only evidence review. This controls evidence lookup only; structure and chemistry downloads are separate."
        )
        self.pdb_evidence_note = QtWidgets.QLabel()
        self.pdb_evidence_note.setWordWrap(True)
        self.pdb_evidence_note.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.pdb_evidence_note.setToolTip(self.pdb_evidence.toolTip())
        self.pdb_evidence.toggled.connect(self._update_evidence_note)
        self._update_evidence_note()
        self.ligand_resname = QtWidgets.QComboBox()
        self.ligand_resname.setEditable(True)
        self.ligand_resname.setPlaceholderText("Detect from the selected structure or enter a residue name")
        self.deposited_evidence = QtWidgets.QLabel(
            "Choose a PDBx/mmCIF structure to review deposited assembly and ligand evidence."
        )
        self.deposited_evidence.setWordWrap(True)
        self.deposited_evidence.setObjectName("deposited_coordinate_evidence")
        self.deposited_evidence.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.deposited_evidence_details = QtWidgets.QPushButton("Full deposited evidence…")
        self.deposited_evidence_details.setEnabled(False)
        self.deposited_evidence_details.hide()
        self._coordinate_evidence_record = None
        input_row, input_button = _path_row(self.input_pdb, "Browse…")
        self.fetch_button = QtWidgets.QPushButton("Fetch RCSB ID")
        self.fetch_button.setObjectName("fetch_rcsb_pdb_button")
        input_row.layout().addWidget(self.fetch_button)
        output_row, output_button = _path_row(self.output_directory, "Browse…")
        ligand_row = QtWidgets.QWidget()
        ligand_layout = QtWidgets.QHBoxLayout(ligand_row)
        ligand_layout.setContentsMargins(0, 0, 0, 0)
        ligand_layout.addWidget(self.ligand_resname)
        self.detect_ligands_button = QtWidgets.QPushButton("Detect from structure")
        self.detect_ligands_button.setObjectName("detect_bound_ligands_button")
        ligand_layout.addWidget(self.detect_ligands_button)
        self.prepare_button = QtWidgets.QPushButton("Prepare receptor and detect pockets")
        self.prepare_button.setObjectName("start_preparation_button")
        self.cancel_button = QtWidgets.QPushButton("Cancel active stage")
        self.cancel_button.setObjectName("cancel_job_button")
        self.cancel_button.hide()
        buttons = QtWidgets.QVBoxLayout()
        buttons.addWidget(self.prepare_button)
        buttons.addWidget(self.cancel_button)
        self.lock_notice = QtWidgets.QLabel(
            "This setup is part of the retained study record. Create a new study to change it."
        )
        self.lock_notice.setWordWrap(True)
        self.lock_notice.setStyleSheet(
            "padding: 7px; background: palette(alternate-base); font-weight: 600;"
        )
        self.lock_notice.hide()
        form.addRow(self.lock_notice)
        form.addRow("Study output directory", output_row)
        form.addRow("Receptor structure", input_row)
        form.addRow("Deposited structure", self.deposited_evidence)
        form.addRow("", self.deposited_evidence_details)
        form.addRow("Study source", self.study_source)
        form.addRow("Pose-recovery check", self.redock_ligand)
        form.addRow(self.redock_note)
        form.addRow("Saved protocol", protocol_row)
        form.addRow(self.protocol_note)
        form.addRow(self.review_protocol_button)
        form.addRow("Starting point for site review", self.site_mode)
        form.addRow(self.site_guidance_note)
        form.addRow("Pocket detector", self.pocket_engine)
        form.addRow("Additional site discovery", self.predict_with_ligand)
        form.addRow("Experimental evidence", self.pdb_evidence)
        form.addRow(self.pdb_evidence_note)
        form.addRow("Bound ligand", ligand_row)
        form.addRow("Control docking engine", self.control_engine)
        form.addRow("Initial control sampling", self.control_tier)
        form.addRow(buttons)
        QtWidgets.QWidget.setTabOrder(self.output_directory, self.input_pdb)
        input_button.clicked.connect(self.chooseInputRequested)
        self.fetch_button.clicked.connect(self.fetchInputRequested)
        self.detect_ligands_button.clicked.connect(self.detectLigandsRequested)
        output_button.clicked.connect(self.chooseOutputRequested)
        self.prepare_button.clicked.connect(self.prepareRequested)
        self.cancel_button.clicked.connect(self.cancelRequested)
        self.site_mode.currentIndexChanged.connect(self._update_mode)
        self.pocket_engine.currentIndexChanged.connect(self._update_mode)
        self.pathway.currentIndexChanged.connect(self._update_mode)
        self.study_source.currentIndexChanged.connect(self._source_changed)
        self.redock_ligand.toggled.connect(self._redocking_changed)
        self.deposited_evidence_details.clicked.connect(self.show_deposited_evidence_details)
        self.output_directory.textChanged.connect(self._update_download_availability)
        self._update_download_availability()
        self._update_mode()

    def _update_download_availability(self):
        ready = bool(self.output_directory.text().strip()) and not self._locked
        self.fetch_button.setEnabled(ready)
        self.fetch_button.setToolTip(
            "Download the structure into this study’s inputs folder."
            if ready else "Choose a study output directory above before downloading."
        )

    def _source_changed(self):
        pathway = "reuse" if self.study_source.currentData() == "reuse" else (
            "control" if self.redock_ligand.isChecked() else "exploratory"
        )
        self.pathway.setCurrentIndex(self.pathway.findData(pathway))

    def _redocking_changed(self):
        if self.study_source.currentData() != "reuse":
            pathway = "control" if self.redock_ligand.isChecked() else "exploratory"
            self.pathway.setCurrentIndex(self.pathway.findData(pathway))

    def _update_evidence_note(self):
        self.pdb_evidence_note.setText(
            "Online evidence lookup sends the receptor’s protein sequence to RCSB PDB. Uncheck for local-only evidence."
            if self.pdb_evidence.isChecked() else
            "Local-only evidence: PDB databank search is off. Local structure information remains available; public evidence may be missing."
        )

    def set_coordinate_evidence(self, record) -> None:
        from ..services.coordinate_evidence import evidence_lines

        self._coordinate_evidence_record = record
        self.deposited_evidence_details.setEnabled(bool(record))
        self.deposited_evidence_details.setVisible(bool(record))
        if record:
            self.deposited_evidence.setText("\n".join(evidence_lines(record)))
        else:
            self.deposited_evidence.setText(
                "Load or download a structure above to review its assembly and deposited components."
            )

    def show_deposited_evidence_details(self) -> None:
        if not self._coordinate_evidence_record:
            return
        from ..services.coordinate_evidence import evidence_lines

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Deposited structure evidence")
        dialog.resize(720, 520)
        layout = QtWidgets.QVBoxLayout(dialog)
        explanation = QtWidgets.QLabel(
            "These observations come from the deposited coordinate file. Review them "
            "alongside the structure before choosing a docking region."
        )
        explanation.setWordWrap(True)
        details = QtWidgets.QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText("\n\n".join(evidence_lines(self._coordinate_evidence_record, detailed=True)))
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(explanation)
        layout.addWidget(details, 1)
        layout.addWidget(close)
        dialog.exec()

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.lock_notice.setVisible(locked)
        for widget in (
            self.input_pdb, self.output_directory, self.site_mode,
            self.pathway, self.study_source, self.redock_ligand,
            self.pocket_engine, self.predict_with_ligand, self.pdb_evidence, self.ligand_resname,
            self.control_engine, self.control_tier,
            self.protocol_bundle,
            self.detect_ligands_button, self.fetch_button, self.prepare_button,
        ):
            widget.setEnabled(not locked)
        # Browse buttons live in row containers; disabling the complete panel
        # would also hide retained values from keyboard selection/copying.
        for button in self.findChildren(QtWidgets.QPushButton):
            if button is not self.cancel_button:
                button.setEnabled(not locked)
        self.deposited_evidence_details.setEnabled(bool(self._coordinate_evidence_record))
        self.review_protocol_button.setEnabled(locked)
        self._update_mode()
        self._update_download_availability()

    def _update_mode(self):
        reuse = self.pathway.currentData() == "reuse"
        control = self.pathway.currentData() == "control"
        # Restoring a locked/older study must synchronize the checkboxes without
        # emitting a fresh scientific request or changing its retained choices.
        with QtCore.QSignalBlocker(self.study_source):
            self.study_source.setCurrentIndex(self.study_source.findData("reuse" if reuse else "structure"))
        if not reuse:
            with QtCore.QSignalBlocker(self.redock_ligand):
                self.redock_ligand.setChecked(control)
        if control:
            with QtCore.QSignalBlocker(self.site_mode):
                self.site_mode.setCurrentIndex(self.site_mode.findData("ligand"))
        self._form.setRowVisible(self.redock_ligand, not reuse)
        self._form.setRowVisible(self.redock_note, not reuse)
        self.redock_ligand.setEnabled(not reuse and not self._locked)
        self.redock_note.setText(
            "Tests recovery of the selected experimental ligand after site review. "
            "Evidence lookup and additional-pocket prediction are separate choices."
            if control else
            "Without redocking, the saved protocol is exploratory — not validated by experimental-pose recovery."
        )
        ligand_site = not reuse and (control or self.site_mode.currentData() == "ligand")
        detector = {"p2rank": "P2Rank", "fpocket": "fpocket",
                    "auto": "pocket prediction (P2Rank preferred)"}.get(self.pocket_engine.currentData(), "P2Rank")
        guidance = "optional fallback" if self.pocket_engine.currentData() == "fpocket" else "recommended"
        self.predict_with_ligand.setText(f"Also run {detector} to look for other pockets? ({guidance})")
        self._form.setRowVisible(self.protocol_bundle.parentWidget(), reuse)
        self._form.setRowVisible(self.protocol_note, reuse)
        self._form.setRowVisible(self.review_protocol_button, reuse and self._locked)
        for widget in (self.output_directory.parentWidget(), self.input_pdb.parentWidget(),
                       self.deposited_evidence):
            self._form.setRowVisible(widget, not reuse)
        self._form.setRowVisible(self.deposited_evidence_details, not reuse and bool(self._coordinate_evidence_record))
        self._form.setRowVisible(self.site_mode, not control and not reuse)
        self._form.setRowVisible(self.site_guidance_note, not reuse)
        self._form.setRowVisible(self.predict_with_ligand, ligand_site)
        prediction = not ligand_site or self.predict_with_ligand.isChecked()
        self._form.setRowVisible(self.pocket_engine, not reuse and prediction)
        for widget in (self.pdb_evidence, self.pdb_evidence_note):
            self._form.setRowVisible(widget, not reuse)
        for widget in (self.control_engine, self.control_tier):
            self._form.setRowVisible(widget, control)
        self._form.setRowVisible(self.ligand_resname.parentWidget(), ligand_site)
        self.site_mode.setEnabled(not control and not self._locked)
        self.pocket_engine.setEnabled(not reuse and prediction and not self._locked)
        self.predict_with_ligand.setEnabled(ligand_site and not self._locked)
        self.pdb_evidence.setEnabled(not reuse and not self._locked)
        self.control_engine.setEnabled(control and not self._locked)
        self.control_tier.setEnabled(control and not self._locked)
        self.ligand_resname.setEnabled(ligand_site and not self._locked)
        self.detect_ligands_button.setEnabled(ligand_site and not self._locked)
        self.prepare_button.setText(
            "Review and import protocol" if reuse else
            "Prepare and review sites before control" if control else "Prepare receptor and detect pockets"
        )

    def ligand_value(self):
        data = self.ligand_resname.currentData()
        if isinstance(data, dict):
            return str(data.get("resname", "")).strip().upper()
        return str(data).strip() if data else self.ligand_resname.currentText().strip().upper()

    def ligand_identity(self):
        data = self.ligand_resname.currentData()
        return dict(data) if isinstance(data, dict) else {}

    def values(self):
        return PreparationValues(
            self.input_pdb.text().strip(), self.output_directory.text().strip(),
            self.site_mode.currentData(), self.ligand_value(),
            self.ligand_identity(),
            self.pocket_engine.currentData(),
            "related-structures" if self.pdb_evidence.isChecked() else "off",
            self.pathway.currentData(),
            self.predict_with_ligand.isChecked() and (self.pathway.currentData() == "control" or self.site_mode.currentData() == "ligand"),
        )


class ProtocolImportDialog(QtWidgets.QDialog):
    """Read-only settings review; accepting imports, never starts screening."""

    def __init__(self, preview, parent=None, *, read_only=False):
        super().__init__(parent)
        from ..reporting import protocol_summary_rows
        from ..services.protein_identity import target_identity_text
        from docking_universal_bundle import protocol_type_label
        self.setObjectName("protocol_import_review")
        self.setWindowTitle("Review saved protocol")
        self.resize(720, 560)
        layout = QtWidgets.QVBoxLayout(self)
        identity = preview.get('target_identity') or {}
        target, species = target_identity_text(identity, str(preview['target']))
        title = QtWidgets.QLabel(target)
        title.setWordWrap(True)
        layout.addWidget(title)
        if identity.get('proteins'):
            organism = QtWidgets.QLabel("Source species: " + species)
            organism.setWordWrap(True)
            layout.addWidget(organism)
        authority = QtWidgets.QLabel(protocol_type_label(preview['protocol_type']) +
            f" · {preview['region_count']} locked docking region(s)")
        layout.addWidget(authority)
        note = QtWidgets.QLabel(
            "Import keeps the saved receptor, regions, docking program and settings unchanged. "
            "It does not prepare the receptor or start docking. " +
            ("This is exploratory: it has not passed a bound-ligand pose-recovery control. "
             "Screening will require your explicit exploratory-use approval."
             if preview['exploratory_authorization_required'] else
             "The bundle records a passed pose-recovery control; import does not repeat or extend that test.")
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        rows = protocol_summary_rows(preview['engine'], {}, preview['parameters'])
        table = QtWidgets.QTableWidget(len(rows) - 1, 2)
        table.setHorizontalHeaderLabels(rows[0])
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        for row, values in enumerate(rows[1:]):
            for column, value in enumerate(values):
                table.setItem(row, column, QtWidgets.QTableWidgetItem(str(value)))
        layout.addWidget(table, 1)
        verification = QtWidgets.QLabel(
            f"Verified {preview['verified_files']} retained files. A study-owned copy is saved on import. "
            "Integrity checks detect changed files; they do not establish scientific correctness."
        )
        verification.setWordWrap(True)
        layout.addWidget(verification)
        if preview.get('receptor_modification_warning'):
            warning = QtWidgets.QLabel(str(preview['receptor_modification_warning']))
            warning.setWordWrap(True)
            layout.addWidget(warning)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close if read_only else
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        if not read_only:
            buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Import saved protocol")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class PreparationProgressPanel(QtWidgets.QWidget):
    """Readable live/retained account of receptor preparation and site detection."""

    cancelRequested = QtCore.pyqtSignal()
    logsRequested = QtCore.pyqtSignal()
    artifactsRequested = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("preparation_progress_panel")
        layout = QtWidgets.QVBoxLayout(self)
        self.heading = QtWidgets.QLabel("Prepare receptor and detect candidate sites")
        self.heading.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.status = QtWidgets.QLabel("Preparation has not started.")
        self.status.setWordWrap(True)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Not started")
        self.operations = QtWidgets.QLabel(
            "This stage validates the selected structure, prepares the receptor, runs the "
            "selected pocket detector, constructs docking boxes, and gathers related-structure "
            "evidence before pausing for scientific review."
        )
        self.operations.setWordWrap(True)
        self.summary = QtWidgets.QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setPlaceholderText("Retained preparation outputs will appear here.")
        buttons = QtWidgets.QHBoxLayout()
        self.cancel_button = QtWidgets.QPushButton("Cancel preparation")
        self.logs_button = QtWidgets.QPushButton("Show complete logs")
        self.artifacts_button = QtWidgets.QPushButton("Show study files")
        self.artifacts_button.setToolTip("Show saved reports, structures, logs and protocol files for this study")
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        buttons.addWidget(self.logs_button)
        buttons.addWidget(self.artifacts_button)
        layout.addWidget(self.heading)
        layout.addWidget(self.status)
        layout.addWidget(self.progress)
        layout.addWidget(self.operations)
        layout.addWidget(self.summary, 1)
        layout.addLayout(buttons)
        self.cancel_button.clicked.connect(self.cancelRequested)
        self.logs_button.clicked.connect(self.logsRequested)
        self.artifacts_button.clicked.connect(self.artifactsRequested)


class ProtocolFinalizationPanel(QtWidgets.QWidget):
    chooseOutputRequested = QtCore.pyqtSignal()
    finalizeRequested = QtCore.pyqtSignal()
    openReportRequested = QtCore.pyqtSignal()
    openBundleRequested = QtCore.pyqtSignal()
    approvalChanged = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("protocol_finalization_panel")
        form = QtWidgets.QFormLayout(self)
        self._settings_guide = None
        self._control_mode = False
        self.introduction = QtWidgets.QLabel('Save a reusable recipe for later screening. This step packages your approved receptor, regions and settings; it does not dock ligands now.')
        self.introduction.setWordWrap(True)
        self.guide_button = QtWidgets.QPushButton('Settings guide…')
        self.guide_button.setObjectName('protocol_settings_guide')
        self.guide_button.clicked.connect(lambda: self.show_settings_guide())
        introduction_row = QtWidgets.QHBoxLayout()
        introduction_row.addWidget(self.introduction, 1)
        introduction_row.addWidget(self.guide_button, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        form.addRow(introduction_row)
        self.output_directory = QtWidgets.QLineEdit()
        output_row, output_button = _path_row(self.output_directory, "Browse…")
        self.engine = QtWidgets.QComboBox(); self.engine.addItem("AutoDock Vina", "vina"); self.engine.addItem("QuickVina-W", "qvinaw")
        from ..ad4_gpu import available, ENGINE_LABEL
        if available():self.engine.addItem(ENGINE_LABEL,'adgpu')
        self.ph = QtWidgets.QDoubleSpinBox(); self.ph.setRange(.1, 14); self.ph.setValue(7.4); self.ph.setDecimals(2)
        self.conformers = QtWidgets.QSpinBox(); self.conformers.setRange(1, 100); self.conformers.setValue(3)
        self.seeds = QtWidgets.QSpinBox(); self.seeds.setRange(1, 100); self.seeds.setValue(5)
        self.base_seed = QtWidgets.QSpinBox(); self.base_seed.setRange(0, 2_147_483_647); self.base_seed.setValue(20260808)
        self.exhaustiveness = QtWidgets.QSpinBox(); self.exhaustiveness.setRange(1, 4096); self.exhaustiveness.setValue(16)
        self.modes = QtWidgets.QSpinBox(); self.modes.setRange(1, 100); self.modes.setValue(15)
        self.energy_range = QtWidgets.QDoubleSpinBox(); self.energy_range.setRange(.1, 100); self.energy_range.setValue(8)
        self.ad4_runs = QtWidgets.QSpinBox(); self.ad4_runs.setRange(1,100); self.ad4_runs.setValue(20)
        self.ad4_heuristic_cap = QtWidgets.QSpinBox(); self.ad4_heuristic_cap.setRange(1000,100_000_000); self.ad4_heuristic_cap.setValue(12_000_000)
        self.approval = QtWidgets.QCheckBox("Approve exploratory use (no pose-recovery control)")
        self.approval.setObjectName("exploratory_protocol_approval")
        self.finalize_button = QtWidgets.QPushButton("Generate final report and .duprotocol"); self.finalize_button.setObjectName("start_protocol_finalization_button")
        self.open_report_button = QtWidgets.QPushButton("Open final report")
        self.open_bundle_button = QtWidgets.QPushButton("Open bundle location")
        actions = QtWidgets.QHBoxLayout(); actions.addWidget(self.open_report_button); actions.addWidget(self.open_bundle_button)
        self.status = QtWidgets.QLabel("Approve docking regions before finalizing the reusable protocol."); self.status.setWordWrap(True)
        self.help_buttons = {}
        self.inline_explanations = {}
        self._field_rows = {}
        settings_grid = QtWidgets.QGridLayout()
        settings_grid.setColumnStretch(2, 1)
        settings_grid.setHorizontalSpacing(20)
        form.addRow(settings_grid)
        for key, widget in (('output_directory', output_row), ('engine', self.engine), ('ph', self.ph),
                            ('conformers', self.conformers), ('seeds', self.seeds), ('base_seed', self.base_seed),
                            ('exhaustiveness', self.exhaustiveness), ('modes', self.modes), ('energy_range', self.energy_range),
                            ('ad4_runs',self.ad4_runs),('ad4_heuristic_cap',self.ad4_heuristic_cap)):
            title, short, detail = SETTINGS_HELP[key]
            label_row = QtWidgets.QWidget()
            label_layout = QtWidgets.QHBoxLayout(label_row)
            label_layout.setContentsMargins(0, 0, 0, 0)
            label = QtWidgets.QLabel(title)
            label.setWordWrap(True)
            label.setBuddy(getattr(self, key))
            help_button = self._help_button(key)
            label_layout.addWidget(label)
            label_layout.addWidget(help_button)
            label_row.setMaximumWidth(250)
            widget.setMaximumWidth(300 if key == 'output_directory' else 190 if key == 'engine' else 140)
            explanation = QtWidgets.QLabel(short + ' ' + INLINE_HELP[key])
            explanation.setObjectName('protocol_explain_' + key)
            explanation.setWordWrap(True)
            explanation.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse |
                                               QtCore.Qt.TextInteractionFlag.TextSelectableByKeyboard)
            row = len(self.inline_explanations)
            settings_grid.addWidget(label_row, row, 0, QtCore.Qt.AlignmentFlag.AlignTop)
            settings_grid.addWidget(widget, row, 1, QtCore.Qt.AlignmentFlag.AlignTop)
            settings_grid.addWidget(explanation, row, 2)
            self.inline_explanations[key] = explanation
            self._field_rows[key]=(label_row,widget,explanation)
            field = getattr(self, key)
            field.setToolTip(short)
            field.setAccessibleDescription(short + ' ' + detail)
            field.setWhatsThis(short + '\n\n' + detail)
        self.workload_hint = QtWidgets.QLabel()
        self.workload_hint.setWordWrap(True)
        form.addRow(self.workload_hint)
        for field in (self.conformers, self.seeds, self.modes,self.ad4_runs):
            field.valueChanged.connect(self._update_workload_hint)
        self._update_workload_hint()
        approval_help = QtWidgets.QHBoxLayout()
        approval_help.addWidget(self.approval)
        approval_help.addWidget(self._help_button('approval'))
        approval_explanation = QtWidgets.QLabel(INLINE_HELP['approval'])
        approval_explanation.setObjectName('protocol_explain_approval')
        approval_explanation.setWordWrap(True)
        approval_help.addWidget(approval_explanation, 1)
        self.inline_explanations['approval'] = approval_explanation
        self.approval.setToolTip(SETTINGS_HELP['approval'][1])
        self.approval.setAccessibleDescription(SETTINGS_HELP['approval'][2])
        form.addRow(approval_help); form.addRow(self.finalize_button); form.addRow(actions); form.addRow(self.status)
        output_button.clicked.connect(self.chooseOutputRequested); self.finalize_button.clicked.connect(self.finalizeRequested); self.open_report_button.clicked.connect(self.openReportRequested); self.open_bundle_button.clicked.connect(self.openBundleRequested); self.approval.toggled.connect(self.approvalChanged)
        self.engine.currentIndexChanged.connect(self._update_engine_fields)
        self._update_engine_fields()

    def _update_engine_fields(self):
        is_ad4=self.engine.currentData()=='adgpu'
        self.inline_explanations['engine'].setText(
            'Experimental AD4 on the GPU—not GPU Vina. Different search and estimated binding-energy formula; do not compare its energy values directly with Vina. Use ? for the offline learning guide. This release accepts only the tested Apple-Silicon build.'
            if is_ad4 else INLINE_HELP['engine'])
        for key,widgets in self._field_rows.items():
            if key.startswith('ad4_') or key in ('exhaustiveness','modes','energy_range'):
                visible=is_ad4 if key.startswith('ad4_') else not is_ad4
                for widget in widgets:widget.setVisible(visible)
        if self._control_mode:
            for widgets in self._field_rows.values():
                for widget in widgets: widget.hide()
        self._update_workload_hint()

    def set_control_mode(self, active, description=""):
        """Show the explicit control launch in stage four, after site approval."""
        self._control_mode = bool(active)
        for widgets in self._field_rows.values():
            for widget in widgets: widget.setVisible(not active)
        for widget in (self.approval, self.help_buttons['approval'],
                       self.inline_explanations['approval'], self.guide_button, self.workload_hint):
            widget.setVisible(not active)
        self.introduction.setText(description if active else
            'Save a reusable recipe for later screening. This step packages your approved receptor, regions and settings; it does not dock ligands now.')
        self.finalize_button.setText("Run reviewed known-ligand control" if active else "Generate final report and .duprotocol")
        if not active:
            self._update_engine_fields()

    def _help_button(self, key):
        button = QtWidgets.QToolButton()
        button.setText('?')
        button.setAccessibleName('Explain ' + SETTINGS_HELP[key][0])
        button.setToolTip('Explain ' + SETTINGS_HELP[key][0])
        button.setFixedSize(22, 22)
        button.clicked.connect(lambda: self.show_settings_guide(key))
        self.help_buttons[key] = button
        return button

    def _update_workload_hint(self):
        if self.engine.currentData()=='adgpu':
            self.workload_hint.setText(
                f'Per chemical state and approved site: up to {self.conformers.value()*self.seeds.value()} GPU repeats '
                f'({self.conformers.value()} starting shapes × {self.seeds.value()} seeds), each retaining {self.ad4_runs.value()} genetic-search winners. '
                'Experimental AD4 uses a dry rigid receptor. Macrocycles/metals are rejected; actual grid extents may expand by a fraction of one 0.375 Å cell and are locked and reported separately.')
            return
        self.workload_hint.setText(
            f'Per chemical state and approved site: up to {self.conformers.value() * self.seeds.value()} docking runs '
            f'({self.conformers.value()} starting shapes × {self.seeds.value()} repeats), each saving at most '
            f'{self.modes.value()} poses. Actual totals depend on generated states/shapes and the ligand library.')

    def show_settings_guide(self, key=''):
        if self._settings_guide is None:
            self._settings_guide = QtWidgets.QDialog(self, QtCore.Qt.WindowType.Window)
            self._settings_guide.setWindowTitle('Protocol settings guide')
            self._settings_guide.resize(660, 620)
            layout = QtWidgets.QVBoxLayout(self._settings_guide)
            self._guide_text = QtWidgets.QTextBrowser()
            self._guide_text.setOpenExternalLinks(True)
            layout.addWidget(self._guide_text)
            close = QtWidgets.QPushButton('Close')
            close.clicked.connect(self._settings_guide.close)
            layout.addWidget(close)
        values = {name: getattr(self, name).value() for name in
                  ('ph', 'conformers', 'seeds', 'base_seed', 'exhaustiveness', 'modes', 'energy_range','ad4_runs','ad4_heuristic_cap')}
        values.update(output_directory=self.output_directory.text() or 'Not chosen',
                      engine=self.engine.currentText(),engine_key=self.engine.currentData(), approval='Approved' if self.approval.isChecked() else 'Not approved')
        self._guide_text.setHtml(settings_guide_html(values))
        self._settings_guide.show()
        if key:
            self._guide_text.scrollToAnchor(key)
        self._settings_guide.raise_()


class ScreeningSetupPanel(QtWidgets.QWidget):
    chooseFileRequested = QtCore.pyqtSignal(); chooseDirectoryRequested = QtCore.pyqtSignal(); chooseOutputRequested = QtCore.pyqtSignal()
    previewRequested = QtCore.pyqtSignal(); runRequested = QtCore.pyqtSignal(); inputsChanged = QtCore.pyqtSignal(); approvalChanged = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("screening_setup_panel")
        form = QtWidgets.QFormLayout(self)
        self.ligands = QtWidgets.QLineEdit(); ligand_row = QtWidgets.QWidget(); ll = QtWidgets.QHBoxLayout(ligand_row); ll.setContentsMargins(0,0,0,0); ll.addWidget(self.ligands)
        file_button = QtWidgets.QPushButton("File…"); directory_button = QtWidgets.QPushButton("Folder…"); ll.addWidget(file_button); ll.addWidget(directory_button)
        file_button.setToolTip("Choose SDF/MOL or a CSV, TSV or XLSX SMILES table. Review and approve table columns before selecting compounds.")
        self.ligands.setPlaceholderText("SDF/MOL, CSV/TSV/XLSX SMILES table, or SDF/MOL folder")
        self.output = QtWidgets.QLineEdit(); output_row, output_button = _path_row(self.output, "Browse…")
        self.analysis = QtWidgets.QComboBox(); self.analysis.addItem("Representative poses + interactions", "representatives"); self.analysis.addItem("Cluster summary only", "summary"); self.analysis.addItem("Docking outputs only", "none")
        self.representatives = QtWidgets.QSpinBox(); self.representatives.setRange(1,100); self.representatives.setValue(3)
        self.cluster_rmsd = QtWidgets.QDoubleSpinBox(); self.cluster_rmsd.setRange(.1,20); self.cluster_rmsd.setValue(1.5); self.cluster_rmsd.setSuffix(" Å")
        self.cpu = QtWidgets.QComboBox()
        self.cpu.setObjectName('screening_cpu_mode')
        self.cpu.addItem('Application default (recommended)', 'default')
        self.cpu.addItem('Automatic — engine decides', 'automatic')
        self.cpu.addItem('Custom thread count', 'custom')
        self.cpu_count = QtWidgets.QSpinBox()
        self.cpu_count.setObjectName('screening_cpu_count')
        self.cpu_count.setRange(1, 1024)
        self.cpu_count.setValue(8)
        self.cpu_count.setSuffix(' threads')
        self.cpu_count.setToolTip('Threads per docking search, not simultaneous compounds. Counts above eight are allowed but may not be faster.')
        self.cpu_count.hide()
        self._engine = 'vina'
        cpu_row = QtWidgets.QWidget()
        cpu_layout = QtWidgets.QVBoxLayout(cpu_row)
        cpu_layout.setContentsMargins(0, 0, 0, 0)
        cpu_layout.addWidget(self.cpu)
        cpu_layout.addWidget(self.cpu_count)
        self.stop_on_error = QtWidgets.QCheckBox("Stop the library after the first failed compound")
        self.approval = QtWidgets.QCheckBox("I authorize screening with this exploratory protocol without pose-recovery control"); self.approval.setObjectName("exploratory_screening_approval")
        self.preview_button = QtWidgets.QPushButton("Preview workload (chemistry validated at launch)")
        self.run_button = QtWidgets.QPushButton("Run locked-protocol screening"); self.run_button.setObjectName("start_locked_screening_button")
        self.status = QtWidgets.QLabel("Finalize a reusable protocol, then select ligands and preview the workload."); self.status.setWordWrap(True)
        self.elapsed = QtWidgets.QLabel()
        self.elapsed.setObjectName('screening_elapsed_summary')
        self.elapsed.setWordWrap(True)
        self.elapsed.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse |
                                             QtCore.Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.elapsed.hide()
        form.addRow(self.elapsed)
        form.addRow("Compound library", ligand_row)
        from .ligand_library_panel import LigandLibraryPanel
        self.library_panel = LigandLibraryPanel()
        form.addRow(self.library_panel)
        # A grid gives wrapping help its own height without making spin boxes
        # expand across the workspace or disturbing the molecule preview.
        settings_grid = QtWidgets.QGridLayout()
        settings_grid.setColumnStretch(2, 1)
        settings_grid.setHorizontalSpacing(20)
        self.inline_explanations = {}
        for row, (key, title, widget, explanation) in enumerate((
                ('output', 'Screening output', output_row,
                 'Folder for this screening run and its results; the locked protocol is not overwritten.'),
                ('analysis', 'Analysis', self.analysis,
                 'Choose detailed representative views, cluster tables only, or docking outputs only. This does not change the docking search.'),
                ('cpu', 'Docking CPU threads', cpu_row,
                 'Default: Vina uses up to 8 threads on Apple Silicon, unless an environment or saved box setting overrides it; other systems/programs keep engine automatic. Automatic lets the engine choose (0). Custom sets a count for this screen only and overrides those settings. More threads can be slower; 8 was a good balance in our Mac tests, not a universal optimum. This does not change search effort or run compounds simultaneously.'),
                ('representatives', 'Representative clusters', self.representatives,
                 'How many lowest-energy pose groups per compound receive detailed output. Each representative is its group’s lowest-energy pose; this is not a compound or total-pose limit.'),
                ('cluster_rmsd', 'Clustering cutoff', self.cluster_rmsd,
                 'Group similar poses using symmetry-aware heavy-atom RMSD in the protein’s coordinate frame, without realignment. Smaller values separate more groups; larger values merge more. This is not RMSD to an experimental pose.'),
        )):
            label = QtWidgets.QLabel(title)
            label.setBuddy(getattr(self, key))
            label.setWordWrap(True)
            widget.setMaximumWidth(330 if key in ('output', 'analysis', 'cpu') else 140)
            note = QtWidgets.QLabel(explanation)
            note.setObjectName('screening_explain_' + key)
            note.setWordWrap(True)
            note.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse |
                                         QtCore.Qt.TextInteractionFlag.TextSelectableByKeyboard)
            settings_grid.addWidget(label, row, 0, QtCore.Qt.AlignmentFlag.AlignTop)
            settings_grid.addWidget(widget, row, 1, QtCore.Qt.AlignmentFlag.AlignTop)
            settings_grid.addWidget(note, row, 2)
            self.inline_explanations[key] = note
            field = getattr(self, key)
            field.setToolTip(explanation)
            field.setAccessibleDescription(explanation)
        form.addRow(settings_grid)
        for key, widget, explanation in (
                ('stop_on_error', self.stop_on_error,
                 'Unchecked: continue other compounds and keep successful results; failures are still reported.'),
                ('approval', self.approval,
                 'Exploratory means this protocol has no experimental pose-recovery control. Authorization is not validation of hits or binding affinity.')):
            form.addRow(widget)
            note = QtWidgets.QLabel(explanation)
            note.setObjectName('screening_explain_' + key)
            note.setWordWrap(True)
            form.addRow(note)
            self.inline_explanations[key] = note
            widget.setToolTip(explanation)
            widget.setAccessibleDescription(explanation)
        for widget in (self.preview_button, self.run_button, self.status): form.addRow(widget)
        file_button.clicked.connect(self.chooseFileRequested); directory_button.clicked.connect(self.chooseDirectoryRequested); output_button.clicked.connect(self.chooseOutputRequested); self.preview_button.clicked.connect(self.previewRequested); self.run_button.clicked.connect(self.runRequested); self.approval.toggled.connect(self.approvalChanged)
        self.ligands.textChanged.connect(self.inputsChanged); self.output.textChanged.connect(self.inputsChanged); self.analysis.currentIndexChanged.connect(self.inputsChanged); self.representatives.valueChanged.connect(self.inputsChanged); self.cluster_rmsd.valueChanged.connect(self.inputsChanged)
        self.cpu.currentIndexChanged.connect(self._cpu_mode_changed)
        self.cpu_count.valueChanged.connect(self.inputsChanged)

    def _cpu_mode_changed(self, *_args):
        self.cpu_count.setVisible(self._engine != 'adgpu' and self.cpu.currentData() == 'custom')
        self.inputsChanged.emit()

    def set_engine(self, engine):
        """Do not imply CPU thread controls tune an OpenCL GPU search."""
        self._engine = engine
        ad4 = engine == 'adgpu'
        self.cpu.setEnabled(not ad4)
        self.cpu_count.setVisible(not ad4 and self.cpu.currentData() == 'custom')
        self.inline_explanations['cpu'].setText(
            'Not used by AutoDock-GPU. The experimental AD4 profile uses the Apple GPU; CPU thread selections are not applied. Compounds still run sequentially.'
            if ad4 else self.cpu.toolTip())

    def cpu_override(self):
        """None inherits policy; zero is explicitly engine automatic."""
        if self._engine == 'adgpu':
            return None
        mode = self.cpu.currentData()
        return self.cpu_count.value() if mode == 'custom' else 0 if mode == 'automatic' else None
