"""Presentation-only scientific workflow detail component."""

from __future__ import annotations

from .qt import QtCore, QtWidgets

from ..events import ScientificDetail
from ..state import StudyState


class ScientificDetailPanel(QtWidgets.QWidget):
    """Render scientific events without controlling warnings or workflow state."""

    detailChanged = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("scientific_detail_panel")
        layout = QtWidgets.QVBoxLayout(self)
        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(QtWidgets.QLabel("Scientific Workflow Detail:"))
        self.mode = QtWidgets.QComboBox()
        self.mode.setObjectName("scientific_detail_mode")
        self.mode.addItems([item.value.title() for item in ScientificDetail])
        self.mode.setCurrentText("Guided")
        self.full_details_button = QtWidgets.QPushButton("Show full details")
        self.full_details_button.setObjectName("show_full_scientific_details")
        controls.addWidget(self.mode, 1)
        controls.addWidget(self.full_details_button)
        self.view = QtWidgets.QTextBrowser()
        self.view.setObjectName("scientific_event_timeline")
        layout.addLayout(controls)
        layout.addWidget(self.view, 1)
        self.mode.currentTextChanged.connect(self.detailChanged)
        self.full_details_button.clicked.connect(self.show_full_details)

    @property
    def detail(self) -> ScientificDetail:
        return ScientificDetail(self.mode.currentText().lower())

    def show_full_details(self) -> None:
        self.mode.setCurrentText("Technical")

    def render(self, state: StudyState) -> None:
        blocks = []
        for event in state.events:
            value = event.presented(self.detail)
            lines = [f"{value['sequence']}. {value['message']}"]
            for key in ("explanation", "teaching", "technical", "data"):
                if value.get(key):
                    lines.append(str(value[key]))
            blocks.append("\n".join(lines))
        self.view.setPlainText("\n\n".join(blocks))
