"""Detachable presentation of experimental evidence for pocket decisions."""

from __future__ import annotations

import json
import html

from .qt import QtCore, QtGui, QtWidgets
from .explanations import ExplanationLabel

LIGAND_EVIDENCE_COLOR = "#009b50"
OBSTRUCTION_COLOR = "#a85b00"
OBSTRUCTION_BACKGROUND = "#fff1b8"


def has_obstruction_warning(conformation: dict) -> bool:
    return bool(conformation.get("box_decision_warning")) or conformation.get("status") == "conformationally_incompatible"


def conformation_summary(conformation: dict) -> tuple[str, str]:
    """Describe the actual ligand-accessibility test, not all rotamer changes."""
    status = conformation.get("status", "not_evaluated")
    if status == "conformationally_incompatible":
        residues = ", ".join(
            f"{item.get('name', 'UNK')}{item.get('number', '?')}{item.get('chain', '')}"
            for item in conformation.get("occluding_residues", [])
        )
        return (
            f"Possible ligand obstruction: {residues or 'review residues'}",
            "The current side chain overlaps an aligned deposited ligand more than the "
            "ligand-bound side chain does. This suggests a possible obstruction, not proof "
            "of flexibility. Review whether rigid docking is appropriate. "
            "This flags protein side-chain overlaps, not all protein or ligand rotamer changes.",
        )
    if status == "reviewed_no_geometric_incompatibility":
        return (
            "No ligand obstruction found",
            "No side-chain obstruction was found in the matched deposited-ligand comparisons. "
            "Side-chain conformations may still differ; this does not validate the docking site.",
        )
    return (
        "Ligand obstruction not evaluated",
        "No matched deposited-ligand comparisons were available for this region's "
        "obstruction test. This does not mean no rotamer differences exist.",
    )


class EvidenceText(QtWidgets.QPlainTextEdit):
    """Scrollable text with a stable viewport, independent of message length."""

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:
        self.setPlainText(text)

    def set_conformation_text(self, conformation: dict, *, compact: bool = False) -> None:
        """Repeat the plot's caution key, without exporting text-dependent sizing."""
        summary, explanation = conformation_summary(conformation)
        warning = has_obstruction_warning(conformation)
        heading = f"!  {summary}" if warning else summary
        brief = (
            "Side-chain overlap only; not proof of flexibility."
            if conformation.get("status") == "conformationally_incompatible" else
            "This does not validate the docking site."
            if conformation.get("status") == "reviewed_no_geometric_incompatibility" else
            "Missing comparisons do not establish absence of differences."
        )
        self.setPlainText(heading if compact else f"{heading}\n{brief}")
        if warning:
            cursor = QtGui.QTextCursor(self.document())
            cursor.select(QtGui.QTextCursor.SelectionType.BlockUnderCursor)
            emphasis = QtGui.QTextCharFormat()
            emphasis.setFontWeight(QtGui.QFont.Weight.Bold)
            emphasis.setFontPointSize(self.font().pointSizeF() + 1)
            cursor.mergeCharFormat(emphasis)
            cursor = QtGui.QTextCursor(self.document())
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.NextCharacter,
                                QtGui.QTextCursor.MoveMode.KeepAnchor)
            symbol = QtGui.QTextCharFormat()
            symbol.setForeground(QtGui.QColor(OBSTRUCTION_COLOR))
            symbol.setFontPointSize(self.font().pointSizeF() + 1)
            cursor.mergeCharFormat(symbol)
        self.setToolTip(f"{heading}\n{explanation}")
        self.set_evidence_style(warning=warning)

    def set_evidence_style(self, *, warning: bool) -> None:
        """Style only the text and scrollbar, not native arrow subcontrols.

        Unscoped padding/background rules also affect macOS scrollbar controls
        and leave an arrow/track border until the first scroll repaint.
        Keep the reserved gutter but use one plain, arrow-free thumb instead.
        """
        background, foreground, thumb = (
            (OBSTRUCTION_BACKGROUND, "#332600", "#aa9256") if warning
            else ("#f2f4f6", "#333333", "#8a9299")
        )
        self.setObjectName("evidence_text")
        self.setStyleSheet(
            f"QPlainTextEdit#evidence_text {{background:{background};color:{foreground};padding:6px;"
            f"border:1px solid {OBSTRUCTION_COLOR if warning else background};border-radius:4px;}}"
            f"QPlainTextEdit#evidence_text QScrollBar:vertical {{background:{background};width:10px;margin:3px 1px;}}"
            f"QPlainTextEdit#evidence_text QScrollBar::handle:vertical {{background:{thumb};min-height:24px;border-radius:4px;}}"
            "QPlainTextEdit#evidence_text QScrollBar::add-line:vertical,"
            "QPlainTextEdit#evidence_text QScrollBar::sub-line:vertical {height:0px;border:none;background:transparent;}"
            "QPlainTextEdit#evidence_text QScrollBar::up-arrow:vertical,"
            "QPlainTextEdit#evidence_text QScrollBar::down-arrow:vertical {width:0px;height:0px;background:transparent;}"
            "QPlainTextEdit#evidence_text QScrollBar::add-page:vertical,"
            "QPlainTextEdit#evidence_text QScrollBar::sub-page:vertical {background:transparent;}"
        )


class EvidenceSelectionTable(QtWidgets.QTableWidget):
    """A second plain click hides a viewed ligand; modifiers retain Qt semantics."""

    def mousePressEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        self._hiding_row = bool(
            event.button() == QtCore.Qt.MouseButton.LeftButton
            and event.modifiers() == QtCore.Qt.KeyboardModifier.NoModifier
            and index.isValid() and self.selectionModel().isRowSelected(index.row())
        )
        if self._hiding_row:
            self.selectionModel().select(index,
                QtCore.QItemSelectionModel.SelectionFlag.Deselect
                | QtCore.QItemSelectionModel.SelectionFlag.Rows)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if getattr(self, '_hiding_row', False):
            self._hiding_row = False
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PocketEvidencePanel(QtWidgets.QScrollArea):
    ligandRequested = QtCore.pyqtSignal(str)
    ligandsRequested = QtCore.pyqtSignal(list)
    selectionChanged = QtCore.pyqtSignal(list)
    interactionsRequested = QtCore.pyqtSignal(dict)
    residuesRequested = QtCore.pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pocket_evidence_panel")
        self.setWidgetResizable(True)
        # Reserve the gutter even when one candidate has less evidence. A
        # disappearing scrollbar changes wrapping and propagates layout hints.
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        content = QtWidgets.QWidget()
        self.setWidget(content)
        layout = QtWidgets.QVBoxLayout(content)
        layout.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetMinimumSize)
        self.content_layout = layout
        self.evidence_header = QtWidgets.QWidget()
        header_layout = QtWidgets.QHBoxLayout(self.evidence_header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        self.evidence_symbol = QtWidgets.QLabel()
        self.evidence_symbol.setFixedSize(20, 20)
        ratio = self.devicePixelRatioF()
        ring = QtGui.QPixmap(round(20 * ratio), round(20 * ratio))
        ring.setDevicePixelRatio(ratio)
        ring.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(ring)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtGui.QPen(QtGui.QColor(LIGAND_EVIDENCE_COLOR), 2.5))
        painter.drawEllipse(QtCore.QRectF(3, 3, 14, 14))
        painter.end()
        self.evidence_symbol.setPixmap(ring)
        self.evidence_title = QtWidgets.QLabel("Ligand evidence")
        title_font = self.evidence_title.font()
        title_font.setBold(True)
        self.evidence_title.setFont(title_font)
        self.evidence_title.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
        header_layout.addWidget(self.evidence_symbol)
        header_layout.addWidget(self.evidence_title, 1)
        self.evidence_header.setFixedHeight(max(20, self.evidence_title.fontMetrics().lineSpacing()))
        self.evidence_header.setToolTip(
            "The green ring in the graph marks retained input-ligand or related deposited-ligand evidence. "
            "The table distinguishes the input-structure ligand from observations in related protein structures, "
            "not newly docked poses from this run. Input coordinates alone do not establish experimental validation. "
            "This evidence does not approve a docking region."
        )
        self.heading = QtWidgets.QLabel("Select a docking-box candidate to inspect its evidence.")
        self.heading.setWordWrap(True)
        self.heading.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
        self.heading.setFixedHeight(self.heading.fontMetrics().lineSpacing() * 2)
        self.evidence_summary = QtWidgets.QFrame()
        self.evidence_summary.setObjectName("ligand_evidence_summary")
        self.evidence_summary.setStyleSheet(
            f"QFrame#ligand_evidence_summary {{background:#effaf4;border:1px solid {LIGAND_EVIDENCE_COLOR};border-radius:4px;}}"
            "QFrame#ligand_evidence_summary QLabel {color:#1d3b2a;background:transparent;border:none;}"
        )
        summary_layout = QtWidgets.QVBoxLayout(self.evidence_summary)
        summary_layout.setContentsMargins(6, 6, 6, 6)
        self.lookup_status = ExplanationLabel('', 'Public PDB lookup coverage', '')
        self.lookup_status.setWordWrap(True)
        self.lookup_status.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Minimum)
        self.lookup_status.setMinimumHeight(self.lookup_status.fontMetrics().lineSpacing() * 2 + 12)
        self.lookup_status.hide()
        layout.addWidget(self.lookup_status)
        self.preparation_issues = QtWidgets.QPlainTextEdit()
        self.preparation_issues.setObjectName('box_receptor_preparation_issues')
        self.preparation_issues.setReadOnly(True)
        self.preparation_issues.setFixedHeight(self.fontMetrics().lineSpacing() * 5 + 16)
        self.preparation_issues.hide()
        layout.addWidget(self.preparation_issues)
        summary_layout.setSpacing(4)
        summary_layout.addWidget(self.evidence_header)
        summary_layout.addWidget(self.heading)
        self.evidence_summary.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
        self.evidence_summary.setFixedHeight(self.evidence_header.height() + self.heading.height() + 16)
        self.warning = EvidenceText()
        self.warning.setReadOnly(True)
        self.warning.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.warning.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
            | QtCore.Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.warning.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.warning.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
        self.warning.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.warning.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.warning.set_evidence_style(warning=True)
        # A text viewport does not export QLabel's text-dependent height-for-
        # width to the outer dock. Only its contents scroll, never the panels.
        self.warning_scroll = self.warning
        self.warning_scroll.setFixedHeight(self.warning.fontMetrics().lineSpacing() * 3 + 16)
        self._embedded_presentation = False
        self._obstructing_residues = []
        self._residue_highlighted = False
        self._guide_window = None
        self._obstruction_details_window = None
        self._conformation = {}
        self.highlight_obstruction_button = QtWidgets.QPushButton("Highlight obstructing residues")
        self.highlight_obstruction_button.setObjectName("highlight_evidence_residues_button")
        self.highlight_obstruction_button.setCheckable(True)
        self.highlight_obstruction_button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
        self.highlight_obstruction_button.setToolTip(
            "Click to show the recorded residue(s); click again to remove this highlight. "
            "Keeps camera and colors unchanged; does not change docking inputs. "
            "This warning identifies possible obstruction, not every rotamer change."
        )
        self.highlight_obstruction_button.clicked.connect(self._request_residues)
        # Reserve a stable row so P1/P2 navigation cannot move the evidence
        # table when only one candidate has a residue-highlight action.
        self.highlight_row = QtWidgets.QWidget()
        highlight_layout = QtWidgets.QVBoxLayout(self.highlight_row)
        highlight_layout.setContentsMargins(0, 0, 0, 0)
        highlight_layout.setSpacing(4)
        highlight_layout.addWidget(self.highlight_obstruction_button)
        self.guide_button = QtWidgets.QPushButton("Guide…")
        self.guide_button.setToolTip("Walk through pocket, ligand and residue evidence review")
        self.guide_button.clicked.connect(self.show_review_guide)
        help_row = QtWidgets.QHBoxLayout()
        help_row.addStretch()
        self.obstruction_details_button = QtWidgets.QPushButton("Details…")
        self.obstruction_details_button.setToolTip("How the obstruction rule works and what this candidate's evidence shows")
        self.obstruction_details_button.clicked.connect(self.show_obstruction_details)
        help_row.addWidget(self.obstruction_details_button)
        help_row.addWidget(self.guide_button)
        highlight_layout.addLayout(help_row)
        self.highlight_row.setFixedHeight(self.highlight_obstruction_button.sizeHint().height()
                                         + self.guide_button.sizeHint().height() + 4)
        self.highlight_row.hide()
        self.highlight_obstruction_button.hide()
        self.table = EvidenceSelectionTable(0, 6)
        self.table.setHorizontalHeaderLabels(("Class", "PDB", "Ligand", "Cα RMSD (Å)", "Identity", "Coverage"))
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        # Column geometry belongs to the panel, not the selected candidate's
        # row contents. Empty evidence must not pull headings/text leftwards.
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Fixed)
        metrics = self.table.fontMetrics()
        for column, sample in enumerate((
            "close structural homolog", "2R8N", "Ligand", "Cα RMSD (Å)", "Identity", "Coverage",
        )):
            self.table.setColumnWidth(column, metrics.horizontalAdvance(sample) + 24)
        self.note = ExplanationLabel(
            'Double-click an observation to view its ligand. Viewing does not approve a region.',
            'Viewing experimental ligand evidence',
            "Double-click an observation to show its aligned deposited ligand in PyMOL. "
            "Experimental correspondence supports a decision; it does not approve a box."
        )
        self.note.setWordWrap(True)
        self.note.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
        self.compare_button = QtWidgets.QPushButton("Show selected observations in PyMOL")
        self.compare_button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
        self.compare_button.setEnabled(False)
        self.compare_button.clicked.connect(self._request_selected_ligands)
        self.render_2d_button = QtWidgets.QPushButton("Render 2D interactions")
        self.render_2d_button.setEnabled(False)
        self.render_2d_button.setToolTip("Calculate interactions in the original deposited structure using retained local chemistry.")
        self.render_2d_button.clicked.connect(self._request_interactions)
        layout.addWidget(self.warning_scroll)
        layout.addWidget(self.highlight_row)
        layout.addWidget(self.evidence_summary)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.compare_button)
        layout.addWidget(self.render_2d_button)
        layout.addWidget(self.note)
        self.table.itemDoubleClicked.connect(self._request_ligand)
        self.table.itemSelectionChanged.connect(self._selection_changed)

    def set_viewer_presentation(self, *, embedded: bool) -> None:
        """Live selection needs no load button; keep it for the companion fallback."""
        self._embedded_presentation = embedded
        self.compare_button.setVisible(not embedded)
        self.highlight_row.setVisible(embedded)
        self._update_residue_action()
        if embedded:
            self.note.setText(
                "Click a ligand to show it; click again to hide it. Ctrl/Cmd-click selects several. Viewing is not approval."
            )
        else:
            self.note.setText(
                "Double-click an observation to view its ligand. Viewing does not approve a region."
            )
            self.compare_button.setText("Show selected observations in PyMOL")

    def set_candidate(self, candidate: dict | None) -> None:
        fingerprint = json.dumps(candidate, sort_keys=True)
        if fingerprint == getattr(self, "_candidate_fingerprint", None):
            return
        # Replace a candidate as one paint transaction, not a sequence of
        # empty table, new text, resized columns, and filled table frames.
        self.setUpdatesEnabled(False)
        try:
            self._render_candidate(candidate)
            self._candidate_fingerprint = fingerprint
        finally:
            self.setUpdatesEnabled(True)

    def set_lookup_status(self, record):
        fingerprint = json.dumps(record, sort_keys=True)
        if fingerprint == getattr(self, '_lookup_status_fingerprint', None):
            return
        self._lookup_status_fingerprint = fingerprint
        from ..services.pdb_lookup_status import lookup_notice
        text, warning = lookup_notice(record)
        summary = (
            'Local-only evidence: public PDB search is off.' if record.get('mode') == 'off' else
            'PDB lookup unavailable. Local work can continue; supporting evidence may be missing.'
            if record.get('status') in {'unavailable', 'failed'} else
            'PDB lookup incomplete: some structures could not be retrieved; evidence may be missing.'
            if (record.get('coverage') or {}).get('failed_entry_count') else
            'PDB search completed: no qualifying observations found; this is not proof of absence.'
            if text else '')
        detail = record.get('detail') or record.get('error') or ''
        self.lookup_status.set_content(summary, text + ('\n\nDetails: ' + str(detail) if detail else ''))
        self.lookup_status.setVisible(bool(text))
        self.lookup_status.setToolTip(text + ('\n\nDetails: ' + str(detail) if detail else ''))
        self.lookup_status.setStyleSheet(
            'QLabel {background:#fff1b8;color:#392600;border:1px solid #a85b00;padding:5px;border-radius:4px;}'
            if warning else
            'QLabel {background:#edf5ff;color:#173a5e;border:1px solid #8bb7e8;padding:5px;border-radius:4px;}'
        )

    def _render_candidate(self, candidate: dict | None) -> None:
        scroll_position = self.verticalScrollBar().value()
        previous_paths = self._selected_paths()
        blocker = QtCore.QSignalBlocker(self.table)
        evidence = (candidate or {}).get("evidence", {})
        issues = evidence.get('receptor_model_review') or evidence.get('receptor_preparation_review') or {}
        lines = [issues['warning']] if issues.get('warning') else []
        reference_review = evidence.get('reviewed_incomplete_reference') or {}
        if reference_review:
            lines.insert(0, reference_review['warning'])
        if issues.get('category'):
            lines.append(issues['category'])
        if issues.get('scientific_concern'):
            lines.append(issues['scientific_concern'])
        for row in issues.get('residues', []):
            distance = row['minimum_distance_to_box_angstrom']
            location = 'inside this box' if row['inside_box'] else f'{distance:.2f} Å from this box'
            lines.append(f"{row['residue']} {row['chain']}:{row['number']} — {location}")
        if issues and not issues.get('residues'):
            lines.append('Distances to this box are not retained; the model-change warning still applies.'
                         if evidence.get('receptor_model_review') else
                         'No backend-named residue could be located in the deposited coordinates; inspect the retained preparation logs.')
        self.preparation_issues.setPlainText('\n'.join(lines))
        self.preparation_issues.setVisible(bool(issues or reference_review))
        experimental = evidence.get("experimental_ligand_evidence") or {}
        local = evidence.get('input_ligand_evidence') or {}
        observations = list(local.get('observations') or []) + list(experimental.get("observations") or [])
        label = (candidate or {}).get("label") or (candidate or {}).get("id") or "No candidate"
        classes = experimental.get("evidence_class_counts") or {}
        self.heading.setText(
            f"{label}: {local.get('observation_count', 0)} input ligand · "
            f"{experimental.get('observation_count', 0)} related observations" if local else
            f"{label}: {experimental.get('observation_count', 0)} observations · "
            f"{experimental.get('pdb_entry_count', 0)} PDB entries")
        self.heading.setToolTip(self.heading.text() +
            f" · exact {classes.get('exact_sequence_match', 0)} · homolog {classes.get('close_structural_homolog', 0)}")
        self.note.set_content(self.note.summary_text,
            self.evidence_header.toolTip() + '\n\n' + self.heading.toolTip() +
            ('\n\nInput ligand: all retained heavy atoms must fit this box (0.25 Å boundary tolerance). '
             'This is evidence from the loaded structure, not independent validation. '
             + str(local.get('detail') or '') if local else '') +
            '\n\nSelecting observations updates the 3D view; deselecting hides them. '
            'Experimental correspondence supports a decision; it does not approve a docking region.')
        if evidence.get('site_group'):
            from ..pocket_sites import site_group_summary
            self.heading.setToolTip(self.heading.toolTip() + '\n' + site_group_summary(evidence['site_group']))
            self.note.set_content(self.note.summary_text,
                                  self.note.details_text + '\n\n' + site_group_summary(evidence['site_group']))
        conformation = evidence.get("conformational_site_evidence") or {}
        self._conformation = conformation
        self.obstruction_details_button.setEnabled(bool(conformation))
        if self._obstruction_details_window is not None:
            self._obstruction_details_window.close()
        self._obstructing_residues = conformation.get("occluding_residues") or []
        self._residue_highlighted = False
        self._update_residue_action()
        self.warning.set_conformation_text(conformation)
        self.warning_scroll.verticalScrollBar().setValue(0)
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
                cell.setData(QtCore.Qt.ItemDataRole.UserRole + 1, item)
                self.table.setItem(row, column, cell)
        del blocker
        self.compare_button.setEnabled(bool(self._selected_paths()))
        self._update_2d_action()
        if previous_paths != self._selected_paths():
            self._selection_changed()
        self.verticalScrollBar().setValue(scroll_position)

    @staticmethod
    def _number(value, decimals):
        return f"{value:.{decimals}f}" if isinstance(value, (int, float)) else "—"

    def _update_residue_action(self):
        available = bool(self._embedded_presentation and self._obstructing_residues)
        self.highlight_obstruction_button.setVisible(available)
        self.highlight_obstruction_button.setEnabled(available)
        labels = ", ".join(f"{r.get('name', '')}{r.get('number', '')}{r.get('chain', '')}"
                           for r in self._obstructing_residues)
        self.highlight_obstruction_button.setChecked(available and self._residue_highlighted)
        prefix = "Hide " if self._residue_highlighted else "Highlight "
        self.highlight_obstruction_button.setText(
            f"{prefix}{labels}" if labels and len(labels) <= 35 else
            ("Hide residue highlight" if self._residue_highlighted else "Highlight obstructing residues")
        )

    def sync_residue_highlight(self, adapter):
        method = getattr(adapter, "is_obstruction_highlighted", None)
        self._residue_highlighted = bool(callable(method) and method(self._obstructing_residues) is True)
        self._update_residue_action()

    def show_review_guide(self):
        if self._guide_window is not None:
            self._guide_window.show()
            self._guide_window.raise_()
            self._guide_window.activateWindow()
            return
        dialog = QtWidgets.QDialog(self.window())
        dialog.setWindowTitle("Structural evidence review — walkthrough")
        dialog.resize(620, 520)
        layout = QtWidgets.QVBoxLayout(dialog)
        content = QtWidgets.QTextBrowser()
        source = ("Return to Docking Universal to select one evidence observation and use "
                  "<b>Render 2D interactions</b>." if getattr(self, "_detached_guide", False) else
                  "Select one evidence observation, then use <b>Render 2D interactions</b>.")
        labels = html.escape(", ".join(f"{r.get('name', '')}{r.get('number', '')}{r.get('chain', '')}"
                                      for r in self._obstructing_residues))
        content.setHtml(
            "<h2>Review a docking region</h2><p>This guide is optional. Viewing does not approve a region.</p>"
            "<h3>1. Choose a candidate</h3><p>Use the pocket graph or table in the main window, or "
            "the Docking region selector in full PyMOL. A detector score ranks predicted pockets; "
            "it is not binding affinity. A green ring marks deposited-ligand evidence.</p>"
            "<h3>2. Overlay ligand evidence</h3><p>Select an observation in the PDB/ligand table to "
            "show its aligned ligand in the current protein. Ctrl-click (Cmd-click on Mac) selects "
            "several; deselect a row to hide that ligand. These are experimental observations, "
            "not newly docked predictions.</p>"
            "<h3>3. Inspect the reported side chain</h3><p>When available, click <b>Highlight "
            + (labels or "the reported residue") + "</b> to show its side chain as sticks, without atom-selection markers. "
            "Click again to remove this highlight. The camera and protein colors stay unchanged. "
            "ASP30A means aspartate (ASP), residue 30, chain A. A possible obstruction is a "
            "recorded overlap with an aligned ligand—not proof of flexibility or an instruction "
            "to change the receptor. This box reports <b>protein side-chain obstruction</b>, "
            "not every changed protein rotamer and not ligand rotamers. The recorded geometric "
            "rule requires a current minimum side-chain–ligand distance below 2.0 Å and at "
            "least 0.5 Å more clearance in the aligned ligand-bound structure. Other side-chain "
            "differences are recorded separately in the conformational-evidence study file. "
            "These geometric comparisons are evidence, not proof that flexible docking is needed.</p>"
            "<h3>4. Read the interaction diagram</h3><p>" + source +
            " The diagram describes calculated <b>protein–ligand contacts in the original "
            "deposited structure</b>, not all residue–residue interactions or proven affinity. "
            "Use Fit or explicit zoom for readability. Diagram clicks currently highlight "
            "the ligand; residue-label click toggles are not implemented yet.</p>"
            "<h3>5. Make the region decision</h3><p>Return to the main window and explicitly "
            "approve the selected docking region(s), with an optional decision note. Selecting "
            "ligands, highlighting residues, or editing the exploratory PyMOL view does not "
            "alter pipeline inputs or grant approval. Static figures are included in the "
            "generated reports; interactive structure and interaction review stay in the workspace.</p>"
        )
        layout.addWidget(content, 1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(dialog.close)
        layout.addWidget(close, 0, QtCore.Qt.AlignmentFlag.AlignRight)
        self._guide_window = dialog
        dialog.show()

    def _request_residues(self):
        if self._embedded_presentation and self._obstructing_residues:
            self.residuesRequested.emit(list(self._obstructing_residues))

    def show_obstruction_details(self):
        if self._obstruction_details_window is not None:
            self._obstruction_details_window.show()
            self._obstruction_details_window.raise_()
            return
        dialog = QtWidgets.QDialog(self.window())
        dialog.setWindowTitle("Possible ligand obstruction — evidence and limits")
        dialog.resize(670, 470)
        layout = QtWidgets.QVBoxLayout(dialog)
        text = QtWidgets.QTextBrowser()
        summary, explanation = conformation_summary(self._conformation)
        paragraphs = [
            f"<h3>{html.escape(summary)}</h3><p>{html.escape(explanation)}</p>",
            "<h3>What triggers the warning?</h3><p>The comparison uses the current receptor "
            "and an aligned, experimentally ligand-bound structure. A residue is flagged when "
            "its minimum side-chain–ligand distance is <b>below 2.0 Å</b> in the current receptor "
            "and the corresponding source side chain has <b>at least 0.5 Å more clearance</b>.</p>",
            "<p>This is a geometric screening rule, not an energy calculation or a complete "
            "van der Waals clash analysis. It does not list all changed protein rotamers, "
            "analyse ligand rotamers, or establish that flexible docking is required. Missing "
            "comparisons mean <b>not evaluated</b>, not absence of conformational differences.</p>",
            "<h3>Evidence for this region</h3>",
        ]
        rows = []
        for observation in self._conformation.get("observations", []):
            residue = observation.get("residue") or {}
            label = f"{residue.get('name', '?')}{residue.get('number', '?')}{residue.get('chain', '')}"
            for ligand in observation.get("ligands", []):
                if not ligand.get("consistent_with_side_chain_occlusion"):
                    continue
                current = ligand.get("current_side_chain_minimum_distance_angstrom")
                bound = ligand.get("bound_side_chain_minimum_distance_angstrom")
                rows.append("<li>" + html.escape(
                    f"{label} · {ligand.get('source_ligand_id') or observation.get('entry', '?')}: "
                    f"current {current if current is not None else 'not recorded'} Å; "
                    f"source {bound if bound is not None else 'not recorded'} Å") + "</li>")
        paragraphs.append("<ul>" + "".join(rows) + "</ul>" if rows else
                          "<p>No per-ligand obstruction distances are recorded for this region.</p>")
        paragraphs.append("<p>Other conformational differences are retained in the separate "
                          "<b>conformational evidence</b> study file. They include available side-chain "
                          "angle/displacement comparisons and backbone displacement. Viewing this "
                          "information does not change the receptor or approve a region.</p>")
        text.setHtml("".join(paragraphs))
        layout.addWidget(text)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(dialog.close)
        layout.addWidget(close, 0, QtCore.Qt.AlignmentFlag.AlignRight)
        self._obstruction_details_window = dialog
        dialog.finished.connect(lambda: setattr(self, "_obstruction_details_window", None))
        dialog.finished.connect(dialog.deleteLater)
        dialog.show()

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
        self._update_2d_action()
        self.selectionChanged.emit(paths)

    def selected_observation(self):
        rows = self.table.selectionModel().selectedRows()
        if len(rows) != 1:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.data(QtCore.Qt.ItemDataRole.UserRole + 1) if item else None

    def _update_2d_action(self):
        from ..services.evidence_interactions import evidence_inputs
        self.render_2d_button.setText(
            "Rendering 2D interactions…" if getattr(self, "rendering_2d", False)
            else "Render 2D interactions"
        )
        if (self.selected_observation() or {}).get('source') == 'input_structure':
            self.render_2d_button.setEnabled(False)
            self.render_2d_button.setToolTip('This input ligand can be shown in 3D. Its exact chemistry is not linked to the deposited-interaction renderer; use the molecule inspector for its 2D drawing.')
            return
        try:
            evidence_inputs(self.selected_observation() or {})
        except (ValueError, OSError) as exc:
            self.render_2d_button.setEnabled(False)
            self.render_2d_button.setToolTip(str(exc))
        else:
            self.render_2d_button.setEnabled(not getattr(self, "rendering_2d", False))
            self.render_2d_button.setToolTip("Interactions from the original deposited protein and ligand; calculated locally.")

    def _request_interactions(self):
        observation = self.selected_observation()
        if observation:
            self.interactionsRequested.emit(observation)
