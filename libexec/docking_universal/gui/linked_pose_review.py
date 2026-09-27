"""Exact retained-file identities and the 2D companion to the live viewport."""
from dataclasses import dataclass
from pathlib import Path
from collections import Counter
import base64
import html
import xml.etree.ElementTree as ET

from .qt import QtCore, QtGui, QtWidgets
from .results_review import InteractionDiagramLabel


@dataclass(frozen=True)
class PoseView:
    ligand: Path
    receptor: Path
    diagram: Path
    interactions: Path
    label: str


def pose_view(diagram: Path) -> PoseView | None:
    """Resolve only established artifact layouts; never infer a pose by energy."""
    diagram = diagram.resolve()
    if not diagram.is_file():
        return None
    cache = diagram.parent
    if cache.name.startswith("pose_") and cache.parent.name == "pose_interactions":
        analysis = cache.parent.parent
        ligand = cache / "pose.sdf"
        xml = cache / "plip" / "report.xml"
        label = f"Docked pose {cache.name.removeprefix('pose_').lstrip('0')}"
    elif cache.parent.name.startswith("cluster_"):
        cluster = cache.parent
        analysis = cluster.parent
        ligand = cluster / "representative.sdf"
        xml = cluster / "interactions" / "report.xml"
        label = f"Docked representative · {cluster.name.replace('_', ' ')}"
    else:
        return None
    receptor = analysis / "receptor.pdb"
    if not ligand.is_file() or not receptor.is_file():
        return None
    return PoseView(ligand, receptor, diagram, xml, label)


def control_view(state) -> PoseView | None:
    root_value = state.workflow_data.get("latest_control_output")
    if not root_value:
        return None
    root = Path(root_value)
    ligands = sorted((root / "00_inputs").glob("*_experimental.sdf"))
    diagrams = root / "report" / "control_experimental_plip2d.png"
    # A single experimentally deposited reference is unambiguous.
    receptors = [root / "report" / "control_pose_analysis" / "receptor.pdb"]
    receptors = [path for path in receptors if path.is_file()]
    if len(ligands) != 1 or not receptors or not diagrams.is_file():
        return None
    return PoseView(ligands[0], receptors[0], diagrams,
                    root / "02_experimental_pose" / "interactions" / "report.xml",
                    "Experimental control ligand")


def interaction_contacts(path):
    """Residue/class comparison, preserving chain identity; ambiguous sites fail closed."""
    root = ET.parse(path).getroot()
    sites = root.findall("bindingsite")
    if len(sites) != 1:
        raise ValueError("Interaction comparison requires one identified ligand binding site")
    contacts = Counter()
    for item in sites[0].findall("interactions/*/*"):
        chain, number, residue = (item.findtext(key) for key in ("reschain", "resnr", "restype"))
        if number is not None and residue is not None:
            contacts[(item.tag.replace('_', ' '), chain or '', number, residue)] += 1
    return contacts


def comparison_summary(query, reference):
    try:
        q, r = interaction_contacts(query.interactions), interaction_contacts(reference.interactions)
    except (OSError, ET.ParseError, ValueError) as exc:
        return f"Interaction comparison unavailable: {exc}"
    lines = ["PLIP residue/contact-class comparison"]
    for title, values in (("Shared", q.keys() & r.keys()),
                          ("Control only", r.keys() - q.keys()),
                          ("Docked only", q.keys() - r.keys())):
        text = "; ".join(f"{residue} {chain}:{number} ({kind})"
                         for kind, chain, number, residue in sorted(values))
        lines.append(f"{title}: {text or 'none'}")
    for title, contacts in (("Control", r), ("Docked", q)):
        totals = Counter()
        for (kind, *_), count in contacts.items():
            totals[kind] += count
        lines.append(title + " contacts: " + ", ".join(f"{k}: {n}" for k, n in sorted(totals.items())))
    lines.append("Contacts are calculated from coordinates. Shared residue/contact classes do not establish affinity.")
    return "\n\n".join(lines)


def write_comparison_report(path, query, reference, query_3d, reference_3d):
    """Self-contained local companion report, including camera-matched 3D renders."""
    def image(source):
        data = base64.b64encode(Path(source).read_bytes()).decode("ascii")
        return '<img src="data:image/png;base64,' + data + '">'
    body = '<!doctype html><meta charset="utf-8"><title>Ligand comparison</title>'
    body += '<style>body{font:16px sans-serif;margin:24px}table{width:100%;table-layout:fixed}td{vertical-align:top}img{width:100%}pre{white-space:pre-wrap}</style>'
    body += '<h1>Experimental control and docked ligand</h1>'
    body += '<p>Same receptor, orientation and zoom. Experimental coordinates are distinguished from a docking prediction.</p>'
    body += '<table><tr><th>Experimental control</th><th>Docked/query ligand</th></tr><tr>'
    body += '<td>' + image(reference_3d) + '</td><td>' + image(query_3d) + '</td></tr><tr>'
    body += '<td>' + image(reference.diagram) + '</td><td>' + image(query.diagram) + '</td></tr></table>'
    body += '<pre>' + html.escape(comparison_summary(query, reference)) + '</pre>'
    body += '<p>Ligand RMSD is omitted unless a chemically valid atom correspondence is established.</p>'
    Path(path).write_text(body, encoding="utf-8")


class FittedDiagramLabel(InteractionDiagramLabel):
    resized = QtCore.pyqtSignal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class LinkedPosePanel(QtWidgets.QWidget):
    """A compact diagram companion; the one PyMOL widget remains alongside it."""
    ligandActivated = QtCore.pyqtSignal(object)
    exportRequested = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("linked_pose_review")
        self.setMinimumWidth(320)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                           QtWidgets.QSizePolicy.Policy.Expanding)
        self.query = None
        self.reference = None
        self._pixmaps = {}
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        self.heading = QtWidgets.QLabel("2D interactions · selected 3D pose")
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        self.compare = QtWidgets.QCheckBox("Compare experimental control")
        self.compare.setEnabled(False)
        self.compare.toggled.connect(self._comparison_changed)
        layout.addWidget(self.compare)
        self.images = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.query_image = self._image("Select a docked pose to view its 2D interactions.")
        self.control_image = self._image("Experimental control diagram unavailable.")
        self.images.addWidget(self.query_image)
        self.images.addWidget(self.control_image)
        self.control_image.hide()
        layout.addWidget(self.images, 1)
        self.status = QtWidgets.QLabel("Click a diagram to highlight its ligand in 3D.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.details = QtWidgets.QPushButton("Interaction comparison details")
        self.details.setEnabled(False)
        self.details.clicked.connect(self._details)
        layout.addWidget(self.details)
        self.export_button = QtWidgets.QPushButton("Save comparison report…")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.exportRequested)
        layout.addWidget(self.export_button)
        self.images.splitterMoved.connect(self._fit)
        self.query_image.activated.connect(lambda: self._activate(self.query))
        self.control_image.activated.connect(lambda: self._activate(self.reference))

    def _image(self, text):
        label = FittedDiagramLabel(text)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setMinimumSize(120, 120)
        label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                            QtWidgets.QSizePolicy.Policy.Ignored)
        label.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        label.resized.connect(self._fit)
        return label

    def _activate(self, view):
        if view is not None:
            self.ligandActivated.emit(view)

    def clear_pose(self, message):
        self.query = None
        self.reference = None
        self._pixmaps.clear()
        self.compare.setChecked(False)
        self.compare.setEnabled(False)
        self.details.setEnabled(False)
        self.export_button.setEnabled(False)
        self.query_image.clear()
        self.control_image.clear()
        self.query_image.setText(message)
        self.heading.setText("2D interactions")
        self.status.setText(message)

    def set_pose(self, query, reference=None):
        self.query = query
        self.reference = reference
        self.heading.setText(query.label)
        self.compare.setEnabled(reference is not None)
        self.compare.setToolTip("No experimental control with the same retained receptor is available."
                               if reference is None else "Compare deposited experimental coordinates with this docked pose.")
        self.details.setEnabled(reference is not None)
        self.export_button.setEnabled(reference is not None)
        if reference is None:
            self.compare.setChecked(False)
        self._pixmaps = {self.query_image: QtGui.QPixmap(str(query.diagram))}
        self.query_image.setToolTip(query.label + " — click to highlight in 3D")
        if reference:
            self._pixmaps[self.control_image] = QtGui.QPixmap(str(reference.diagram))
            self.control_image.setToolTip("Experimental control — click to show in the same 3D view")
        self.status.setText("Click a diagram to highlight its ligand in 3D.")
        self._fit()

    def _comparison_changed(self, checked):
        self.control_image.setVisible(checked and self.reference is not None)
        QtCore.QTimer.singleShot(0, self._fit)

    def _details(self):
        if self.query and self.reference:
            dialog = QtWidgets.QDialog(self)
            dialog.setWindowTitle("Experimental / docked interaction comparison")
            layout = QtWidgets.QVBoxLayout(dialog)
            text = QtWidgets.QPlainTextEdit(comparison_summary(self.query, self.reference))
            text.setReadOnly(True)
            layout.addWidget(text)
            dialog.resize(700, 450)
            dialog.exec()

    def _fit(self, *_args):
        for label, pixmap in self._pixmaps.items():
            if not pixmap.isNull():
                size = label.contentsRect().size()
                if size.width() < 40 or size.height() < 40:
                    QtCore.QTimer.singleShot(0, self._fit)
                    continue
                canvas = QtGui.QPixmap(size)
                canvas.fill(QtCore.Qt.GlobalColor.white)
                painter = QtGui.QPainter(canvas)
                painter.setPen(QtCore.Qt.GlobalColor.black)
                title = "Experimental control" if label is self.control_image else "Docked/query ligand"
                painter.drawText(8, 20, title)
                image = pixmap.scaled(max(1, size.width()), max(1, size.height() - 30),
                                      QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                      QtCore.Qt.TransformationMode.SmoothTransformation)
                painter.drawPixmap((size.width() - image.width()) // 2,
                                   30 + max(0, (size.height() - 30 - image.height()) // 2), image)
                painter.end()
                label.setScaledContents(False)
                label.setPixmap(canvas)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()
