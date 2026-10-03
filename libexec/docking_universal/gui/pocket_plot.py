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
        self.setFixedHeight(220)
        self.setMouseTracking(True)
        self.points = []
        self.selected = None
        self.detector = "Pocket"

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
        for index, candidate in enumerate(state.workflow_data.get("pocket_candidates", [])):
            identity = str(candidate["id"])
            evidence = candidate.get("evidence", {})
            value = scores.get(identity, evidence.get("score"))
            if value is None:
                continue
            try:
                value = float(value)
            except (ValueError, TypeError):
                continue
            if not math.isfinite(value):
                continue
            self.detector = {"p2rank": "P2Rank", "fpocket": "fpocket"}.get(evidence.get("detector"), "Pocket")
            self.points.append((identity, value, self.COLORS[index % len(self.COLORS)]))
        self.setVisible(bool(self.points))
        self.update()

    def positions(self):
        if not self.points:
            return []
        lo = min(0, min(point[1] for point in self.points))
        hi = max(point[1] for point in self.points)
        span = max(hi - lo, 0.01)
        return [QtCore.QPointF(
            50 + (index + .5) * max(1, self.width() - 70) / len(self.points),
            self.height() - 42 - (point[1] - lo) / span * (self.height() - 100),
        ) for index, point in enumerate(self.points)]

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor("white"))
        painter.setPen(QtGui.QColor("#222222"))
        painter.drawText(12, 20, f"{self.detector} scores · click a pocket")
        painter.drawLine(40, 38, 40, self.height() - 42)
        painter.drawLine(40, self.height() - 42, self.width() - 12, self.height() - 42)
        for point, position in zip(self.points, self.positions()):
            identity, score, color = point
            radius = 8 if identity == self.selected else 5
            painter.setPen(QtGui.QPen(QtGui.QColor("#222222"), 2 if identity == self.selected else 1))
            painter.setBrush(QtGui.QColor(color))
            painter.drawEllipse(position, radius, radius)
            painter.setPen(QtGui.QColor("#222222"))
            painter.drawText(QtCore.QRectF(position.x() - 28, position.y() - 30, 56, 20),
                             QtCore.Qt.AlignmentFlag.AlignCenter, f"{score:.3g}")
            painter.drawText(QtCore.QRectF(position.x() - 25, self.height() - 38, 50, 20),
                             QtCore.Qt.AlignmentFlag.AlignCenter, identity)
        painter.drawText(12, self.height() - 5, "Detector scores; not binding affinity")

    def _hit(self, position):
        for point, center in zip(self.points, self.positions()):
            label = QtCore.QRectF(center.x() - 25, self.height() - 40, 50, 24)
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
        self.setToolTip(f"{point[0]} · {self.detector} score {point[1]:.4g}\nClick to inspect this pocket in 3D." if point else "")
        super().mouseMoveEvent(event)
