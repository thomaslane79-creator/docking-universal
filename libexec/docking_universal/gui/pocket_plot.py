"""Clickable pocket scores from retained detector output."""

import csv
import math
import re
from pathlib import Path

from .qt import QtCore, QtGui, QtWidgets
from ..pocket_metadata import POCKET_COLORS, candidate_pocket_number, candidate_display_label
from .pocket_evidence import (
    conformation_summary, has_obstruction_warning,
    LIGAND_EVIDENCE_COLOR, OBSTRUCTION_COLOR, OBSTRUCTION_BACKGROUND,
)

REMOVED_COMPONENT_COLOR = '#6e2c91'
REMOVED_COMPONENT_BACKGROUND = '#f3e8fa'
SUPPORTING_COMPONENT_COLOR = '#66727d'


def _potential_ligand(observation, include_fragments=False):
    """Keep unknown roles visible; known supporting components are secondary."""
    from ..services.molecule_inspection import is_supporting_component_observation, ligand_display_role
    return (not is_supporting_component_observation(observation) and
            (include_fragments or ligand_display_role(observation) != 'fragment_screening'))


class PocketScorePlot(QtWidgets.QWidget):
    candidateActivated = QtCore.pyqtSignal(str)
    layoutHeightChanged = QtCore.pyqtSignal(int)
    COLORS = POCKET_COLORS

    def __init__(self, parent=None, *, top_count=None, include_experimental=True, include_selected=True):
        super().__init__(parent)
        self.setFixedHeight(288)
        self.setMouseTracking(True)
        self.score_sources = {}
        self.display_labels = {}
        self.points = []
        self.all_points = []
        self.top_count = top_count
        self.include_experimental = include_experimental
        self.include_selected = include_selected
        self.added_site_ids = set()
        self.selected = None
        self.detector = "Pocket"
        self.evidence_counts = {}
        self.evidence_sources = {}
        self.conflicts = set()
        self.conformations = {}
        self.removed_components = {}
        self.experimental_sites = set()
        self.supporting_counts = {}
        self.input_ligand_sites = set()

    def set_study(self, state, candidates=None):
        root = state.workflow_data.get("preparation_root") or state.workflow_data.get('site_exploration_root')
        scores = {}
        if root:
            try:
                cavity = Path(root) / "cavity"
                records = cavity / "selected_pocket_records.txt"
                # Generated box numbers enumerate retained pockets, not the
                # detector's original ranks. Extra ligand-expanded boxes have
                # no independent detector score.
                if records.is_file():
                    for index, line in enumerate(records.read_text().splitlines(), 1):
                        fields = line.split("|")
                        value = float(fields[0])
                        if math.isfinite(value):
                            match = re.search(r"pocket(\d+)_atm\.pdb", fields[1] if len(fields) > 1 else "")
                            scores[f"P{match.group(1) if match else index}"] = value
                else:
                    with (cavity / "pocket_selection_diagnostics.tsv").open() as handle:
                        for row in csv.DictReader(handle, delimiter="\t"):
                            match = re.search(r"pocket(\d+)_atm", row.get("pocket_file", ""))
                            if match:
                                value = float(row.get("rank_score") or row.get("score"))
                                if math.isfinite(value):
                                    scores[f"P{match.group(1)}"] = value
            except (OSError, ValueError, TypeError):
                pass
        self.score_sources = {}
        self.display_labels = {}
        self.points = []
        self.evidence_counts = {}
        self.evidence_sources = {}
        self.conflicts = set()
        self.conformations = {}
        self.removed_components = {}
        self.experimental_sites = set()
        self.supporting_counts = {}
        self.input_ligand_sites = set()
        for index, candidate in enumerate(candidates if candidates is not None else state.workflow_data.get("pocket_candidates", [])):
            if candidates is None:
                if hasattr(state, 'artifacts'):
                    from ..services.preparation_site_issues import candidate_with_model_change_review
                    candidate = candidate_with_model_change_review(state, candidate)
                else:
                    from ..services.pocket_review import candidate_with_input_ligand_evidence
                    candidate = candidate_with_input_ligand_evidence(state, candidate)
            identity = str(candidate["id"])
            self.display_labels[identity] = candidate_display_label(candidate)
            evidence = candidate.get("evidence", {})
            group = evidence.get('site_group') or evidence.get('site_group_presentation')
            from ..pocket_sites import site_prediction_sources
            predictions = site_prediction_sources(group)
            value = scores.get(identity, evidence.get("score"))
            if value is None and predictions and len({p['detector'] for p in predictions}) == 1:
                ranks = {str(m.get('id')): m.get('rank') for m in (group or {}).get('members', [])}
                # The displayed marker follows the best original detector
                # rank; its label and tooltip retain the source box identity.
                def source_rank(prediction):
                    rank = ranks.get(str(prediction['source_id']))
                    return rank if isinstance(rank, (int, float)) else float('inf')
                prediction = min(predictions, key=source_rank)
                value = prediction['score']
                self.score_sources[identity] = prediction['source_id']
                self.detector = {'p2rank': 'P2Rank', 'fpocket': 'fpocket'}.get(prediction['detector'], 'Pocket')
            try:
                value = float(value)
            except (ValueError, TypeError):
                value = None
            if value is not None and not math.isfinite(value):
                value = None
            if evidence.get("detector"):
                self.detector = {"p2rank": "P2Rank", "fpocket": "fpocket"}.get(evidence.get("detector"), "Pocket")
            experimental = evidence.get("experimental_ligand_evidence") or {}
            local = evidence.get('input_ligand_evidence') or {}
            # This marker refers only to the exact selected bound ligand, not
            # any other ligand observed in this or a related structure.
            if (local.get('status') == 'verified' and local.get('all_heavy_atoms_inside')
                    and local.get('observation_count')):
                self.input_ligand_sites.add(identity)
            local_count = int(local.get('observation_count') or 0)
            related_count = int(experimental.get('observation_count') or 0)
            primary_observations = experimental.get('observations') or []
            observations = list(primary_observations) + list((experimental.get('supporting_components') or {}).get('observations') or [])
            local_observations = list(local.get('observations') or [])
            if getattr(self, 'include_additional_input_ligands', False):
                local_observations += list(local.get('additional_observations') or [])
            # Count-only legacy records have an unknown role, so retain them as
            # possible evidence rather than silently suppressing them.
            include_fragments = getattr(self, 'include_fragment_screening', False)
            priority_related = sum(1 for row in observations if _potential_ligand(row, include_fragments))
            unknown_count = max(0, related_count - len(primary_observations))
            priority_local = sum(1 for row in local_observations if _potential_ligand(row))
            # A merged site's ligand can belong to a constituent rather than
            # the representative box. Include only retained, verified ligand
            # coordinates and avoid double-counting observations already shown.
            known_ids = {str(row.get('source_ligand_id')) for row in observations + local_observations
                         if row.get('source_ligand_id')}
            grouped_count = 0
            for ligand in (group or {}).get('ligands') or []:
                observation = ligand.get('observation') or {}
                source_id = str(observation.get('source_ligand_id') or '')
                if (source_id and source_id in known_ids) or not _potential_ligand(observation, include_fragments):
                    continue
                path, expected = ligand.get('path'), ligand.get('sha256')
                if not path or not expected:
                    continue
                try:
                    import hashlib
                    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
                        continue
                except OSError:
                    continue
                grouped_count += 1
                if source_id:
                    known_ids.add(source_id)
            self.evidence_counts[identity] = priority_local + max(0, local_count - len(local_observations)) + priority_related + unknown_count + grouped_count
            from ..services.molecule_inspection import is_supporting_component_observation
            self.supporting_counts[identity] = sum(1 for row in observations + local_observations
                                                  if is_supporting_component_observation(row))
            self.evidence_sources[identity] = (f'{priority_local} possible input ligand · '
                f'{priority_related + unknown_count} possible related-PDB observations')
            if grouped_count:
                self.evidence_sources[identity] += f'\n{grouped_count} retained ligand(s) from merged site sources.'
            if self.supporting_counts[identity]:
                self.evidence_sources[identity] += f"\n{self.supporting_counts[identity]} known supporting-component observations (role not established)."
            group = evidence.get('site_group') or evidence.get('site_group_presentation')
            if group:
                from ..pocket_sites import site_group_summary
                self.evidence_sources[identity] += '\n' + site_group_summary(group)
            from ..services.molecule_inspection import possible_ligand_conformation
            self.conformations[identity] = possible_ligand_conformation(evidence.get("conformational_site_evidence") or {})
            group_members = (group or {}).get('members', [])
            if (self.evidence_counts[identity]
                    or (not observations and self.conformations[identity].get('observation_count'))
                    or any(any(_potential_ligand(row, include_fragments) for row in
                               (((member.get('evidence') or {}).get('experimental_ligand_evidence') or {}).get('observations') or []))
                           for member in group_members)):
                self.experimental_sites.add(identity)
            if has_obstruction_warning(self.conformations[identity]):
                self.conflicts.add(identity)
            review = evidence.get('receptor_model_review') or {}
            removed = [r for r in review.get('residues', []) if r.get('removed') and r.get('inside_box')]
            if removed:
                self.removed_components[identity] = [
                    f"{r['residue']} {r['chain'] or '(blank)'}:{r['number']}" for r in removed]
            pocket_number = candidate_pocket_number(candidate)
            color = self.COLORS[(pocket_number - 1) % len(self.COLORS)] if pocket_number else '#66727d'
            self.points.append((identity, value, color))
        # Rank the displayed points by the detector score; unscored ligand
        # evidence follows them. The stable IDs continue to drive selection.
        self.points.sort(key=lambda point: (point[1] is None, -point[1] if point[1] is not None else 0))
        self.all_points = list(self.points)
        self._apply_display_filter()

    def _apply_display_filter(self):
        if self.top_count is None:
            self.points = list(self.all_points)
        else:
            top = {point[0] for point in self.all_points[:self.top_count]}
            self.points = [point for point in self.all_points if point[0] in top
                           or (self.include_experimental and point[0] in self.experimental_sites)
                           or point[0] in self.added_site_ids
                           or (self.include_selected and point[0] == self.selected)]
        # The compact view adapts its key to the available width. The full
        # graph retains horizontal scrolling for large numbers of sites.
        self.setMinimumWidth(0 if self.top_count is not None else max(340, 230 + len(self.points) * 65))
        self._adjust_plot_height()
        self.setVisible(bool(self.points))
        self.update()

    def set_selected(self, identity):
        self.selected = str(identity) if identity is not None else None
        self._apply_display_filter()

    def copy_presentation_from(self, other):
        """Use the same resolved evidence and scores without re-reading scientific data."""
        self.detector = other.detector
        self.all_points = list(other.all_points)
        for name in ('score_sources', 'display_labels', 'evidence_counts', 'evidence_sources', 'conformations', 'removed_components', 'supporting_counts'):
            setattr(self, name, dict(getattr(other, name)))
        self.conflicts = set(other.conflicts)
        self.experimental_sites = set(other.experimental_sites)
        self.input_ligand_sites = set(other.input_ligand_sites)
        self.set_selected(other.selected)

    def positions(self):
        if not self.points:
            return []
        scores = [point[1] for point in self.points if point[1] is not None]
        lo = min([0, *scores])
        hi = max([0, *scores])
        span = max(hi - lo, 0.01)
        return [QtCore.QPointF(
            40 + (index + .5) * self._plot_width() / len(self.points),
            184 - (point[1] - lo) / span * 94
            if point[1] is not None else 197,
        ) for index, point in enumerate(self.points)]

    def _plot_width(self):
        # Don't spread a small number of sites across a very wide window.
        space = self.width() - (55 if self._legend_below() else 230)
        return max(1, min(max(1, len(self.points)) * 82, space))

    def _legend_below(self):
        return self.top_count is not None and self.width() < 230 + max(1, len(self.points)) * 65

    def _legend_columns(self):
        font = QtGui.QFont(self.font())
        font.setPointSizeF(10)
        metrics = QtGui.QFontMetricsF(font)
        widest = max(metrics.horizontalAdvance(label) for label in (
            'Possible ligand', 'Selected input ligand', 'Possible obstruction',
            'Removed in box', 'Supporting component')) + 27
        return 2 if self.width() >= 24 + 2 * widest else 1

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor("white"))
        painter.setPen(QtGui.QColor("#222222"))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(13)
        painter.setFont(font)
        painter.drawText(12, 20, "Choose a docking region")
        font.setBold(False)
        font.setPointSize(10)
        painter.setFont(font)
        painter.drawText(12, 38, "Click a site · unscored sites are below the axis")
        painter.drawLine(40, 60, 40, 184)
        painter.drawLine(QtCore.QPointF(40, 184), QtCore.QPointF(40 + self._plot_width(), 184))
        painter.save()
        painter.translate(14, (184 + 60) / 2)
        painter.rotate(-90)
        axis_font = painter.font()
        axis_font.setPointSizeF(15)
        painter.setFont(axis_font)
        axis_label = f"{self.detector} score"
        metrics = painter.fontMetrics()
        painter.drawText(
            int(-metrics.horizontalAdvance(axis_label) / 2),
            int(metrics.ascent() / 2),
            axis_label,
        )
        painter.restore()
        value_font = painter.font()
        value_font.setPointSizeF(12.5)
        painter.setFont(value_font)
        for point, position in zip(self.points, self.positions()):
            identity, score, color = point
            radius = 8 if identity == self.selected else 5
            painter.setPen(QtGui.QPen(QtGui.QColor("#222222"), 2 if identity == self.selected else 1))
            painter.setBrush(QtGui.QColor(color))
            if identity in self.input_ligand_sites:
                self._draw_input_ligand_marker(painter, position, color, radius + 3)
            else:
                painter.drawEllipse(position, radius, radius)
            if self.evidence_counts.get(identity):
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.setPen(QtGui.QPen(QtGui.QColor(LIGAND_EVIDENCE_COLOR), 2.5))
                painter.drawEllipse(position, 13, 13)
            elif self.supporting_counts.get(identity):
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.setPen(QtGui.QPen(QtGui.QColor(SUPPORTING_COMPONENT_COLOR), 2.5, QtCore.Qt.PenStyle.DashLine))
                painter.drawEllipse(position, 13, 13)
            painter.setPen(QtGui.QColor("#222222"))
            if score is not None:
                painter.drawText(QtCore.QRectF(position.x() - 48, position.y() - 35, 96, 20),
                                 QtCore.Qt.AlignmentFlag.AlignCenter,
                                 f"{score:.4g}")
            # Keep unscored points clear of their labels below the axis.
            label_top = 194 if score is not None else 210
            label = self.display_labels.get(identity, identity)
            painter.drawText(QtCore.QRectF(position.x() - 32, label_top, 64, 20),
                             QtCore.Qt.AlignmentFlag.AlignCenter, label)
            if identity in self.conflicts:
                self._draw_obstruction_marker(painter, self.obstruction_marker_rect(position))
            if identity in self.removed_components:
                self._draw_removed_component_marker(painter, self.removed_component_marker_rect(position))
        self._draw_legend(painter)

    def _adjust_plot_height(self):
        rows = math.ceil(5 / self._legend_columns()) if self._legend_below() else 0
        height = 250 + rows * 22 if rows else 235
        if self.height() != height:
            self.setFixedHeight(height)
            self.layoutHeightChanged.emit(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._adjust_plot_height()

    def _draw_legend(self, painter):
        """Place the key next to the compact, horizontally scrollable plot."""
        legend_font = painter.font()
        below = self._legend_below()
        legend_font.setPointSizeF(10 if below else 11.25)
        painter.setFont(legend_font)
        entries = [('ligand', 'Possible ligand'), ('input', 'Selected input ligand'),
                   ('obstruction', 'Possible obstruction'), ('removed', 'Removed in box'),
                   ('support', 'Supporting component')]
        x = 12 if below else 40 + self._plot_width() + 20
        painter.setPen(QtGui.QColor('#222222'))
        painter.drawText(QtCore.QPointF(x, 240 if below else 55), 'Key')
        columns = self._legend_columns() if below else 1
        rows = math.ceil(len(entries) / columns)
        for index, (kind, label) in enumerate(entries):
            item_x = x + (index // rows) * ((self.width() - 24) / columns) if below else x
            baseline = (260 + (index % rows) * 22) if below else 78 + index * 22
            center = QtCore.QPointF(item_x + 5, baseline - 5)
            if kind in ('ligand', 'support'):
                color = LIGAND_EVIDENCE_COLOR if kind == 'ligand' else SUPPORTING_COMPONENT_COLOR
                style = QtCore.Qt.PenStyle.SolidLine if kind == 'ligand' else QtCore.Qt.PenStyle.DashLine
                painter.setPen(QtGui.QPen(QtGui.QColor(color), 2, style))
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.drawEllipse(center, 5, 5)
            elif kind == 'input':
                self._draw_input_ligand_marker(painter, center, '#333333', 6)
            elif kind == 'obstruction':
                self._draw_obstruction_marker(painter, QtCore.QRectF(item_x - 2, baseline - 13, 14, 14))
            else:
                self._draw_removed_component_marker(painter, QtCore.QRectF(item_x - 1, baseline - 11, 12, 12))
            painter.setPen(QtGui.QColor('#222222'))
            painter.drawText(QtCore.QPointF(item_x + 19, baseline), label)

    @staticmethod
    def _draw_input_ligand_marker(painter, center, color, radius):
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor('#222222'), 1))
        painter.setBrush(QtGui.QColor(color))
        points = []
        for index in range(10):
            angle = -math.pi / 2 + index * math.pi / 5
            size = radius if index % 2 == 0 else radius * 0.43
            points.append(QtCore.QPointF(center.x() + size * math.cos(angle),
                                         center.y() + size * math.sin(angle)))
        painter.drawPolygon(QtGui.QPolygonF(points))
        painter.restore()

    @staticmethod
    def obstruction_marker_rect(position):
        return QtCore.QRectF(position.x() + 18, position.y() - 9, 18, 18)

    def removed_component_marker_rect(self, position):
        # Stack with the obstruction marker; flip above near the axis so the
        # warning cannot cover the candidate label or unscored area.
        top = position.y() + 12
        if top > 162:
            top = position.y() - 30
        return QtCore.QRectF(position.x() + 18, top, 18, 18)

    @staticmethod
    def _draw_removed_component_marker(painter, rect):
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor(REMOVED_COMPONENT_COLOR), 1.5))
        painter.setBrush(QtGui.QColor(REMOVED_COMPONENT_BACKGROUND))
        painter.drawRoundedRect(rect, 2, 2)
        font = painter.font()
        font.setBold(True)
        font.setPointSize(12 if rect.width() > 16 else 9)
        painter.setFont(font)
        painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, '−')
        painter.restore()

    @staticmethod
    def _draw_obstruction_marker(painter, rect):
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor(OBSTRUCTION_COLOR), 1.5))
        painter.setBrush(QtGui.QColor(OBSTRUCTION_BACKGROUND))
        painter.drawEllipse(rect)
        font = painter.font()
        font.setBold(True)
        font.setPointSize(12 if rect.width() > 16 else 11)
        painter.setFont(font)
        painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, "!")
        painter.restore()

    def _hit(self, position):
        for point, center in zip(self.points, self.positions()):
            label_top = 194 if point[1] is not None else 210
            label = QtCore.QRectF(center.x() - 32, label_top - 4, 64, 28)
            warning = point[0] in self.conflicts and self.obstruction_marker_rect(center).contains(position)
            removed = point[0] in self.removed_components and self.removed_component_marker_rect(center).contains(position)
            if (position - center).manhattanLength() <= 20 or label.contains(position) or warning or removed:
                return point
        return None

    def mousePressEvent(self, event):
        point = self._hit(event.position())
        if event.button() == QtCore.Qt.MouseButton.LeftButton and point:
            self.candidateActivated.emit(point[0])
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        point = self._hit(event.position())
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor if point else QtCore.Qt.CursorShape.ArrowCursor)
        if point:
            score = f"{self.detector} score {point[1]:.4g}" if point[1] is not None else "No independent detector score"
            if point[0] in self.score_sources:
                score += " from original box " + self.score_sources[point[0]] + "; not a score for the displayed box geometry"
            summary, explanation = conformation_summary(self.conformations.get(point[0], {}))
            removed = self.removed_components.get(point[0], [])
            removal_warning = ('\nRemoved from receptor and originally inside this box: ' + ', '.join(removed)
                + '. Docking will not include interactions with these components.' if removed else '')
            input_ligand = ('\nThe selected input ligand fits in this box (all heavy atoms, within 0.25 Å tolerance).'
                            if point[0] in self.input_ligand_sites else '')
            self.setToolTip(f"{self.display_labels.get(point[0], point[0])} · {score}\n"
                            f"{self.evidence_sources.get(point[0], '')}\n"
                            f"{summary}. {explanation}{input_ligand}{removal_warning}\n"
                            "Click to inspect in 3D. Evidence is not approval.")
        else:
            self.setToolTip("")
        super().mouseMoveEvent(event)
