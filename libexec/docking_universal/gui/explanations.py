"""Compact teaching text with a separate, read-only explanation window.

Summaries are written explicitly by each panel, never truncated automatically:
warnings, consent and scientific choices must remain visible at their source.
This component owns presentation only, with no workflow or settings callbacks.
"""
from html import escape

from .qt import QtCore, QtWidgets


class ExplanationWindow(QtWidgets.QDialog):
    """Reusable modeless window; opening or closing it grants no authority."""

    def __init__(self, title, parent=None):
        super().__init__(parent, QtCore.Qt.WindowType.Window)
        self.setObjectName('explanation_window')
        self.setWindowTitle(title)
        self.resize(660, 480)
        layout = QtWidgets.QVBoxLayout(self)
        self.content = QtWidgets.QTextBrowser()
        self.content.setObjectName('explanation_content')
        self.content.setOpenExternalLinks(False)
        self._content_text = None
        layout.addWidget(self.content, 1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def set_content(self, text):
        text = str(text)
        if text == self._content_text:
            return  # Passive refreshes must not reset the reader's scroll position.
        scroll = self.content.verticalScrollBar().value()
        self._content_text = text
        # File names and deposited metadata are data, not markup or links.
        paragraphs = ''.join('<p>' + escape(part).replace('\n', '<br>') + '</p>'
                             for part in text.split('\n\n'))
        self.content.setHtml('<h2>' + escape(self.windowTitle()) + '</h2>' + paragraphs)
        self.content.verticalScrollBar().setValue(scroll)


class ExplanationLabel(QtWidgets.QLabel):
    """A short wrapping sentence and a keyboard-accessible Explain… link."""

    def __init__(self, summary, title, details, parent=None):
        super().__init__(parent)
        self.explanation_title = title
        self.explanation_window = None
        self.details_text = ''
        self.summary_text = ''
        self.setWordWrap(True)
        self.setOpenExternalLinks(False)
        self.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse |
            QtCore.Qt.TextInteractionFlag.LinksAccessibleByMouse |
            QtCore.Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.linkActivated.connect(self.show_explanation)
        self.set_content(summary, details)

    def set_content(self, summary, details):
        self.summary_text, self.details_text = str(summary), str(details)
        link = ' <a href="explain">Explain…</a>' if self.details_text else ''
        super().setText(escape(self.summary_text).replace('\n', '<br>') + link)
        self.setAccessibleName(self.summary_text)
        self.setAccessibleDescription(self.details_text)
        if self.explanation_window is not None:
            self.explanation_window.set_content(self.details_text)

    def setText(self, text):
        """Dynamic status changes keep the same topic's explanation available."""
        self.set_content(text, self.details_text)

    def keyPressEvent(self, event):
        # QLabel can focus its text without focusing the embedded anchor. Make
        # Enter/Space reliable after tabbing to this single-action help label.
        if (event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter, QtCore.Qt.Key.Key_Space)
                and event.modifiers() == QtCore.Qt.KeyboardModifier.NoModifier and self.details_text):
            self.show_explanation()
            event.accept()
            return
        super().keyPressEvent(event)

    def show_explanation(self, _link=None):
        if not self.details_text:
            return
        if self.explanation_window is None:
            self.explanation_window = ExplanationWindow(self.explanation_title, self)
        self.explanation_window.set_content(self.details_text)
        self.explanation_window.show()
        self.explanation_window.raise_()
        self.explanation_window.activateWindow()
