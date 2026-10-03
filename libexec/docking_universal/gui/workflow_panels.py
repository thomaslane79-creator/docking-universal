"""Passive, independently testable forms for the three workflow stages."""

from __future__ import annotations

from dataclasses import dataclass

from .qt import QtCore, QtWidgets


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


class StudySetupPanel(QtWidgets.QWidget):
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
        self.pathway = QtWidgets.QComboBox()
        self.pathway.addItem("Exploratory — no redocking control", "exploratory")
        self.pathway.addItem("Known-ligand pose-recovery control", "control")
        self.site_mode = QtWidgets.QComboBox()
        self.site_mode.addItem("Predicted pockets", "pockets")
        self.site_mode.addItem("Selected bound ligand", "ligand")
        self.pocket_engine = QtWidgets.QComboBox()
        self.pocket_engine.addItem("P2Rank — primary", "p2rank")
        self.pocket_engine.addItem("fpocket — fallback", "fpocket")
        self.pocket_engine.addItem("Automatic capability selection", "auto")
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
            "Search related public PDB structures"
        )
        self.pdb_evidence.setChecked(True)
        self.pdb_evidence.setToolTip(
            "Uses the receptor protein sequence to query RCSB PDB; no docked pose or screening ligand is shared."
        )
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
        form.addRow("Scientific pathway", self.pathway)
        form.addRow("Site definition", self.site_mode)
        form.addRow("Pocket detector", self.pocket_engine)
        form.addRow("Experimental evidence", self.pdb_evidence)
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
        self.pathway.currentIndexChanged.connect(self._update_mode)
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
            self.pathway, self.pocket_engine, self.pdb_evidence, self.ligand_resname,
            self.control_engine, self.control_tier,
            self.detect_ligands_button, self.fetch_button, self.prepare_button,
        ):
            widget.setEnabled(not locked)
        # Browse buttons live in row containers; disabling the complete panel
        # would also hide retained values from keyboard selection/copying.
        for button in self.findChildren(QtWidgets.QPushButton):
            if button is not self.cancel_button:
                button.setEnabled(not locked)
        self.deposited_evidence_details.setEnabled(bool(self._coordinate_evidence_record))
        self._update_download_availability()

    def _update_mode(self):
        control = self.pathway.currentData() == "control"
        ligand_site = control or self.site_mode.currentData() == "ligand"
        for widget in (self.site_mode, self.pocket_engine, self.pdb_evidence):
            self._form.setRowVisible(widget, not control)
        for widget in (self.control_engine, self.control_tier):
            self._form.setRowVisible(widget, control)
        self._form.setRowVisible(self.ligand_resname.parentWidget(), ligand_site)
        self.site_mode.setEnabled(not control and not self._locked)
        self.pocket_engine.setEnabled(not control and not self._locked)
        self.pdb_evidence.setEnabled(not control and not self._locked)
        self.control_engine.setEnabled(control and not self._locked)
        self.control_tier.setEnabled(control and not self._locked)
        self.ligand_resname.setEnabled(ligand_site and not self._locked)
        self.detect_ligands_button.setEnabled(ligand_site and not self._locked)
        self.prepare_button.setText(
            "Run known-ligand control" if control else "Prepare receptor and detect pockets"
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
        )


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
        self.artifacts_button = QtWidgets.QPushButton("Show retained artifacts")
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
        self.output_directory = QtWidgets.QLineEdit()
        output_row, output_button = _path_row(self.output_directory, "Browse…")
        self.engine = QtWidgets.QComboBox(); self.engine.addItem("AutoDock Vina", "vina"); self.engine.addItem("QuickVina-W", "qvinaw")
        self.ph = QtWidgets.QDoubleSpinBox(); self.ph.setRange(.1, 14); self.ph.setValue(7.4); self.ph.setDecimals(2)
        self.conformers = QtWidgets.QSpinBox(); self.conformers.setRange(1, 100); self.conformers.setValue(3)
        self.seeds = QtWidgets.QSpinBox(); self.seeds.setRange(1, 100); self.seeds.setValue(5)
        self.base_seed = QtWidgets.QSpinBox(); self.base_seed.setRange(0, 2_147_483_647); self.base_seed.setValue(20260808)
        self.exhaustiveness = QtWidgets.QSpinBox(); self.exhaustiveness.setRange(1, 4096); self.exhaustiveness.setValue(16)
        self.modes = QtWidgets.QSpinBox(); self.modes.setRange(1, 100); self.modes.setValue(15)
        self.energy_range = QtWidgets.QDoubleSpinBox(); self.energy_range.setRange(.1, 100); self.energy_range.setValue(8)
        self.approval = QtWidgets.QCheckBox("I approve creation of a reusable exploratory protocol without bound-ligand control")
        self.approval.setObjectName("exploratory_protocol_approval")
        self.finalize_button = QtWidgets.QPushButton("Generate final report and .duprotocol"); self.finalize_button.setObjectName("start_protocol_finalization_button")
        self.open_report_button = QtWidgets.QPushButton("Open final report")
        self.open_bundle_button = QtWidgets.QPushButton("Open bundle location")
        actions = QtWidgets.QHBoxLayout(); actions.addWidget(self.open_report_button); actions.addWidget(self.open_bundle_button)
        self.status = QtWidgets.QLabel("Approve docking regions before finalizing the reusable protocol."); self.status.setWordWrap(True)
        for label, widget in (("Final output directory", output_row), ("Docking engine", self.engine), ("Ligand pH", self.ph), ("Conformers per state", self.conformers), ("Independent seeds", self.seeds), ("Base seed", self.base_seed), ("Exhaustiveness", self.exhaustiveness), ("Maximum poses", self.modes), ("Energy range (kcal/mol)", self.energy_range)):
            form.addRow(label, widget)
        form.addRow(self.approval); form.addRow(self.finalize_button); form.addRow(actions); form.addRow(self.status)
        output_button.clicked.connect(self.chooseOutputRequested); self.finalize_button.clicked.connect(self.finalizeRequested); self.open_report_button.clicked.connect(self.openReportRequested); self.open_bundle_button.clicked.connect(self.openBundleRequested); self.approval.toggled.connect(self.approvalChanged)


class ScreeningSetupPanel(QtWidgets.QWidget):
    chooseFileRequested = QtCore.pyqtSignal(); chooseDirectoryRequested = QtCore.pyqtSignal(); chooseOutputRequested = QtCore.pyqtSignal()
    previewRequested = QtCore.pyqtSignal(); runRequested = QtCore.pyqtSignal(); inputsChanged = QtCore.pyqtSignal(); approvalChanged = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("screening_setup_panel")
        form = QtWidgets.QFormLayout(self)
        self.ligands = QtWidgets.QLineEdit(); ligand_row = QtWidgets.QWidget(); ll = QtWidgets.QHBoxLayout(ligand_row); ll.setContentsMargins(0,0,0,0); ll.addWidget(self.ligands)
        file_button = QtWidgets.QPushButton("SDF…"); directory_button = QtWidgets.QPushButton("Folder…"); ll.addWidget(file_button); ll.addWidget(directory_button)
        self.output = QtWidgets.QLineEdit(); output_row, output_button = _path_row(self.output, "Browse…")
        self.analysis = QtWidgets.QComboBox(); self.analysis.addItem("Representative poses + interactions", "representatives"); self.analysis.addItem("Cluster summary only", "summary"); self.analysis.addItem("Docking outputs only", "none")
        self.representatives = QtWidgets.QSpinBox(); self.representatives.setRange(1,100); self.representatives.setValue(3)
        self.cluster_rmsd = QtWidgets.QDoubleSpinBox(); self.cluster_rmsd.setRange(.1,20); self.cluster_rmsd.setValue(2); self.cluster_rmsd.setSuffix(" Å")
        self.stop_on_error = QtWidgets.QCheckBox("Stop the library after the first failed compound")
        self.approval = QtWidgets.QCheckBox("I authorize screening with this exploratory protocol without pose-recovery control"); self.approval.setObjectName("exploratory_screening_approval")
        self.preview_button = QtWidgets.QPushButton("Preview workload (chemistry validated at launch)")
        self.run_button = QtWidgets.QPushButton("Run locked-protocol screening"); self.run_button.setObjectName("start_locked_screening_button")
        self.status = QtWidgets.QLabel("Finalize a reusable protocol, then select ligands and preview the workload."); self.status.setWordWrap(True)
        for label, widget in (("Ligand SDF or directory", ligand_row), ("Screening output", output_row), ("Analysis", self.analysis), ("Representative clusters", self.representatives), ("Clustering cutoff", self.cluster_rmsd)):
            form.addRow(label, widget)
        for widget in (self.stop_on_error, self.approval, self.preview_button, self.run_button, self.status): form.addRow(widget)
        file_button.clicked.connect(self.chooseFileRequested); directory_button.clicked.connect(self.chooseDirectoryRequested); output_button.clicked.connect(self.chooseOutputRequested); self.preview_button.clicked.connect(self.previewRequested); self.run_button.clicked.connect(self.runRequested); self.approval.toggled.connect(self.approvalChanged)
        self.ligands.textChanged.connect(self.inputsChanged); self.output.textChanged.connect(self.inputsChanged); self.analysis.currentIndexChanged.connect(self.inputsChanged); self.representatives.valueChanged.connect(self.inputsChanged); self.cluster_rmsd.valueChanged.connect(self.inputsChanged)
