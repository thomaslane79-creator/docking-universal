"""Compact controls for the exact representative currently in the live scene."""
from .qt import QtCore, QtGui, QtWidgets


class ContactTypeControls(QtWidgets.QWidget):
    """Native labeled checkboxes, shared by compact and paired review views."""
    visibilityChanged = QtCore.pyqtSignal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('plip_contact_types')
        self.buttons = {}
        self.grid = QtWidgets.QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)

    def set_styles(self, styles):
        while self.grid.count():
            item = self.grid.takeAt(0)
            item.widget().deleteLater()
        self.buttons.clear()
        for index, (kind, (label, color, dashed)) in enumerate(sorted(styles.items())):
            button = QtWidgets.QCheckBox(label)
            button.setObjectName('plip_type_' + kind)
            button.setChecked(True)
            button.setToolTip('Show or hide ' + label.lower() + ' in 3D; the 2D diagram stays unchanged.')
            button.setAccessibleDescription(button.toolTip())
            ratio = self.devicePixelRatioF()
            swatch = QtGui.QPixmap(round(26 * ratio), round(14 * ratio))
            swatch.setDevicePixelRatio(ratio)
            swatch.fill(QtCore.Qt.GlobalColor.transparent)
            painter = QtGui.QPainter(swatch)
            pen = QtGui.QPen(QtGui.QColor(color), 3)
            if dashed:
                pen.setStyle(QtCore.Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(1, 7, 25, 7)
            painter.end()
            button.setIcon(QtGui.QIcon(swatch))
            button.toggled.connect(lambda visible, k=kind: self.visibilityChanged.emit(k, visible))
            self.grid.addWidget(button, index // 2, index % 2)
            self.buttons[kind] = button
        self.setVisible(bool(styles))

    def sync_visibility(self, visibility):
        for kind, button in self.buttons.items():
            blocker = QtCore.QSignalBlocker(button)
            button.setChecked(bool(visibility.get(kind, False)))
            del blocker


class ClusterContactControls(QtWidgets.QWidget):
    def __init__(self, adapter, parent=None):
        super().__init__(parent)
        self.adapter = adapter
        self.styles = {}
        self.visible_types = {}
        self.residues = []
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.key = QtWidgets.QLabel('3D PLIP interaction types')
        layout.addWidget(self.key)
        self.types = ContactTypeControls()
        self.types.visibilityChanged.connect(self.set_type_visible)
        layout.addWidget(self.types)
        row = QtWidgets.QHBoxLayout()
        self.contacts = QtWidgets.QCheckBox('PLIP contacts')
        self.cartoon = QtWidgets.QCheckBox('Protein cartoon')
        self.labels = QtWidgets.QCheckBox('Residue labels')
        self.contacts.toggled.connect(self.toggle_contacts)
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
        self.types.set_styles(styles)
        self.types.setEnabled(bool(styles))
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
        self.set_type_visible(kind, not self.visible_types[kind])

    def set_type_visible(self, kind, visible):
        if kind not in self.visible_types:
            return
        self.adapter.set_review_contact_type_visible(kind, visible)
        self.visible_types[kind] = visible
        self.update_key()

    def toggle_contacts(self, visible):
        self.adapter.set_review_contacts_visible(visible)
        self.types.setEnabled(visible)

    def update_key(self):
        self.key.setText('3D PLIP interaction types' if self.styles else 'No PLIP contacts recorded')
        self.types.sync_visibility(self.visible_types)
