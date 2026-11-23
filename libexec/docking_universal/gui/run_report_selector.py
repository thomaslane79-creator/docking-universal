"""Choose retained screening runs and how their reports are presented."""
from .qt import QtCore, QtWidgets
from ..services.run_reports import PDF_QUALITIES, require_matching_methods


class RunReportSelector(QtWidgets.QDialog):
    def __init__(self, runs, current_root=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Choose screening runs for reports')
        self.resize(720, 450)
        layout = QtWidgets.QVBoxLayout(self)
        explanation = QtWidgets.QLabel('Select the runs to include. Each run keeps its own results and provenance.')
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.runs = QtWidgets.QListWidget()
        for record in runs:
            root = record['root']
            names = ', '.join(record['names'][:4]) or 'compound names unavailable'
            if len(record['names']) > 4:
                names += f" and {len(record['names']) - 4} more"
            item = QtWidgets.QListWidgetItem(f'{root.name} · {names}')
            item.setToolTip(str(root))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, record)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Checked if current_root and root == current_root else QtCore.Qt.CheckState.Unchecked)
            self.runs.addItem(item)
        if self.runs.count() and not self.selected_runs():
            self.runs.item(0).setCheckState(QtCore.Qt.CheckState.Checked)
        layout.addWidget(self.runs, 1)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItem('Open individual reports', 'individual')
        self.mode.addItem('One report with separate run sections', 'sections')
        self.mode.addItem('Combined results by compound — identical methods required', 'merged')
        layout.addWidget(self.mode)
        self.quality = QtWidgets.QComboBox()
        self.quality.addItem('Use saved PDFs', 'saved')
        for label, quality in PDF_QUALITIES:
            self.quality.addItem(label, quality)
        form = QtWidgets.QFormLayout()
        form.addRow('PDF quality', self.quality)
        layout.addLayout(form)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText('Continue')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.runs.itemChanged.connect(self._update)
        self.mode.currentIndexChanged.connect(self._update)
        self._update()

    def selected_runs(self):
        return [self.runs.item(i).data(QtCore.Qt.ItemDataRole.UserRole) for i in range(self.runs.count())
                if self.runs.item(i).checkState() == QtCore.Qt.CheckState.Checked]

    def _update(self, *_args):
        merged = self.mode.currentData() == 'merged'
        self.quality.model().item(0).setEnabled(not merged)
        if merged and self.quality.currentData() == 'saved':
            self.quality.setCurrentIndex(1)
        selected = self.selected_runs()
        ready = bool(selected)
        message = 'Select at least one run.' if not selected else ''
        if ready and merged:
            try:
                require_matching_methods([record['root'] for record in selected])
                message = 'Recorded methods match exactly. Results are alphabetical and identify each run; poses and clusters remain separate.'
            except ValueError as exc:
                ready, message = False, str(exc)
        elif ready and self.mode.currentData() == 'sections':
            message = 'Each selected report remains a separate section; methods may differ.'
        self.status.setText(message)
        self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setEnabled(ready)
