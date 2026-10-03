"""Clickable pocket scores from retained detector output."""

import csv
import math
import re
from pathlib import Path

from .qt import QtCore, QtGui, QtWidgets


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
                        value = float(line.split("|")[0])
                        if math.isfinite(value):
                            scores[f"P{index}"] = value
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
            if (evidence.get("conformational_site_evidence") or {}).get("box_decision_warning"):
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
        painter.setFont(font)
        painter.drawText(12, 20, "Choose a docking region")
        font.setBold(False)
        painter.setFont(font)
        painter.drawText(12, 38, f"{self.detector} scores · click any candidate")
        painter.drawLine(40, 60, 40, self.height() - 86)
        painter.drawLine(40, self.height() - 86, self.width() - 12, self.height() - 86)
        for point, position in zip(self.points, self.positions()):
            identity, score, color = point
            radius = 8 if identity == self.selected else 5
            painter.setPen(QtGui.QPen(QtGui.QColor("#222222"), 2 if identity == self.selected else 1))
            painter.setBrush(QtGui.QColor(color))
            painter.drawEllipse(position, radius, radius)
            if self.evidence_counts.get(identity):
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.setPen(QtGui.QPen(QtGui.QColor("#009b50"), 2.5))
                painter.drawEllipse(position, 13, 13)
            painter.setPen(QtGui.QColor("#222222"))
            if score is not None:
                painter.drawText(QtCore.QRectF(position.x() - 28, position.y() - 35, 56, 20),
                                 QtCore.Qt.AlignmentFlag.AlignCenter, f"{score:.3g}")
            painter.drawText(QtCore.QRectF(position.x() - 25, self.height() - 60, 50, 20),
                             QtCore.Qt.AlignmentFlag.AlignCenter, identity)
            if identity in self.conflicts:
                painter.setPen(QtGui.QColor("#a85b00"))
                painter.drawText(QtCore.QRectF(position.x() + 16, position.y() - 12, 16, 20),
                                 QtCore.Qt.AlignmentFlag.AlignCenter, "!")
        painter.setPen(QtGui.QPen(QtGui.QColor("#009b50"), 2))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QtCore.QPointF(17, self.height() - 25), 5, 5)
        painter.setPen(QtGui.QColor("#222222"))
        painter.drawText(29, self.height() - 21, "Deposited ligand evidence   ! Conflict")
        painter.drawText(12, self.height() - 5, "Below axis: unscored · not binding affinity")

    def _hit(self, position):
        for point, center in zip(self.points, self.positions()):
            label = QtCore.QRectF(center.x() - 25, self.height() - 64, 50, 26)
            if (position - center).manhattanLength() <= 20 or label.contains(position):
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
            self.setToolTip(f"{point[0]} · {score}\n"
                            f"{self.evidence_counts.get(point[0], 0)} deposited-ligand observations\n"
                            "Click to inspect in 3D. Evidence is not approval.")
        else:
            self.setToolTip("")
        super().mouseMoveEvent(event)
