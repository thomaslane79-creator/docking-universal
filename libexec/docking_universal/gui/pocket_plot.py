"""Clickable pocket scores from retained detector output."""

import csv
import math
import re
from pathlib import Path

from .qt import QtCore, QtGui, QtWidgets
from .pocket_evidence import (
    conformation_summary, has_obstruction_warning,
    LIGAND_EVIDENCE_COLOR, OBSTRUCTION_COLOR, OBSTRUCTION_BACKGROUND,
)


class PocketScorePlot(QtWidgets.QWidget):
    candidateActivated = QtCore.pyqtSignal(str)
    COLORS = ("#ff0000", "#0080ff", "#ffa600", "#ff00ff", "#00ffff", "#ff8000", "#8f5e99")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(270)
        self.setMouseTracking(True)
        self.points = []
        self.selected = None
        self.detector = "Pocket"
        self.evidence_counts = {}
        self.conflicts = set()
        self.conformations = {}

    def set_study(self, state):
        root = state.workflow_data.get("preparation_root")
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
        self.points = []
        self.evidence_counts = {}
        self.conflicts = set()
        self.conformations = {}
        for index, candidate in enumerate(state.workflow_data.get("pocket_candidates", [])):
            identity = str(candidate["id"])
            evidence = candidate.get("evidence", {})
            value = scores.get(identity, evidence.get("score"))
            try:
                value = float(value)
            except (ValueError, TypeError):
                value = None
            if value is not None and not math.isfinite(value):
                value = None
            if evidence.get("detector"):
                self.detector = {"p2rank": "P2Rank", "fpocket": "fpocket"}.get(evidence.get("detector"), "Pocket")
            experimental = evidence.get("experimental_ligand_evidence") or {}
            self.evidence_counts[identity] = int(experimental.get("observation_count") or 0)
            self.conformations[identity] = evidence.get("conformational_site_evidence") or {}
            if has_obstruction_warning(self.conformations[identity]):
                self.conflicts.add(identity)
            self.points.append((identity, value, self.COLORS[index % len(self.COLORS)]))
        self.setMinimumWidth(max(340, 70 + len(self.points) * 65))
        self.setVisible(bool(self.points))
        self.update()

    def positions(self):
        if not self.points:
            return []
        scores = [point[1] for point in self.points if point[1] is not None]
        lo = min([0, *scores])
        hi = max([0, *scores])
        span = max(hi - lo, 0.01)
        return [QtCore.QPointF(
            50 + (index + .5) * max(1, self.width() - 70) / len(self.points),
            self.height() - 86 - (point[1] - lo) / span * (self.height() - 176)
            if point[1] is not None else self.height() - 73,
        ) for index, point in enumerate(self.points)]

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
        painter.drawText(12, 38, "Click any candidate")
        painter.drawLine(40, 60, 40, self.height() - 86)
        painter.drawLine(40, self.height() - 86, self.width() - 12, self.height() - 86)
        painter.save()
        painter.translate(14, (self.height() - 86 + 60) / 2)
        painter.rotate(-90)
        axis_font = painter.font()
        axis_font.setPointSize(12)
        painter.setFont(axis_font)
        axis_label = f"{self.detector} score"
        metrics = painter.fontMetrics()
        painter.drawText(
            int(-metrics.horizontalAdvance(axis_label) / 2),
            int(metrics.ascent() / 2),
            axis_label,
        )
        painter.restore()
        for point, position in zip(self.points, self.positions()):
            identity, score, color = point
            radius = 8 if identity == self.selected else 5
            painter.setPen(QtGui.QPen(QtGui.QColor("#222222"), 2 if identity == self.selected else 1))
            painter.setBrush(QtGui.QColor(color))
            painter.drawEllipse(position, radius, radius)
            if self.evidence_counts.get(identity):
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.setPen(QtGui.QPen(QtGui.QColor(LIGAND_EVIDENCE_COLOR), 2.5))
                painter.drawEllipse(position, 13, 13)
            painter.setPen(QtGui.QColor("#222222"))
            if score is not None:
                painter.drawText(QtCore.QRectF(position.x() - 28, position.y() - 35, 56, 20),
                                 QtCore.Qt.AlignmentFlag.AlignCenter, f"{score:.3g}")
            painter.drawText(QtCore.QRectF(position.x() - 25, self.height() - 60, 50, 20),
                             QtCore.Qt.AlignmentFlag.AlignCenter, identity)
            if identity in self.conflicts:
                self._draw_obstruction_marker(painter, self.obstruction_marker_rect(position))
        painter.setPen(QtGui.QPen(QtGui.QColor(LIGAND_EVIDENCE_COLOR), 2))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QtCore.QPointF(17, self.height() - 25), 5, 5)
        painter.setPen(QtGui.QColor("#222222"))
        legend_font = painter.font()
        legend_font.setPointSize(9)
        painter.setFont(legend_font)
        painter.drawText(29, self.height() - 21, "Ligand evidence")
        key_x = 39 + painter.fontMetrics().horizontalAdvance("Ligand evidence")
        self._draw_obstruction_marker(painter, QtCore.QRectF(key_x, self.height() - 33, 16, 16))
        painter.setPen(QtGui.QColor("#222222"))
        painter.drawText(key_x + 24, self.height() - 21, "Possible obstruction")
        painter.drawText(12, self.height() - 5, "Below axis: unscored · not binding affinity")

    @staticmethod
    def obstruction_marker_rect(position):
        return QtCore.QRectF(position.x() + 18, position.y() - 9, 18, 18)

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
            label = QtCore.QRectF(center.x() - 25, self.height() - 64, 50, 26)
            warning = point[0] in self.conflicts and self.obstruction_marker_rect(center).contains(position)
            if (position - center).manhattanLength() <= 20 or label.contains(position) or warning:
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
            summary, explanation = conformation_summary(self.conformations.get(point[0], {}))
            self.setToolTip(f"{point[0]} · {score}\n"
                            f"{self.evidence_counts.get(point[0], 0)} deposited-ligand observations\n"
                            f"{summary}. {explanation}\n"
                            "Click to inspect in 3D. Evidence is not approval.")
        else:
            self.setToolTip("")
        super().mouseMoveEvent(event)
