"""Exact retained-file identities and the 2D companion to the live viewport."""
from dataclasses import dataclass
from pathlib import Path
from collections import Counter
import base64
import html
import json
import hashlib
import xml.etree.ElementTree as ET

from .qt import QtCore, QtGui, QtWidgets
from .results_review import InteractionDiagramLabel
from ..pose_visuals import cluster_color, retained_pose_color, read_pose_view


@dataclass(frozen=True)
class PoseView:
    ligand: Path
    receptor: Path
    diagram: Path
    interactions: Path
    label: str
    ligand_name: str = ""
    ligand_color: str = "gray70"
    coordinate_kind: str = "unknown"

    @property
    def experimental(self):
        # Compatibility for established artifacts predating source-kind metadata.
        # "experimental-RMSD pose" is a docking prediction, not an experiment.
        return self.coordinate_kind == "experimental" or (
            self.coordinate_kind == "unknown" and
            ("deposited" in self.label.lower() or self.label.lower() == "experimental control ligand"))


def retained_ligand_name(view):
    """A display name only, never a chemical-identity or pose-mapping inference."""
    if getattr(view, 'ligand_name', ''):
        return view.ligand_name
    try:
        with view.ligand.open() as source:
            title = source.readline().strip()
        if title:
            return title
    except (OSError, UnicodeError):
        pass
    return 'Ligand'


def pose_view(diagram: Path) -> PoseView | None:
    """Resolve only established artifact layouts; never infer a pose by energy."""
    diagram = diagram.resolve()
    if not diagram.is_file():
        return None
    if Path(str(diagram) + ".view.json").is_file():
        record = read_pose_view(diagram)
        return PoseView(**record) if record else None
    cache = diagram.parent
    if cache.name.startswith("pose_") and cache.parent.name == "pose_interactions":
        analysis = cache.parent.parent
        ligand = cache / "pose.sdf"
        xml = cache / "plip" / "report.xml"
        label = f"Docked pose {cache.name.removeprefix('pose_').lstrip('0')}"
        color = retained_pose_color(analysis, int(cache.name.removeprefix('pose_')))
    elif cache.parent.name.startswith("cluster_"):
        cluster = cache.parent
        analysis = cluster.parent
        ligand = cluster / "representative.sdf"
        xml = cluster / "interactions" / "report.xml"
        label = f"Docked representative · {cluster.name.replace('_', ' ')}"
        color = cluster_color(analysis, int(cluster.name.removeprefix('cluster_')))
    else:
        return None
    receptor = analysis / "receptor.pdb"
    if not ligand.is_file() or not receptor.is_file():
        return None
    return PoseView(ligand, receptor, diagram, xml, label, ligand_color=color, coordinate_kind="docked")


def control_view(state) -> PoseView | None:
    root_value = state.workflow_data.get("latest_control_output")
    if not root_value:
        return None
    root = Path(root_value)
    ligands = sorted((root / "00_inputs").glob("*_experimental.sdf"))
    diagrams = root / "report" / "control_experimental_plip2d.png"
    if Path(str(diagrams) + ".view.json").is_file():
        return pose_view(diagrams)
    # A single experimentally deposited reference is unambiguous.
    receptors = [root / "report" / "control_pose_analysis" / "receptor.pdb"]
    receptors = [path for path in receptors if path.is_file()]
    if len(ligands) != 1 or not receptors or not diagrams.is_file():
        return None
    return PoseView(ligands[0], receptors[0], diagrams,
                    root / "02_experimental_pose" / "interactions" / "report.xml",
                    "Experimental control ligand", ligand_color="magenta", coordinate_kind="experimental")


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


def contact_residues(view):
    """Use the report's exact source identities, never study-receptor numbering."""
    contacts = interaction_contacts(view.interactions)
    identities = sorted({(chain, number, name) for _, chain, number, name in contacts})
    return [{"chain": chain, "number": number, "name": name} for chain, number, name in identities]


def diagram_hit_regions(view):
    """Accept renderer hit regions only for this exact image and PLIP report."""
    try:
        record = json.loads(Path(str(view.diagram) + ".hit-regions.json").read_text())
        if record.get("image_sha256") != hashlib.sha256(view.diagram.read_bytes()).hexdigest():
            return []
        if record.get("plip_sha256") != hashlib.sha256(view.interactions.read_bytes()).hexdigest():
            return []
        allowed = {(r["chain"], r["number"], r["name"]) for r in contact_residues(view)}
        hits = []
        for hit in record.get("regions", []):
            residue, rect = hit["residue"], hit["rect"]
            if (residue["chain"], residue["number"], residue["name"]) not in allowed:
                continue
            if len(rect) != 4 or not all(isinstance(v, (float, int)) and 0 <= v <= 1 for v in rect):
                continue
            hits.append(hit)
        return hits
    except (OSError, ET.ParseError, ValueError, KeyError, TypeError):
        return []


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
    residueActivated = QtCore.pyqtSignal(dict)

    def residue_boxes(self):
        """Map verified name hit regions to the displayed pixmap, not its source size."""
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return []
        width = pixmap.width() / pixmap.devicePixelRatio()
        height = pixmap.height() / pixmap.devicePixelRatio()
        left, top = (self.width() - width) / 2, (self.height() - height) / 2
        return [(hit, QtCore.QRectF(left + hit['rect'][0] * width,
                                   top + hit['rect'][1] * height,
                                   hit['rect'][2] * width, hit['rect'][3] * height))
                for hit in getattr(self, 'hit_regions', [])]

    def paintEvent(self, event):
        super().paintEvent(event)
        # UI-only outlines preserve the detailed rendering and retained report.
        # Painting and clicking use precisely the same rectangles.
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtGui.QPen(QtGui.QColor('#466a87'), 1.0))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        for _, rect in self.residue_boxes():
            painter.drawRoundedRect(rect, 2, 2)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            hits = [hit for hit, rect in self.residue_boxes() if rect.contains(event.position())]
            keys = {(h["residue"]["chain"], h["residue"]["number"], h["residue"]["name"]) for h in hits}
            if len(keys) == 1:
                self.residueActivated.emit(hits[0]["residue"])
                event.accept()
                return
            if hits:
                event.accept()  # overlapping different labels must not guess
                return
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class LinkedPosePanel(QtWidgets.QWidget):
    """A compact diagram companion; the one PyMOL widget remains alongside it."""
    ligandActivated = QtCore.pyqtSignal(object)
    exportRequested = QtCore.pyqtSignal()
    detaching = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("linked_pose_review")
        self.setMinimumWidth(320)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                           QtWidgets.QSizePolicy.Policy.Expanding)
        self.query = None
        self.reference = None
        self._pixmaps = {}
        self._zoom = None
        self._detached_window = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        # Reuse the existing heading row: a visible named target, not another
        # toolbar taking space away from the diagram.
        self.heading = QtWidgets.QPushButton("2D interactions")
        self.heading.setObjectName('center_review_ligand')
        self.heading.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
        self.heading.setEnabled(False)
        self.heading.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.heading.clicked.connect(lambda: self.query_image.activated.emit())
        layout.addWidget(self.heading)
        tools = QtWidgets.QHBoxLayout()
        self.detach_button = QtWidgets.QPushButton("Detach 2D")
        self.detach_button.setEnabled(False)
        self.detach_button.clicked.connect(self.detach_diagram)
        tools.addWidget(self.detach_button)
        for text, callback in (("Fit", self.fit_diagram), ("100%", lambda: self.zoom_diagram(1.0)),
                               ("−", lambda: self.step_zoom(0.8)), ("+", lambda: self.step_zoom(1.25))):
            button = QtWidgets.QPushButton(text)
            button.clicked.connect(callback)
            tools.addWidget(button)
        layout.addLayout(tools)
        self.compare = QtWidgets.QCheckBox("Compare experimental control")
        self.compare.setEnabled(False)
        self.compare.toggled.connect(self._comparison_changed)
        layout.addWidget(self.compare)
        self.images = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.query_image = self._image("Select a docked pose to view its 2D interactions.")
        self.control_image = self._image("Experimental control diagram unavailable.")
        self._scrolls = {}
        for label in (self.query_image, self.control_image):
            scroll = QtWidgets.QScrollArea()
            scroll.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            scroll.setWidget(label)
            scroll.setWidgetResizable(False)
            self._scrolls[label] = scroll
            self.images.addWidget(scroll)
        self._scrolls[self.control_image].hide()
        self.control_image.hide()
        layout.addWidget(self.images, 1)
        self.status = QtWidgets.QLabel("Click a diagram to open matching 3D review.")
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
        self.detach_button.setEnabled(False)
        self.compare.setChecked(False)
        self.compare.setEnabled(False)
        self.details.setEnabled(False)
        self.export_button.setEnabled(False)
        self.compare.hide()
        self.details.hide()
        self.export_button.hide()
        self.control_image.hide()
        self._scrolls[self.control_image].hide()
        self.query_image.clear()
        self.query_image.hit_regions = []
        self.control_image.hit_regions = []
        self.control_image.clear()
        self.query_image.setText(message)
        self.heading.setText("2D interactions")
        self.heading.setEnabled(False)
        self.status.clear()

    def show_loading(self, message):
        self.clear_pose(message)
        self.status.setText("Calculating PLIP contacts and arranging the diagram…")

    def set_pose(self, query, reference=None):
        self.query = query
        self.reference = reference
        self.detach_button.setEnabled(True)
        self.compare.setVisible(reference is not None)
        self.details.setVisible(reference is not None)
        self.export_button.setVisible(reference is not None)
        self.control_image.setVisible(reference is not None and self.compare.isChecked())
        self._scrolls[self.control_image].setVisible(reference is not None and self.compare.isChecked())
        name = retained_ligand_name(query)
        self._ligand_heading = name + ' · Center ligand in 3D'
        self.heading.setText(self._ligand_heading)
        self.heading.setToolTip(name + ' — click to center this exact ligand; camera zoom and 2D diagram stay unchanged.')
        self.heading.setEnabled(True)
        self.compare.setEnabled(reference is not None)
        self.compare.setToolTip("No experimental control with the same retained receptor is available."
                               if reference is None else "Compare deposited experimental coordinates with this docked pose.")
        self.details.setEnabled(reference is not None)
        self.export_button.setEnabled(reference is not None)
        if reference is None:
            self.compare.setChecked(False)
        self._pixmaps = {self.query_image: QtGui.QPixmap(str(query.diagram))}
        self.query_image.hit_regions = diagram_hit_regions(query)
        self.query_image.setToolTip(query.label + " — click to center in paired 3D review")
        if reference:
            self._pixmaps[self.control_image] = QtGui.QPixmap(str(reference.diagram))
            self.control_image.setToolTip("Experimental control — click to show in the same 3D view")
        self.status.setText("Click a boxed residue name or the ligand heading to center in 3D. Checkboxes control residue sticks."
                           if self.query_image.hit_regions else
                           "Retained diagram has no verified residue links. Click the ligand heading to center in 3D; checkboxes control residue sticks.")
        self._fit()

    def _comparison_changed(self, checked):
        self.control_image.setVisible(checked and self.reference is not None)
        self._scrolls[self.control_image].setVisible(checked and self.reference is not None)
        QtCore.QTimer.singleShot(0, self._fit)

    def detach_diagram(self):
        if self._detached_window is not None:
            self._detached_window.close()
            return
        self.detaching.emit()
        parent = self.parentWidget()
        if not isinstance(parent, QtWidgets.QSplitter):
            return
        self._home_splitter = parent
        self._home_index = parent.indexOf(self)
        self._home_sizes = parent.sizes()
        dialog = QtWidgets.QDialog(parent.window())
        dialog.setWindowTitle("2D interactions")
        dialog.resize(850, 700)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(self)
        self._detached_window = dialog
        self.detach_button.setText("Return to workspace")
        dialog.finished.connect(self._reattach_diagram)
        dialog.show()
        self.show()
        QtCore.QTimer.singleShot(0, self._fit)

    def _reattach_diagram(self, *_args):
        dialog = self._detached_window
        self._detached_window = None
        self._home_splitter.insertWidget(self._home_index, self)
        self._home_splitter.setSizes(self._home_sizes)
        self.detach_button.setText("Detach 2D")
        self.show()
        dialog.deleteLater()
        QtCore.QTimer.singleShot(0, self._fit)

    def fit_diagram(self):
        self._zoom = None
        self._fit()

    def zoom_diagram(self, factor):
        self._zoom = max(0.1, min(4.0, factor))
        self._fit()

    def step_zoom(self, multiplier):
        if self._zoom is None:
            source = self._pixmaps.get(self.query_image)
            self._zoom = self.query_image.width() / source.width() if source and source.width() else 1.0
        self.zoom_diagram(self._zoom * multiplier)

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
        if self.query and getattr(self, '_ligand_heading', ''):
            self.heading.setText(self.heading.fontMetrics().elidedText(
                self._ligand_heading, QtCore.Qt.TextElideMode.ElideMiddle, max(80, self.heading.width() - 24)))
        for label, pixmap in self._pixmaps.items():
            if not pixmap.isNull():
                size = self._scrolls[label].viewport().size()
                if size.width() < 40 or size.height() < 40:
                    QtCore.QTimer.singleShot(0, self._fit)
                    continue
                target = size if self._zoom is None else QtCore.QSize(
                    max(1, round(pixmap.width() * self._zoom)), max(1, round(pixmap.height() * self._zoom)))
                image = pixmap.scaled(target,
                                      QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                      QtCore.Qt.TransformationMode.SmoothTransformation)
                label.setScaledContents(False)
                label.setPixmap(image)
                label.resize(image.size())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()
