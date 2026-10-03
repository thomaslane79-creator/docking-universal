"""Graphical entry point for creating or reopening one scientific study."""

from __future__ import annotations

import re

from .qt import QtCore, QtWidgets


def study_id_from_name(name: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip()).strip("-._")
    return value or "study"


class StudyLauncherDialog(QtWidgets.QDialog):
    def __init__(
        self, store, host_client, parent=None, *, mode="all",
        current_study_id: str | None = None,
    ):
        super().__init__(parent)
        self.store = store
        self.host_client = host_client
        self.selected_study_id: str | None = None
        self.current_study_id = current_study_id
        if mode not in {"all", "create", "open"}:
            raise ValueError(f"Unknown study chooser mode: {mode}")
        self.mode = mode
        self.setWindowTitle("Docking Universal — Studies")
        self.resize(820, 560)
        self.setMinimumWidth(640)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        heading = QtWidgets.QLabel("Open a scientific study")
        font = heading.font(); font.setPointSize(font.pointSize() + 4); font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)
        explanation = QtWidgets.QLabel(
            "Each entry is one persistent scientific run. Reopening a study never starts a second job."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.studies = QtWidgets.QTableWidget(0, 4)
        self.studies.setHorizontalHeaderLabels(("Study", "Workflow", "Status", "Last updated"))
        self.studies.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.studies.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.studies.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.studies.horizontalHeader().setStretchLastSection(True)
        self.studies.itemSelectionChanged.connect(self._selection_changed)
        self.studies.itemDoubleClicked.connect(lambda _item: self.open_selected())
        layout.addWidget(self.studies, 1)
        self.empty_notice = QtWidgets.QLabel("No saved studies. Create a study below to begin.")
        self.empty_notice.setWordWrap(True)
        layout.addWidget(self.empty_notice)
        for label in (heading, explanation, self.empty_notice):
            label.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Preferred,
                QtWidgets.QSizePolicy.Policy.Maximum,
            )

        create_group = self.create_group = QtWidgets.QGroupBox("Create a new study")
        create_group.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Maximum,
        )
        form = QtWidgets.QVBoxLayout(create_group)
        form.setContentsMargins(14, 18, 14, 14)
        form.setSpacing(10)
        self.study_name = QtWidgets.QLineEdit()
        self.study_name.setPlaceholderText("For example: COX-2 compound screening")
        self.study_name.setMinimumWidth(360)
        self.workflow_scope = QtWidgets.QLabel(
            "Next, choose a structure file or download one by PDB ID. "
            "You’ll choose exploratory docking or known-ligand redocking in Study setup."
        )
        self.workflow_scope.setWordWrap(True)
        form.addWidget(QtWidgets.QLabel("Study name"))
        form.addWidget(self.study_name)
        form.addWidget(self.workflow_scope)
        layout.addWidget(create_group)
        if mode == "create":
            heading.setText("Create a new scientific study")
            explanation.setText(
                "A new study has its own immutable scientific setup and retained audit trail."
            )
            self.studies.hide()
        elif mode == "open":
            create_group.hide()

        buttons = QtWidgets.QHBoxLayout()
        self.create_button = QtWidgets.QPushButton("Create study")
        self.open_button = QtWidgets.QPushButton("Open selected study")
        self.open_button.setEnabled(False)
        self.delete_button = QtWidgets.QPushButton("Delete selected study…")
        self.delete_button.setObjectName("delete_selected_study_button")
        self.delete_button.setEnabled(False)
        cancel = QtWidgets.QPushButton("Cancel")
        self.create_button.clicked.connect(self.create_study)
        self.open_button.clicked.connect(self.open_selected)
        self.delete_button.clicked.connect(self.delete_selected)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.create_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.open_button)
        self.create_button.setVisible(mode != "open")
        self.open_button.setVisible(mode != "create")
        self.delete_button.setVisible(mode != "create")
        layout.addLayout(buttons)
        self.reload()
        if not self.store.list_studies() or mode == "create":
            self.resize(820, 340)

    def reload(self) -> None:
        values = self.store.list_studies()
        self.studies.setRowCount(len(values))
        self.studies.setVisible(bool(values) and self.mode != "create")
        self.empty_notice.setVisible(not values and self.mode != "create")
        for row, state in enumerate(values):
            cells = (state.name, state.workflow, state.completion_status.value, state.updated_at)
            for column, value in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(QtCore.Qt.ItemDataRole.UserRole, state.study_id)
                self.studies.setItem(row, column, item)
        self.studies.resizeColumnsToContents()
        self._selection_changed()

    def _selection_changed(self) -> None:
        rows = self.studies.selectionModel().selectedRows()
        self.open_button.setEnabled(bool(rows))
        selected = None
        if rows:
            selected = str(
                self.studies.item(rows[0].row(), 0).data(QtCore.Qt.ItemDataRole.UserRole)
            )
        self.delete_button.setEnabled(bool(selected and selected != self.current_study_id))

    def delete_selected(self) -> None:
        rows = self.studies.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        study_id = str(
            self.studies.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole)
        )
        if study_id == self.current_study_id:
            QtWidgets.QMessageBox.information(
                self, "Current study is open",
                "Open a different study before deleting this study from the active library.",
            )
            return
        name = self.studies.item(row, 0).text()
        state = self.store.load(study_id)
        unfinished = state.active_job is not None
        stage_notice = (
            "This study has an unfinished stage recorded. If this was a broken or "
            "abandoned job, would you like to override that record and delete the "
            "study anyway? A calculation still running in the application cannot "
            "be overridden.\n\n"
            if unfinished else ""
        )
        answer = QtWidgets.QMessageBox.question(
            self, "Delete study from Docking Universal?",
            (
                f"Delete '{name}' from the active Docking Universal study list?\n\n"
                + stage_notice +
                "This does not delete external reports, .duprotocol bundles, receptor files, "
                "or docking output directories. The retained application-state record remains "
                "recoverable on disk."
            ),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            self.host_client.request(
                study_id, "remove_study", {"override_stale_job": unfinished},
            )
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Study could not be deleted from the library", str(exc)
            )
            return
        self.reload()

    def open_selected(self) -> None:
        rows = self.studies.selectionModel().selectedRows()
        if not rows:
            return
        self.selected_study_id = str(
            self.studies.item(rows[0].row(), 0).data(QtCore.Qt.ItemDataRole.UserRole)
        )
        self.accept()

    def create_study(self) -> None:
        name = self.study_name.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Study name required", "Enter a descriptive study name.")
            return
        base = study_id_from_name(name)
        study_id = base
        suffix = 2
        while self.store.path_for(study_id).exists():
            study_id = f"{base}-{suffix}"
            suffix += 1
        try:
            self.host_client.request(study_id, "create_study", {
                "name": name, "workflow": "site_guided_protocol",
            })
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Study could not be created", str(exc))
            return
        self.selected_study_id = study_id
        self.accept()


def choose_study(
    store, host_client, parent=None, *, mode="all", current_study_id: str | None = None,
) -> str | None:
    dialog = StudyLauncherDialog(
        store, host_client, parent, mode=mode, current_study_id=current_study_id,
    )
    return dialog.selected_study_id if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted else None
