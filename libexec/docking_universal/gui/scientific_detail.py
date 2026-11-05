"""Presentation-only scientific workflow detail component."""

from __future__ import annotations

from .qt import QtCore, QtWidgets
from .explanations import ExplanationWindow

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
        self.full_details_button = QtWidgets.QPushButton("Full details…")
        self.full_details_button.setObjectName("show_full_scientific_details")
        controls.addWidget(self.mode, 1)
        controls.addWidget(self.full_details_button)
        self.view = QtWidgets.QTextBrowser()
        self.view.setObjectName("scientific_event_timeline")
        layout.addLayout(controls)
        layout.addWidget(self.view, 1)
        self.mode.currentTextChanged.connect(self.detailChanged)
        self.full_details_button.clicked.connect(self.show_full_details)
        self._full_details_window = None
        self._full_details_text = ''

    @property
    def detail(self) -> ScientificDetail:
        return ScientificDetail(self.mode.currentText().lower())

    def show_full_details(self) -> None:
        if self._full_details_window is None:
            self._full_details_window = ExplanationWindow('Full scientific details', self)
        self._full_details_window.set_content(self._full_details_text)
        self._full_details_window.show()
        self._full_details_window.raise_()
        self._full_details_window.activateWindow()

    def render(self, state: StudyState) -> None:
        self.view.setPlainText(self._event_text(state, self.detail))
        self._full_details_text = self._event_text(state, ScientificDetail.TECHNICAL)
        if self._full_details_window is not None:
            self._full_details_window.set_content(self._full_details_text)

    @staticmethod
    def _event_text(state, detail):
        blocks = []
        for event in state.events:
            value = event.presented(detail)
            lines = [f"{value['sequence']}. {value['message']}"]
            for key in ("explanation", "teaching", "technical", "data"):
                if value.get(key):
                    lines.append(str(value[key]))
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)
