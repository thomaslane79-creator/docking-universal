"""Optional in-process PyMOL backend for the PyQt6 desktop.

PyMOL imports are intentionally delayed until widget construction. This keeps
the normal GUI and companion fallback importable when the combined runtime is
not installed.
"""

from __future__ import annotations

from pathlib import Path
import hashlib
import itertools
import math
import sys
from typing import Any
from uuid import uuid4

from ..gui.qt import QtCore, QtWidgets
from .pymol_adapter import RegisteredStructure
from .selections import Selection


POCKET_RGB = {
    "red": (1.0, 0.0, 0.0), "marine": (0.0, 0.5, 1.0),
    "gold": (1.0, 0.65, 0.0), "magenta": (1.0, 0.0, 1.0),
    "cyan": (0.0, 1.0, 1.0), "orange": (1.0, 0.5, 0.0),
    "violet": (0.56, 0.37, 0.6), "yellow": (1.0, 1.0, 0.0),
    "green": (0.0, 1.0, 0.0),
}


def _box_cgo(cgo, center, size, rgb, *, line_width=2.0, cylinder_radius=None):
    corners = [
        tuple(float(center[i]) + sign[i] * float(size[i]) / 2 for i in range(3))
        for sign in itertools.product((-1, 1), repeat=3)
    ]
    edges = []
    for index, first in enumerate(corners):
        for second in corners[index + 1:]:
            if sum(a != b for a, b in zip(first, second)) == 1:
                edges.append((first, second))
    if cylinder_radius is not None:
        result = []
        for first, second in edges:
            result.extend([
                cgo.CYLINDER, *first, *second, float(cylinder_radius),
                *rgb, *rgb,
            ])
        return result
    result = [cgo.LINEWIDTH, float(line_width), cgo.BEGIN, cgo.LINES, cgo.COLOR, *rgb]
    for first, second in edges:
        result.extend([cgo.VERTEX, *first, cgo.VERTEX, *second])
    return result + [cgo.END]


def create_embedded_pymol_widget(parent=None):
    """Create the genuine upstream widget or raise a precise runtime error."""
    try:
        import pymol
        from pmg_qt.pymol_gl_widget import PyMOLGLWidget
    except ImportError as exc:
        raise RuntimeError(
            "Embedded PyMOL requires the tested combined Python 3.12/PyQt6/PyMOL runtime"
        ) from exc

    options = pymol.invocation.options
    options.external_gui = 0
    options.internal_gui = 0
    options.internal_feedback = 0
    options.show_splash = 0
    options.quiet = 1
    options.no_quit = 1
    options.read_stdin = 0
    options.deferred = ["_do_button single_left, none, pk1"]

    class EmbeddedPymolWidget(PyMOLGLWidget):
        residuePicked = QtCore.pyqtSignal(dict)

        def __init__(self, widget_parent=None):
            super().__init__(widget_parent)
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
            self._du_stopped = False
            self._du_right_press_pos = None
            self._du_right_dragging = False
            self.setAcceptDrops(False)
            self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.PreventContextMenu)
            self.setMinimumSize(420, 300)
            self.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Expanding,
            )

        def initializeGL(self):
            super().initializeGL()
            handle = self.window().windowHandle()
            if handle:
                self.updateFbScale(handle)

        def event(self, event):
            # A double-click inside an embedded viewport must never escape to
            # PyMOL's application-level GUI machinery or a parent widget.  The
            # first ordinary click has already performed any atom selection;
            # consume the synthetic double-click event at this boundary.
            if event.type() == QtCore.QEvent.Type.MouseButtonDblClick:
                event.accept()
                return True
            return super().event(event)

        def mouseDoubleClickEvent(self, event):
            # Kept explicit as a second guard for Qt/platform event variations.
            self._du_right_press_pos = None
            self._du_right_dragging = False
            event.accept()

        def contextMenuEvent(self, event):
            event.accept()

        def mousePressEvent(self, event, state=0):
            if event.button() == QtCore.Qt.MouseButton.RightButton and state == 0:
                # Delay delivery until movement proves this is navigation.
                # A stationary right-click (single or double) is intentionally
                # inert so the embedded viewport cannot expose PyMOL menus.
                self._du_right_press_pos = event.position()
                self._du_right_dragging = False
                event.accept()
                return
            super().mousePressEvent(event, state)

        def mouseMoveEvent(self, event):
            if self._du_right_press_pos is not None:
                delta = event.position() - self._du_right_press_pos
                if not self._du_right_dragging and delta.manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                    self.pymol.button(
                        self._buttonMap[QtCore.Qt.MouseButton.RightButton], 0,
                        *self._event_x_y_mod(event),
                    )
                    self._du_right_dragging = True
                if self._du_right_dragging:
                    self.pymol.drag(*self._event_x_y_mod(event))
                event.accept()
                return
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event):
            if event.button() == QtCore.Qt.MouseButton.RightButton:
                if self._du_right_dragging:
                    self.pymol.button(
                        self._buttonMap[QtCore.Qt.MouseButton.RightButton], 1,
                        *self._event_x_y_mod(event),
                    )
                self._du_right_press_pos = None
                self._du_right_dragging = False
                event.accept()
                return
            super().mouseReleaseEvent(event)

        def paintGL(self):
            if not self._du_stopped:
                super().paintGL()

        def resizeGL(self, width, height):
            if not self._du_stopped:
                super().resizeGL(width, height)

        def stop(self):
            if self._du_stopped:
                return
            self._timer.stop()
            self.cmd.set_wizard()
            self.makeCurrent()
            self.pymol.stop()
            self.doneCurrent()
            self._du_stopped = True

    return EmbeddedPymolWidget(parent)


class EmbeddedPymolAdapter:
    """Implement the existing viewer contract on one GUI-thread PyMOL widget."""

    backend_kind = "embedded"
    backend_name = "Embedded PyMOL"

    def __init__(self, widget):
        self.widget = widget
        self.cmd = widget.cmd
        self.session_id = f"embedded-viewer-{uuid4().hex}"
        self.structures: dict[str, RegisteredStructure] = {}
        self.pockets: dict[str, dict[str, Any]] = {}
        self.report_session: Path | None = None
        self.review_pose: Path | None = None
        self.evidence_ligand: Path | None = None
        self._captured_view = None
        self._launched = False
        self.structure_context: str | None = None
        self._loaded_structure_context: str | None = None
        self._hidden_source_box: str | None = None
        self._hidden_redundant_boxes: list[str] = []
        self._visible_associated_object_names: set[str] = set()

    def set_structure_context(self, identity: str | None) -> None:
        self.structure_context = str(identity) if identity else None

    def launch(self, *, headless: bool = False) -> str:
        if headless:
            raise ValueError("The embedded viewer is a visible Qt widget")
        if getattr(self.widget, "_du_stopped", False):
            raise RuntimeError("The embedded PyMOL engine has already stopped")
        self._launched = True
        self.cmd.set("internal_gui", 0)
        self.cmd.set("internal_feedback", 0)
        self.cmd.set("orthoscopic", 1)
        self.cmd.set("opaque_background", 1)
        self.cmd.bg_color("white")
        return self.session_id

    def register_structure(self, structure: RegisteredStructure) -> dict[str, Any]:
        existing = self.structures.get(structure.object_name)
        if existing is not None:
            if existing != structure:
                raise ValueError(f"PyMOL object name is already registered: {structure.object_name}")
            return {"object_name": structure.object_name, "path": str(structure.path), "already_loaded": True}
        self.cmd.load(str(structure.path.resolve()), structure.object_name)
        self.cmd.hide("everything", structure.object_name)
        self.cmd.show("cartoon", structure.object_name)
        self.cmd.color("gray70", structure.object_name)
        self.structures[structure.object_name] = structure
        self.widget.update()
        return {"object_name": structure.object_name, "path": str(structure.path.resolve())}

    def show_pocket(self, path: Path | str, object_name: str, color: str) -> dict[str, Any]:
        pocket = Path(path).resolve()
        if not pocket.is_file():
            raise FileNotFoundError(f"Retained pocket coordinates are missing: {pocket}")
        retained = {"path": str(pocket), "object_name": object_name, "color": color}
        existing = self.pockets.get(object_name)
        if existing is not None:
            if existing != retained:
                raise ValueError(f"PyMOL pocket object name is already registered: {object_name}")
            return {**retained, "already_loaded": True}
        self.cmd.load(str(pocket), object_name)
        self.cmd.hide("everything", object_name)
        self.cmd.show("surface", object_name)
        self.cmd.set("transparency", 0.35, object_name)
        self.cmd.color(color, object_name)
        self.pockets[object_name] = retained
        self.widget.update()
        return retained

    def show_box(
        self, center, size, color: str = "red", source_object_name: str | None = None,
        redundant_object_names: tuple[str, ...] = (),
        visible_associated_object_names: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        values = [float(value) for value in [*center, *size]]
        if len(values) != 6 or not all(math.isfinite(value) for value in values) or any(value <= 0 for value in values[3:]):
            raise ValueError("Docking box requires finite center coordinates and positive sizes")
        if color not in POCKET_RGB:
            raise ValueError(f"Unsupported docking-box color: {color}")
        from pymol import cgo
        # Candidate navigation is a pan, never a zoom.  Loading a replacement
        # CGO can otherwise trigger PyMOL auto_zoom and make the pocket fill the
        # viewport.  Restore the exact camera first, then move only its center
        # to the selected box.
        view = self.cmd.get_view()
        auto_zoom = self.cmd.get_setting_int("auto_zoom")
        try:
            self.cmd.set("auto_zoom", 0)
            if self._hidden_source_box and self._hidden_source_box in self.cmd.get_names("objects"):
                self.cmd.enable(self._hidden_source_box)
            self._hidden_source_box = None
            object_names = self.cmd.get_names("objects")
            associated_objects = [
                name for name in object_names
                if name == "ligand_site_representative"
                or name.startswith("ligand_site_representative_")
            ]
            self._visible_associated_object_names = set(visible_associated_object_names)
            for object_name in associated_objects:
                if object_name in self._visible_associated_object_names:
                    self.cmd.enable(object_name)
                else:
                    self.cmd.disable(object_name)
            if source_object_name and source_object_name in self.cmd.get_names("objects"):
                self.cmd.disable(source_object_name)
                self._hidden_source_box = source_object_name
            for object_name in redundant_object_names:
                if object_name in self.cmd.get_names("objects"):
                    self.cmd.disable(object_name)
                    if object_name not in self._hidden_redundant_boxes:
                        self._hidden_redundant_boxes.append(object_name)
            self.cmd.delete("du_box")
            self.cmd.load_cgo(
                _box_cgo(
                    cgo, values[:3], values[3:], POCKET_RGB[color],
                    cylinder_radius=0.35,
                ),
                "du_box", zoom=0,
            )
        finally:
            self.cmd.set("auto_zoom", auto_zoom)
            self.cmd.set_view(view)
        self.cmd.center("du_box", animate=0)
        self.widget.update()
        return {
            "name": "du_box", "center": values[:3], "size": values[3:],
            "color": color,
            "replaces": self._hidden_source_box,
            "hides_redundant": list(self._hidden_redundant_boxes),
            "visible_associated": list(visible_associated_object_names),
            "camera": "center_preserving_scale",
            "edge_representation": "cylinders", "edge_radius_angstrom": 0.35,
        }

    def apply_selection(self, selection: Selection) -> Selection:
        self.cmd.select(selection.name, "none")
        grouped: dict[str, list[int]] = {}
        for atom in selection.atoms:
            registered = self._registered(atom)
            matches = []
            for candidate in self.cmd.get_model(registered.object_name).atom:
                if (
                    str(candidate.segi) == atom.segment
                    and str(candidate.chain) == atom.chain
                    and str(candidate.resi) == f"{atom.residue_number}{atom.insertion_code}"
                    and str(candidate.resn) == atom.residue_name
                    and str(candidate.name) == atom.atom_name
                    and str(candidate.alt) == atom.altloc
                ):
                    matches.append(int(candidate.index))
            if len(matches) != 1:
                raise ValueError(f"Selection atom does not map to exactly one displayed atom: {atom}")
            grouped.setdefault(registered.object_name, []).extend(matches)
        for object_name, indices in grouped.items():
            self.cmd.select_list(selection.name, object_name, indices, mode="index", merge=1)
        self.widget.update()
        return selection

    def load_report_session(self, path: Path | str) -> dict[str, Any]:
        return self._load_report_session(path, preserve_camera=True)

    def _load_report_session(
        self, path: Path | str, *, preserve_camera: bool,
    ) -> dict[str, Any]:
        session = Path(path).resolve()
        if not session.is_file() or session.suffix.lower() != ".pse":
            raise FileNotFoundError(f"Retained PyMOL scene is missing: {session}")
        previous_view = self.cmd.get_view() if self.report_session is not None else None
        previous_protein = self._protein_signature() if previous_view is not None else None
        self.cmd.load(str(session), partial=0)
        self._hidden_source_box = None
        self._hidden_redundant_boxes = []
        self._visible_associated_object_names = set()
        loaded_protein = self._protein_signature()
        same_context = bool(
            self.structure_context
            and self._loaded_structure_context
            and self.structure_context == self._loaded_structure_context
        )
        same_inferred_protein = bool(
            previous_protein and previous_protein == loaded_protein
        )
        camera_preserved = bool(
            preserve_camera and previous_view is not None
            and (same_context or same_inferred_protein)
        )
        self.last_camera_transition = {
            "previous_protein": previous_protein,
            "loaded_protein": loaded_protein,
            "camera_preserved": camera_preserved,
            "previous_view_available": previous_view is not None,
            "structure_context": self.structure_context,
            "loaded_structure_context": self._loaded_structure_context,
        }
        if camera_preserved:
            self.cmd.set_view(previous_view)
        else:
            self._frame_whole_protein()
        self.report_session = session
        self._loaded_structure_context = self.structure_context
        self.widget.update()
        return {
            "path": str(session), "replace": True,
            "camera": "preserved" if camera_preserved else "whole_protein",
        }

    def reset_report_view(self) -> dict[str, Any]:
        if self.report_session is None:
            raise ValueError("No retained report view is available to restore")
        return self._load_report_session(self.report_session, preserve_camera=False)

    def show_review_pose(self, path: Path | str) -> dict[str, Any]:
        pose = Path(path).resolve()
        if not pose.is_file() or pose.suffix.lower() != ".sdf":
            raise FileNotFoundError(f"Retained SDF review pose is missing: {pose}")
        view = self.cmd.get_view()
        auto_zoom = self.cmd.get_setting_int("auto_zoom")
        try:
            self.cmd.set("auto_zoom", 0)
            self.cmd.delete("du_review_pose")
            self.cmd.load(str(pose), "du_review_pose", zoom=0)
            self.cmd.show("sticks", "du_review_pose")
        finally:
            self.cmd.set("auto_zoom", auto_zoom)
            self.cmd.set_view(view)
        self.review_pose = pose
        self.widget.update()
        return {"path": str(pose), "object_name": "du_review_pose"}

    def show_linked_pose(self, ligand, receptor, *, highlight=False):
        """Review exact coordinates in one engine, preserving the same-receptor camera."""
        ligand, receptor = Path(ligand).resolve(), Path(receptor).resolve()
        if not ligand.is_file() or not receptor.is_file():
            raise FileNotFoundError("The retained ligand or receptor is unavailable")
        digest = hashlib.sha256(receptor.read_bytes()).hexdigest()
        objects = self.cmd.get_names("objects")
        reuse = (getattr(self, "_linked_receptor_hash", None) == digest
                 and "du_linked_receptor" in objects)
        view = self.cmd.get_view()
        auto_zoom = self.cmd.get_setting_int("auto_zoom")
        try:
            self.cmd.set("auto_zoom", 0)
            for name in objects:
                self.cmd.disable(name)
            if not reuse:
                self.cmd.delete("du_linked_receptor")
                self.cmd.load(str(receptor), "du_linked_receptor", zoom=0)
                self.cmd.hide("everything", "du_linked_receptor")
                self.cmd.show("cartoon", "du_linked_receptor")
                self.cmd.color("gray70", "du_linked_receptor and elem C")
            self.cmd.enable("du_linked_receptor")
            self.cmd.delete("du_review_pose")
            self.cmd.load(str(ligand), "du_review_pose", zoom=0)
            self.cmd.show("sticks", "du_review_pose")
            self.cmd.enable("du_review_pose")
            self.cmd.delete("du_ligand_highlight")
            if highlight:
                self.cmd.select("du_ligand_highlight", "du_review_pose")
            self._linked_receptor_hash = digest
            self.review_pose = ligand
        finally:
            self.cmd.set("auto_zoom", auto_zoom)
            self.cmd.set_view(view)
        if not reuse:
            self.cmd.orient("du_linked_receptor", animate=0)
            self.cmd.zoom("du_linked_receptor", buffer=8, complete=1, animate=0)
        self.widget.update()
        return {"path": str(ligand), "highlighted": highlight}

    def show_evidence_ligand(self, path: Path | str, receptor_path: Path | str | None = None):
        return self.show_evidence_ligands([path], receptor_path)

    def show_evidence_ligands(self, paths: list[Path | str], receptor_path: Path | str | None = None):
        ligands = [Path(path).resolve() for path in paths]
        if not ligands or any(not path.is_file() or path.suffix.lower() != ".pdb" for path in ligands):
            raise FileNotFoundError("Evidence comparison requires existing retained PDB ligands")
        self.sync_evidence_ligands(ligands)
        self.evidence_ligand = ligands[-1]
        return {"paths": [str(path) for path in ligands]}

    def sync_evidence_ligands(self, paths: list[Path | str]):
        ligands = [Path(path).resolve() for path in paths]
        if any(not path.is_file() or path.suffix.lower() != ".pdb" for path in ligands):
            raise FileNotFoundError("Evidence selection contains a missing PDB")
        # Loading a new object triggers PyMOL's global auto_zoom by default.
        # Evidence selection is a visibility operation, not a camera command:
        # retain the user's exact protein-level view across both first load and
        # every later table-selection change.
        view = self.cmd.get_view()
        auto_zoom = self.cmd.get_setting_int("auto_zoom")
        names = []
        try:
            self.cmd.set("auto_zoom", 0)
            object_names = self.cmd.get_names("objects")
            for name in object_names:
                if name.startswith("du_evidence_"):
                    self.cmd.disable(name)
                if (
                    name == "ligand_site_representative"
                    or name.startswith("ligand_site_representative_")
                ):
                    # A specific table observation supersedes the overview's
                    # representative ligand. Restore it only after the table
                    # selection is cleared and its candidate remains active.
                    if not ligands and name in self._visible_associated_object_names:
                        self.cmd.enable(name)
                    else:
                        self.cmd.disable(name)
            for path in ligands:
                name = f"du_evidence_{hashlib.sha256(str(path).encode()).hexdigest()[:12]}"
                if name not in self.cmd.get_names("objects"):
                    self.cmd.load(str(path), name, zoom=0)
                    self.cmd.hide("everything", name)
                    self.cmd.show("sticks", name)
                    # Deposited experimental ligands are green everywhere.
                    # Selection is conveyed by the active sticks, not by
                    # changing the molecule's scientific identity color.
                    self.cmd.color("green", f"{name} and elem C")
                    self.cmd.set("stick_radius", 0.32, name)
                self.cmd.enable(name)
                names.append(name)
        finally:
            self.cmd.set("auto_zoom", auto_zoom)
            self.cmd.set_view(view)
        self.widget.update()
        return {"paths": [str(path) for path in ligands], "objects": names}

    def capture_view(self):
        self._captured_view = self.cmd.get_view()
        return {"view": list(self._captured_view)}

    def reconnect(self, *, headless: bool = False) -> str:
        if not self.is_alive():
            raise RuntimeError("An embedded PyMOL engine cannot be restarted inside the same Qt process")
        return self.session_id

    def bring_to_front(self) -> None:
        self.widget.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)

    def close(self) -> None:
        if hasattr(self.widget, "stop"):
            self.widget.stop()
        self._launched = False

    def is_alive(self) -> bool:
        return bool(
            self._launched
            and not getattr(self.widget, "_du_stopped", False)
            and getattr(self.cmd, "_COb", None) is not None
        )

    def _registered(self, atom):
        matches = [item for item in self.structures.values() if item.identity == atom.structure]
        if len(matches) != 1:
            raise ValueError("Selection atom does not map to exactly one registered structure")
        return matches[0]

    def _protein_selection(self) -> str:
        if self.cmd.count_atoms("polymer"):
            return "polymer"
        if "receptor" in self.cmd.get_names("objects"):
            return "receptor"
        return "all"

    def _frame_whole_protein(self) -> None:
        selection = self._protein_selection()
        if self.cmd.count_atoms(selection):
            self.cmd.orient(selection, animate=0)
            self.cmd.zoom(selection, buffer=8, complete=1, animate=0)

    def _protein_signature(self) -> str | None:
        atoms = self.cmd.get_model(
            f"({self._protein_selection()}) and name CA"
        ).atom
        if not atoms:
            return None
        records = sorted(
            (
                str(atom.segi), str(atom.chain), str(atom.resi), str(atom.resn),
            )
            for atom in atoms
        )
        return hashlib.sha256(repr(records).encode()).hexdigest()
