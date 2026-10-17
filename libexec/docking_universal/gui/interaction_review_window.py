"""Resizable paired review, borrowing the single owned PyMOL viewport."""
from .qt import QtCore, QtGui, QtWidgets
from .linked_pose_review import contact_residues
import html
import xml.etree.ElementTree as ET
from .image_export import save_image_button, diagram_export, pymol_export, paired_export


class InteractionReviewWindow(QtWidgets.QDialog):
    def __init__(self, view, diagram_panel, viewer, adapter, parent=None):
        super().__init__(parent, QtCore.Qt.WindowType.Window)
        self.setObjectName("paired_interaction_review_window")
        self.setWindowTitle("Docking Universal — 2D / 3D interaction review")
        self.resize(1120, 760)
        self.view = view
        self.adapter = adapter
        self.viewer = viewer
        self.diagram_panel = diagram_panel
        self.residue_buttons = {}
        self.contact_type_actions = {}
        layout = QtWidgets.QVBoxLayout(self)
        bar = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel(view.label)
        title.setWordWrap(True)
        bar.addWidget(title, 1)
        self.save_image = save_image_button(self, [
            ('3D PyMOL view', lambda: viewer.isVisible(),
             lambda: pymol_export(viewer, {'label': view.label,
                 'coordinate_kind': 'experimental' if view.experimental else view.coordinate_kind},
                 (view.diagram, view.ligand, view.receptor, view.interactions))),
            ('3D PyMOL view — ray-traced PNG', lambda: viewer.isVisible(),
             lambda: pymol_export(viewer, {'label': view.label,
                 'coordinate_kind': 'experimental' if view.experimental else view.coordinate_kind},
                 (view.diagram, view.ligand, view.receptor, view.interactions), ray=True)),
            ('2D diagram — original resolution', lambda: view.diagram.is_file(),
             lambda: diagram_export(view)),
            ('2D / 3D panel', lambda: viewer.isVisible() and view.diagram.is_file(),
             lambda: paired_export(view, viewer, self._export_contact_legend())),
            ('2D / 3D panel — ray-traced 3D', lambda: viewer.isVisible() and view.diagram.is_file(),
             lambda: paired_export(view, viewer, self._export_contact_legend(), ray=True)),
        ])
        bar.addWidget(self.save_image)
        close = QtWidgets.QPushButton("Return to workspace")
        close.clicked.connect(self.close)
        bar.addWidget(close)
        layout.addLayout(bar)
        self.basis = QtWidgets.QLabel(
            "Experimental structure only — not a docked pose. Both views use the same retained "
            "experimental receptor and ligand coordinates. PLIP contacts are calculated from those "
            "coordinates, not predictions for the study receptor."
            if view.experimental else
            "Docked pose — both views use this exact retained docking pose and receptor. Contacts do not establish affinity."
            if view.coordinate_kind == "docked" else
            "Both views use the same retained receptor and ligand coordinates. The source kind is not recorded; contacts do not establish affinity.")
        self.basis.setWordWrap(True)
        layout.addWidget(self.basis)
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(diagram_panel)
        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QtWidgets.QLabel("3D · ligand and contacting residues"))
        right_layout.addWidget(viewer, 1)
        options = QtWidgets.QHBoxLayout()
        self.cartoon = QtWidgets.QCheckBox('Protein cartoon')
        self.cartoon.setChecked(True)
        self.cartoon.toggled.connect(adapter.set_review_cartoon_visible)
        options.addWidget(self.cartoon)
        self.contacts = QtWidgets.QCheckBox('PLIP contacts')
        self.contacts.setChecked(True)
        self.contacts.toggled.connect(adapter.set_review_contacts_visible)
        options.addWidget(self.contacts)
        self.labels = QtWidgets.QCheckBox('Residue labels')
        self.labels.setObjectName('review_residue_labels')
        self.labels.setToolTip('Check to label all visible contact residues; uncheck to clear review labels. Click a 3D residue to toggle its label individually.')
        self.labels.toggled.connect(self.toggle_labels)
        options.addWidget(self.labels)
        options.addStretch()
        self._viewer_tooltip = viewer.toolTip()
        viewer.setToolTip("Click a 3D residue to show/hide its label. Click a boxed 2D residue name to center on it.")
        scroll = QtWidgets.QScrollArea()
        self.residue_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        row = QtWidgets.QWidget()
        buttons_layout = QtWidgets.QHBoxLayout(row)
        buttons_layout.setContentsMargins(4, 2, 4, 2)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        try:
            residues = contact_residues(view)
        except (OSError, ET.ParseError, ValueError) as exc:
            residues = []
            self.status.setText(f"Residue links unavailable: {exc}")
        self._residues = residues
        failures = []
        for residue in residues:
            key = self.key(residue)
            button = QtWidgets.QCheckBox()
            button.setText(f"{residue['name']} {residue['chain']}:{residue['number']}")
            try:
                adapter.set_contact_residue_visible(residue, True)
                button.setChecked(True)
            except ValueError as exc:
                button.setEnabled(False)
                button.setToolTip(str(exc))
                failures.append(str(exc))
            button.toggled.connect(lambda visible, r=residue: self.toggle_residue(r, visible))
            buttons_layout.addWidget(button)
            self.residue_buttons[key] = button
        buttons_layout.addStretch()
        scroll.setWidget(row)
        # One checkbox row plus its horizontal scrollbar; no oversized margin
        # stealing height from the PyMOL viewport.
        scroll.setFixedHeight(row.sizeHint().height() +
                              self.style().pixelMetric(QtWidgets.QStyle.PixelMetric.PM_ScrollBarExtent) + 4)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([560, 560])
        layout.addWidget(self.splitter, 1)
        layout.addWidget(self.status)
        if failures:
            self.status.setText("Some residue links could not be mapped: " + "; ".join(failures))
        elif residues:
            self.status.setText(f"All {len(residues)} recorded contact residues are shown. Click a 2D label to center; uncheck below to hide sticks.")
        elif not self.status.text():
            self.status.setText("No PLIP contact residues were recorded for this ligand.")
        adapter.focus_interaction_review()
        try:
            styles = adapter.show_review_contacts(view.interactions)
            if isinstance(styles, dict) and styles:
                self._contact_styles = styles
                self.contact_key = QtWidgets.QLabel()
                self.contact_key.setWordWrap(True)
                self.contact_key.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.LinksAccessibleByMouse |
                                                       QtCore.Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
                self.contact_key.setOpenExternalLinks(False)
                self.contact_key.setToolTip('Click a contact type to toggle it in 3D only; the retained 2D diagram stays unchanged.')
                for kind, style in sorted(styles.items()):
                    action = QtGui.QAction(style[0], self)
                    action.setCheckable(True)
                    action.setChecked(True)
                    action.toggled.connect(lambda visible, k=kind: self.toggle_contact_type(k, visible))
                    self.contact_type_actions[kind] = action
                self.contact_key.linkActivated.connect(self._activate_contact_key)
                self._update_contact_key()
                right_layout.addWidget(self.contact_key)
        except (OSError, ET.ParseError, ValueError) as exc:
            self.contacts.setEnabled(False)
            self.status.setText(f'3D contacts unavailable: {exc}')
        right_layout.addLayout(options)
        right_layout.addWidget(scroll)
        adapter.enable_review_picking()
        if hasattr(viewer, 'residuePicked'):
            viewer.residuePicked.connect(self.clicked_3d_residue)
        diagram_panel.query_image.residueActivated.connect(self.clicked_residue)
        diagram_panel.query_image.activated.connect(self.clicked_ligand)
        diagram_panel.status.setText(
            "Click a boxed residue name or ligand heading to center in 3D; click a 3D residue to label/unlabel. 2D zoom stays unchanged."
            if getattr(diagram_panel.query_image, 'hit_regions', []) else
            "Retained diagram has no verified residue links. Click the ligand heading to center; click a 3D residue to label/unlabel.")

    @staticmethod
    def key(residue):
        return residue["chain"], residue["number"], residue["name"]

    def _export_contact_legend(self):
        if not self.contacts.isChecked():
            return []
        return [(action.text(), self._contact_styles[kind][1])
                for kind, action in self.contact_type_actions.items() if action.isChecked()]

    def clicked_residue(self, residue):
        button = self.residue_buttons.get(self.key(residue))
        if button is not None and button.isEnabled():
            try:
                self.adapter.center_contact_residue(residue)
                self.status.setText(f"Centered on {residue['name']} {residue['chain']}:{residue['number']} · "
                                    "zoom unchanged; checkbox controls visibility" +
                                    (" (sticks remain hidden)" if not button.isChecked() else ""))
            except ValueError as exc:
                self.status.setText(str(exc))
        else:
            self.status.setText("This contact residue cannot be mapped uniquely to the displayed source receptor.")

    def clicked_ligand(self):
        try:
            self.adapter.center_review_ligand()
            self.status.setText("Centered on the matching ligand · zoom and residue visibility unchanged")
        except ValueError as exc:
            self.status.setText(str(exc))

    def clicked_3d_residue(self, residue):
        try:
            shown = self.adapter.toggle_review_residue_label(residue)
            if shown is not None:
                self._sync_label_checkbox()
                self.status.setText(f"{residue['name']} {residue['chain']}:{residue['number']} "
                                    f"label {'shown' if shown else 'hidden'} · click again to toggle")
        except ValueError as exc:
            self.status.setText(str(exc))

    def toggle_residue(self, residue, visible):
        try:
            self.adapter.set_contact_residue_visible(residue, visible)
            if not visible or self.labels.isChecked():
                self.adapter.set_review_residue_label(residue, visible)
                self._sync_label_checkbox()
            self.status.setText(f"{residue['name']} {residue['chain']}:{residue['number']} "
                                f"{'shown' if visible else 'hidden'} · camera and diagram zoom unchanged")
        except ValueError as exc:
            button = self.residue_buttons[self.key(residue)]
            blocker = QtCore.QSignalBlocker(button)
            button.setChecked(False)
            del blocker
            self.status.setText(str(exc))

    def _sync_label_checkbox(self):
        blocker = QtCore.QSignalBlocker(self.labels)
        self.labels.setChecked(self.adapter.has_review_residue_labels())
        del blocker

    def toggle_labels(self, visible):
        residues = [r for r in self._residues
                    if self.residue_buttons[self.key(r)].isEnabled()
                    and self.residue_buttons[self.key(r)].isChecked()]
        try:
            self.adapter.set_review_labels_visible(residues, visible)
            self._sync_label_checkbox()
            self.status.setText('3D residue labels ' + ('shown' if self.labels.isChecked() else 'hidden') +
                                ' · camera, contacts and 2D diagram unchanged')
        except ValueError as exc:
            self._sync_label_checkbox()
            self.status.setText(str(exc))

    def toggle_contact_type(self, kind, visible):
        self.adapter.set_review_contact_type_visible(kind, visible)
        self._update_contact_key()
        label = self.contact_type_actions[kind].text()
        self.status.setText(f"{label} {'shown' if visible else 'hidden'} in 3D · "
                           'camera and retained 2D diagram unchanged')

    def _activate_contact_key(self, kind):
        if kind in self.contact_type_actions:
            self.contact_type_actions[kind].trigger()

    def _update_contact_key(self):
        text_color = self.palette().color(QtGui.QPalette.ColorRole.WindowText).name()
        entries = []
        for kind, action in self.contact_type_actions.items():
            color = self._contact_styles[kind][1] if action.isChecked() else '#888888'
            text = html.escape(action.text())
            if not action.isChecked():
                text = '<s>' + text + '</s>'
            entries.append(f'<a href="{kind}" style="color:{text_color}; text-decoration:none;">'
                           f'<span style="color:{color}">{"■" if action.isChecked() else "□"}</span> {text}</a>')
        self.contact_key.setText('3D contacts: ' + ' &nbsp; · &nbsp; '.join(entries))

    def dispose(self):
        self.viewer.setToolTip(self._viewer_tooltip)
        if hasattr(self.viewer, 'residuePicked'):
            self.viewer.residuePicked.disconnect(self.clicked_3d_residue)
        self.diagram_panel.query_image.residueActivated.disconnect(self.clicked_residue)
        self.diagram_panel.query_image.activated.disconnect(self.clicked_ligand)
