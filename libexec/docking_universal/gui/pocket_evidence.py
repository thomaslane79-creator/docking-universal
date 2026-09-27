"""Detachable presentation of experimental evidence for pocket decisions."""

from __future__ import annotations

from .qt import QtCore, QtWidgets


class PocketEvidencePanel(QtWidgets.QWidget):
    ligandRequested = QtCore.pyqtSignal(str)
    ligandsRequested = QtCore.pyqtSignal(list)
    selectionChanged = QtCore.pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pocket_evidence_panel")
        layout = QtWidgets.QVBoxLayout(self)
        self.heading = QtWidgets.QLabel("Select a docking-box candidate to inspect its evidence.")
        self.heading.setWordWrap(True)
        self.warning = QtWidgets.QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("background:#fff1b8;color:#332600;padding:6px")
        self.warning.hide()
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(("Class", "PDB", "Ligand", "Cα RMSD (Å)", "Identity", "Coverage"))
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.note = QtWidgets.QLabel(
            "Double-click an observation to show its aligned deposited ligand in PyMOL. "
            "Experimental correspondence supports a decision; it does not approve a box."
        )
        self.note.setWordWrap(True)
        self.compare_button = QtWidgets.QPushButton("Show selected observations in PyMOL")
        self.compare_button.setEnabled(False)
        self.compare_button.clicked.connect(self._request_selected_ligands)
        layout.addWidget(self.heading)
        layout.addWidget(self.warning)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.compare_button)
        layout.addWidget(self.note)
        self.table.itemDoubleClicked.connect(self._request_ligand)
        self.table.itemSelectionChanged.connect(self._selection_changed)

    def set_viewer_presentation(self, *, embedded: bool) -> None:
        """Describe the action without implying a second application in embedded mode."""
        if embedded:
            self.note.setText(
                "Double-click an observation to show its aligned deposited ligand in the "
                "interactive structure view. Experimental correspondence supports a decision; "
                "it does not approve a box."
            )
            self.compare_button.setText(
                "Show selected observations in interactive structure"
            )
        else:
            self.note.setText(
                "Double-click an observation to show its aligned deposited ligand in PyMOL. "
                "Experimental correspondence supports a decision; it does not approve a box."
            )
            self.compare_button.setText("Show selected observations in PyMOL")

    def set_candidate(self, candidate: dict | None) -> None:
        evidence = (candidate or {}).get("evidence", {})
        experimental = evidence.get("experimental_ligand_evidence") or {}
        observations = experimental.get("observations") or []
        label = (candidate or {}).get("label") or (candidate or {}).get("id") or "No candidate"
        classes = experimental.get("evidence_class_counts") or {}
        self.heading.setText(
            f"{label}: {experimental.get('observation_count', 0)} deposited-ligand observations · "
            f"{experimental.get('pdb_entry_count', 0)} PDB entries · "
            f"exact {classes.get('exact_sequence_match', 0)} · homolog {classes.get('close_structural_homolog', 0)}"
        )
        conformation = evidence.get("conformational_site_evidence") or {}
        warning = conformation.get("box_decision_warning") or ""
        self.warning.setText(warning)
        self.warning.setVisible(bool(warning))
        self.table.setRowCount(len(observations))
        for row, item in enumerate(observations):
            values = (
                str(item.get("evidence_class", "")).replace("_", " "), item.get("entry", ""),
                item.get("ligand", ""), self._number(item.get("ca_rmsd_angstrom"), 3),
                self._percent(item.get("sequence_identity")), self._percent(item.get("query_coverage")),
            )
            for column, value in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(str(value))
                cell.setData(QtCore.Qt.ItemDataRole.UserRole, item.get("aligned_ligand_pdb"))
                self.table.setItem(row, column, cell)
        self.table.resizeColumnsToContents()

    @staticmethod
    def _number(value, decimals):
        return f"{value:.{decimals}f}" if isinstance(value, (int, float)) else "—"

    @staticmethod
    def _percent(value):
        return f"{100 * value:.1f}%" if isinstance(value, (int, float)) else "—"

    def _request_ligand(self, item) -> None:
        path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if path:
            self.ligandRequested.emit(str(path))

    def _selected_paths(self) -> list[str]:
        paths = []
        for row in sorted({index.row() for index in self.table.selectionModel().selectedRows()}):
            item = self.table.item(row, 0)
            path = item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None
            if path:
                paths.append(str(path))
        return paths

    def _request_selected_ligands(self) -> None:
        paths = self._selected_paths()
        if paths:
            self.ligandsRequested.emit(paths)

    def _selection_changed(self) -> None:
        paths = self._selected_paths()
        self.compare_button.setEnabled(bool(paths))
        self.selectionChanged.emit(paths)
