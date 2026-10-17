"""Compact controls for the exact representative currently in the live scene."""
import html
from .qt import QtCore, QtGui, QtWidgets


class ClusterContactControls(QtWidgets.QWidget):
    def __init__(self, adapter, parent=None):
        super().__init__(parent)
        self.adapter = adapter
        self.styles = {}
        self.visible_types = {}
        self.residues = []
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.key = QtWidgets.QLabel()
        self.key.setWordWrap(True)
        self.key.setOpenExternalLinks(False)
        self.key.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.LinksAccessibleByMouse |
                                         QtCore.Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.key.setToolTip('Click a type to toggle its contacts in 3D only; the 2D diagram stays unchanged.')
        self.key.linkActivated.connect(self.toggle_type)
        layout.addWidget(self.key)
        row = QtWidgets.QHBoxLayout()
        self.contacts = QtWidgets.QCheckBox('PLIP contacts')
        self.cartoon = QtWidgets.QCheckBox('Protein cartoon')
        self.labels = QtWidgets.QCheckBox('Residue labels')
        self.contacts.toggled.connect(lambda visible: self.adapter.set_review_contacts_visible(visible))
        self.cartoon.toggled.connect(lambda visible: self.adapter.set_review_cartoon_visible(visible))
        self.labels.toggled.connect(lambda visible: self.adapter.set_review_labels_visible(self.residues, visible))
        for widget in (self.contacts, self.cartoon, self.labels):
            row.addWidget(widget)
        row.addStretch()
        layout.addLayout(row)
        self.hide()

    def set_contacts(self, styles, residues):
        self.styles, self.residues = styles, residues
        self.visible_types = {kind: True for kind in styles}
        for widget, checked in ((self.contacts, True), (self.cartoon, True), (self.labels, False)):
            blocker = QtCore.QSignalBlocker(widget)
            widget.setChecked(checked)
            del blocker
        self.contacts.setEnabled(bool(styles))
        self.labels.setEnabled(bool(residues))
        self.update_key()
        self.show()

    def unavailable(self, reason):
        self.set_contacts({}, [])
        self.key.setText(reason)

    def toggle_type(self, kind):
        if kind not in self.visible_types:
            return
        visible = not self.visible_types[kind]
        self.adapter.set_review_contact_type_visible(kind, visible)
        self.visible_types[kind] = visible
        self.update_key()

    def update_key(self):
        color = self.palette().color(QtGui.QPalette.ColorRole.WindowText).name()
        entries = []
        for kind, (label, contact_color, _dashed) in sorted(self.styles.items()):
            visible = self.visible_types[kind]
            text = html.escape(label)
            if not visible:
                text = '<s>' + text + '</s>'
            entries.append(f'<a href="{kind}" style="color:{color};text-decoration:none">'
                           f'<span style="color:{contact_color if visible else "#888888"}">'
                           f'{"■" if visible else "□"}</span> {text}</a>')
        self.key.setText('3D PLIP contacts: ' + (' &nbsp; · &nbsp; '.join(entries) or 'none recorded'))
