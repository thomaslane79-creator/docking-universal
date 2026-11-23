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
import os
import sys
from typing import Any
from uuid import uuid4

from ..gui.qt import QtCore, QtWidgets
from .pymol_adapter import RegisteredStructure
from .selections import Selection
from .scene_style import SELECTED_BOX_RADIUS, expand_scene_clipping
from ..pocket_metadata import POCKET_COLOR_RGB


POCKET_RGB = {
    "red": (1.0, 0.0, 0.0), "marine": (0.0, 0.5, 1.0),
    "gold": (1.0, 0.65, 0.0), "magenta": (1.0, 0.0, 1.0),
    "cyan": (0.0, 1.0, 1.0), "orange": (1.0, 0.5, 0.0),
    "violet": (0.56, 0.37, 0.6), "yellow": (1.0, 1.0, 0.0),
    "green": (0.0, 1.0, 0.0),
    "du_report_unscored": (0.4, 0.447, 0.49),
    **POCKET_COLOR_RGB,
}


def _set_pocket_color(cmd, color, selection):
    if color in POCKET_COLOR_RGB or color == 'du_report_unscored':
        cmd.set_color(color, POCKET_RGB[color])
    cmd.color(color, selection)

# Display-only rolling probe: rounds the bead-union envelope without changing
# grid coordinates/radii. This is not a molecular solvent/cavity measurement.
POCKET_SURFACE_PROBE = 1.4
POCKET_SURFACE_STYLE = 'rolling-probe-1.4-quality-2-v1'


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
    options.deferred = ["_do_button single_left, none, cent"]

    class EmbeddedPymolWidget(PyMOLGLWidget):
        residuePicked = QtCore.pyqtSignal(dict)
        inputMoleculePicked = QtCore.pyqtSignal(dict)

        def __init__(self, widget_parent=None):
            super().__init__(widget_parent)
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
            self._du_stopped = False
            self._du_full_interface = False
            self._du_interaction_review = False
            self._du_blocked_gesture = False
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
            if self._du_stopped:
                return
            super().initializeGL()
            handle = self.window().windowHandle()
            if handle:
                self.updateFbScale(handle)

        def updateFbScale(self, context):
            if not getattr(self, '_du_stopped', False):
                super().updateFbScale(context)

        def _pymolProcess(self):
            if self._du_stopped:
                return
            if not getattr(self, '_du_fast_animation', False):
                return super()._pymolProcess()
            # The upstream widget checks at 20 ms intervals. During a camera
            # pan, poll sooner so redraws can follow the display refresh rate.
            idle = self.pymol.idle()
            if idle or self.pymol.getRedisplay():
                self.update()
            self._timer.start(8)

        def event(self, event):
            if getattr(self, "_du_full_interface", False):
                return super().event(event)
            # A double-click inside an embedded viewport must never escape to
            # PyMOL's application-level GUI machinery or a parent widget.  The
            # first ordinary click has already performed any atom selection;
            # consume the synthetic double-click event at this boundary.
            if event.type() == QtCore.QEvent.Type.MouseButtonDblClick:
                event.accept()
                return True
            return super().event(event)

        def mouseDoubleClickEvent(self, event):
            if self._du_full_interface:
                return super().mouseDoubleClickEvent(event)
            # Kept explicit as a second guard for Qt/platform event variations.
            self._du_right_press_pos = None
            self._du_right_dragging = False
            event.accept()

        def contextMenuEvent(self, event):
            if self._du_full_interface:
                return super().contextMenuEvent(event)
            event.accept()

        def mousePressEvent(self, event, state=0):
            if self._du_full_interface:
                return super().mousePressEvent(event, state)
            if (event.modifiers() &
                    (QtCore.Qt.KeyboardModifier.ShiftModifier | QtCore.Qt.KeyboardModifier.ControlModifier)):
                self._du_blocked_gesture = True
                event.accept()
                return
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
            if self._du_full_interface:
                return super().mouseMoveEvent(event)
            if self._du_blocked_gesture:
                event.accept()
                return
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
            if self._du_full_interface:
                super().mouseReleaseEvent(event)
                self._du_expand_clipping()
                return
            if self._du_blocked_gesture:
                self._du_blocked_gesture = False
                event.accept()
                return
            if event.button() == QtCore.Qt.MouseButton.RightButton:
                if self._du_right_dragging:
                    self.pymol.button(
                        self._buttonMap[QtCore.Qt.MouseButton.RightButton], 1,
                        *self._event_x_y_mod(event),
                    )
                self._du_right_press_pos = None
                self._du_right_dragging = False
                self._du_expand_clipping()
                event.accept()
                return
            super().mouseReleaseEvent(event)
            self._du_expand_clipping()

        def wheelEvent(self, event):
            super().wheelEvent(event)
            self._du_expand_clipping()

        def _du_expand_clipping(self):
            if not self._du_stopped:
                expand_scene_clipping(self.cmd, getattr(self, '_du_box_bounds', None))

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
            try:
                self.pymol.stop()
                self._du_stopped = True
                # Upstream SingletonPyMOL.stop clears cmd._COb, but the widget's
                # engine still owns the same native capsule. Its destructor
                # frees the singleton; release it while the GL context is
                # current so switching studies can safely create the next one.
                self.pymol._COb = None
            finally:
                self.doneCurrent()

    return EmbeddedPymolWidget(parent)


class EmbeddedPymolAdapter:
    """Implement the existing viewer contract on one GUI-thread PyMOL widget."""

    backend_kind = "embedded"
    backend_name = "Embedded PyMOL"

    def __init__(self, widget):
        self.widget = widget
        if sys.platform == 'win32' and os.environ.get('DOCKING_UNIVERSAL_VIEWER_GRAPHICS') == 'software':
            self.backend_name = 'Embedded PyMOL · software graphics'
        self.cmd = widget.cmd
        self.session_id = f"embedded-viewer-{uuid4().hex}"
        self.structures: dict[str, RegisteredStructure] = {}
        self.pockets: dict[str, dict[str, Any]] = {}
        self.report_session: Path | None = None
        self._obstruction_highlight = None
        self._contact_highlights = {}
        self._review_atoms = None
        self._review_labels = set()
        self._review_label_anchors = {}
        self._plip_contacts = []
        self._plip_contacts_visible = True
        self._plip_types_visible = {}
        self.review_pose: Path | None = None
        self.evidence_ligand: Path | None = None
        self._captured_view = None
        self._launched = False
        self.structure_context: str | None = None
        self._loaded_structure_context: str | None = None
        self._hidden_source_box: str | None = None
        self._hidden_redundant_boxes: list[str] = []
        self._visible_associated_object_names: set[str] = set()
        self._input_preview = None

    def begin_input_preview(self, path: Path | str) -> dict[str, Any]:
        """Temporarily display supplied coordinates without registering a receptor."""
        source = Path(path).resolve()
        if not source.is_file() or source.suffix.lower() not in {'.pdb', '.cif', '.mmcif'}:
            raise ValueError('Preview requires a local PDB or mmCIF structure.')
        result = self._begin_local_preview(lambda name: self.cmd.load(str(source), name, zoom=0))
        return {**result, 'path': str(source)}

    def begin_compound_preview(self, mol_block: str) -> dict[str, Any]:
        """Display supplied compound coordinates; never generate a conformer."""
        return self._begin_local_preview(lambda name: self.cmd.read_molstr(mol_block, name, zoom=0), ligand_only=True)

    def _begin_local_preview(self, load, *, ligand_only=False) -> dict[str, Any]:
        if self._input_preview is not None:
            raise RuntimeError('An input-structure preview is already open.')
        name = 'du_input_preview_' + uuid4().hex
        self._input_preview = {
            'name': name, 'view': self.cmd.get_view(),
            'enabled': list(self.cmd.get_names('objects', enabled_only=1)),
        }
        auto_zoom = self.cmd.get_setting_int('auto_zoom')
        try:
            self.cmd.set('auto_zoom', 0)
            load(name)
            for existing in self._input_preview['enabled']:
                self.cmd.disable(existing)
            self.cmd.hide('everything', name)
            self.cmd.color('atomic', name)
            self.cmd.set('cartoon_color', 'gray70', name)
            self.cmd.show('cartoon', f'{name} and polymer')
            components = f'{name} and not polymer and not solvent'
            self.cmd.color('orange', f'({components}) and elem C')
            self.cmd.show('sticks', components)
            self.cmd.show('nonbonded', components)
            visible = f'{name} and not solvent'
            if not self.cmd.count_atoms(visible):
                raise ValueError('No non-water atoms are available to preview.')
            self.cmd.orient(visible, animate=0)
            self.cmd.zoom(visible, buffer=2 if ligand_only else 6, complete=int(not ligand_only), animate=0)
            self.widget.update()
            return {'object_name': name}
        except Exception:
            self.end_input_preview()
            raise
        finally:
            self.cmd.set('auto_zoom', auto_zoom)

    def focus_input_preview(self, entry, *, show_receptor=True, preserve_view=False,
                            show_all_components=False, visible_components=None) -> None:
        """Render the inspector's visible instances using exact source atom indices.

        An overview pick keeps the camera/other visible ligands; explicit list
        navigation can focus one component. Hidden supporting atoms remain in
        the temporary object and original input for reversible display filtering.
        """
        if self._input_preview is None:
            raise ValueError('Open the local preview first.')
        name = self._input_preview['name']
        components = f'{name} and not polymer and not solvent'
        shown_components = components
        atoms = self.cmd.get_model(name, state=1).atom if visible_components is not None or entry['kind'] != 'whole' else []
        if visible_components is not None:
            identities = {(item['resname'], item['chain'], item['resi'], item.get('segment') or None)
                          for item in visible_components}
            indices = [atom.index for atom in atoms
                       if (atom.resn, atom.chain, atom.resi, atom.segi) in identities
                       or (atom.resn, atom.chain, atom.resi, None) in identities]
            shown_components = f'{name} and index ' + '+'.join(str(int(index)) for index in indices) if indices else 'none'
        self.cmd.color('orange', f'({components}) and elem C')
        if entry['kind'] == 'whole':
            self.cmd.hide('everything', name)
            self.cmd.show('cartoon', f'{name} and polymer')
            selection = shown_components
            self.cmd.show('sticks', selection)
            self.cmd.show('nonbonded', selection)
            selection = f'({name} and polymer) or ({shown_components})'
        else:
            indices = [atom.index for atom in atoms
                       if atom.chain == entry['chain'] and atom.resi == entry['resi']
                       and atom.resn == entry['resname']
                       and (not entry.get('segment') or atom.segi == entry['segment'])]
            if not indices:
                raise ValueError('The exact selected component is not present in the preview coordinates.')
            selection = f'{name} and index ' + '+'.join(str(int(index)) for index in indices)
            self.cmd.hide('everything', name)
            self.cmd.show('sticks', selection)
            self.cmd.show('nonbonded', selection)
            if show_receptor:
                self.cmd.show('cartoon', f'{name} and polymer')
                if show_all_components:
                    self.cmd.show('sticks', shown_components)
                    self.cmd.show('nonbonded', shown_components)
            self.cmd.color('cyan', f'({selection}) and elem C')
        if not preserve_view:
            self.cmd.orient(selection, animate=0)
            component = entry['kind'] == 'component'
            self.cmd.zoom(selection, buffer=2 if component else 4, complete=int(not component), animate=0)
        self.widget.update()

    def enable_input_preview_picking(self) -> None:
        """Route temporary native atom picks to the molecule inspector only."""
        if self._input_preview is None:
            raise ValueError('Open the local preview first.')
        preview = self._input_preview
        if 'wizard_stack' in preview:
            return
        from pymol.wizard import Wizard
        preview['wizard_stack'] = self.cmd.get_wizard_stack()
        preview['interaction_input'] = getattr(self.widget, '_du_interaction_review', False)
        adapter = self

        class InputMoleculeWizard(Wizard):
            def get_event_mask(self):
                return Wizard.event_mask_pick

            def do_pick(self, bondFlag):
                try:
                    if bondFlag or adapter._input_preview is not preview:
                        return
                    indices = self.cmd.index('pk1')
                    if len(indices) != 1 or indices[0][0] != preview['name']:
                        return
                    atoms = self.cmd.get_model('pk1', state=1).atom
                    if len(atoms) == 1:
                        self.cmd.center('pk1', animate=0)
                        adapter.expand_scene_clipping()
                        atom = atoms[0]
                        adapter.widget.inputMoleculePicked.emit(dict(
                            object=preview['name'], name=atom.resn, chain=atom.chain,
                            number=atom.resi, segment=atom.segi))
                finally:
                    self.cmd.unpick()

        self.cmd.set_wizard(InputMoleculeWizard(_self=self.cmd))
        self.cmd.button('single_left', 'none', 'pk1')
        self.widget._du_interaction_review = True

    def end_input_preview(self) -> None:
        preview = self._input_preview
        if preview is None:
            return
        self._input_preview = None
        try:
            if 'wizard_stack' in preview:
                self.cmd.set_wizard_stack(preview['wizard_stack'])
                self.widget._du_interaction_review = preview['interaction_input']
                self.cmd.button('single_left', 'none', 'pk1' if preview['interaction_input'] else 'cent')
                self.widget._du_blocked_gesture = False
            self.cmd.delete(preview['name'])
        finally:
            names = set(self.cmd.get_names('objects'))
            for name in preview['enabled']:
                if name in names:
                    self.cmd.enable(name)
            self.cmd.set_view(preview['view'])
            self.widget.update()

    def set_structure_context(self, identity: str | None) -> None:
        self.structure_context = str(identity) if identity else None

    def expand_scene_clipping(self):
        bounds = getattr(self.widget, '_du_box_bounds', None)
        if 'du_box' not in self.cmd.get_names('objects', enabled_only=1):
            bounds = None
        expand_scene_clipping(self.cmd, bounds)

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
        self._frame_whole_protein()
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
        view = self.cmd.get_view()
        auto_zoom = self.cmd.get_setting_int("auto_zoom")
        try:
            self.cmd.set("auto_zoom", 0)
            self.cmd.load(str(pocket), object_name, zoom=0)
        finally:
            self.cmd.set("auto_zoom", auto_zoom)
            self.cmd.set_view(view)
        self.cmd.hide("everything", object_name)
        self.cmd.show("surface", object_name)
        self.cmd.set("transparency", 0.32, object_name)
        _set_pocket_color(self.cmd, color, object_name)
        self.pockets[object_name] = retained
        self.expand_scene_clipping()
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
        # A candidate click changes geometry/visibility, not the user's camera
        # or rotation pivot. Explicit interaction-review centering is separate.
        view = self.cmd.get_view()
        auto_zoom = self.cmd.get_setting_int("auto_zoom")
        try:
            self.cmd.set("auto_zoom", 0)
            self._multi_source_boxes = []
            self._hidden_source_box = None
            object_names = self.cmd.get_names("objects")
            # Retained scene boxes are source geometry, not the current selection.
            # Keep every one hidden; du_box is rebuilt from the selected regions.
            source_boxes = {name for name in object_names
                            if name.startswith('candidate_box_') or name == 'ligand_site_box'}
            source_boxes.update(name for name in (source_object_name, *redundant_object_names)
                                if name and name in object_names)
            for name in object_names:
                if name in source_boxes:
                    self.cmd.disable(name)
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
                self._hidden_source_box = source_object_name
            self._hidden_redundant_boxes = []
            for object_name in redundant_object_names:
                if object_name in self.cmd.get_names("objects"):
                    if object_name not in self._hidden_redundant_boxes:
                        self._hidden_redundant_boxes.append(object_name)
            self.cmd.delete("du_box")
            self.cmd.load_cgo(
                _box_cgo(
                    cgo, values[:3], values[3:], POCKET_RGB[color],
                    cylinder_radius=SELECTED_BOX_RADIUS,
                ),
                "du_box", zoom=0,
            )
        finally:
            self.cmd.set("auto_zoom", auto_zoom)
            self.cmd.set_view(view)
        self.widget._du_box_bounds = [[values[i] - values[i+3]/2 for i in range(3)],
                                     [values[i] + values[i+3]/2 for i in range(3)]]
        self.expand_scene_clipping()
        self.widget.update()
        return {
            "name": "du_box", "center": values[:3], "size": values[3:],
            "color": color,
            "replaces": self._hidden_source_box,
            "hides_redundant": list(self._hidden_redundant_boxes),
            "visible_associated": list(visible_associated_object_names),
            "camera": "preserved",
            "edge_representation": "cylinders", "edge_radius_angstrom": SELECTED_BOX_RADIUS,
        }

    def show_multiple_boxes(self, boxes):
        """Replace the active overlay with all selected boxes, preserving the camera."""
        from pymol import cgo
        rendered, lows, highs = [], [], []
        for box in boxes:
            values = [float(v) for v in [*box['center'], *box['size']]]
            color = box['color']
            if len(values) != 6 or not all(math.isfinite(v) for v in values) or any(v <= 0 for v in values[3:]) or color not in POCKET_RGB:
                raise ValueError('Invalid selected docking box')
            rendered.extend(_box_cgo(cgo, values[:3], values[3:], POCKET_RGB[color], cylinder_radius=SELECTED_BOX_RADIUS))
            lows.append([values[i] - values[i + 3] / 2 for i in range(3)])
            highs.append([values[i] + values[i + 3] / 2 for i in range(3)])
        if not rendered:
            raise ValueError('No selected docking boxes')
        view = self.cmd.get_view()
        auto_zoom = self.cmd.get_setting_int('auto_zoom')
        try:
            self.cmd.set('auto_zoom', 0)
            for box in boxes[1:]:
                for name in (box['source_object_name'], *box.get('redundant_object_names', ())):
                    if name in self.cmd.get_names('objects'):
                        self.cmd.disable(name)
                        self._multi_source_boxes.append(name)
            self.cmd.delete('du_box')
            self.cmd.load_cgo(rendered, 'du_box', zoom=0)
        finally:
            self.cmd.set('auto_zoom', auto_zoom)
            self.cmd.set_view(view)
        self.widget._du_box_bounds = [[min(v[i] for v in lows) for i in range(3)],
                                     [max(v[i] for v in highs) for i in range(3)]]
        self.expand_scene_clipping()
        self.widget.update()
        return {'count': len(boxes), 'camera': 'preserved'}

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

    @staticmethod
    def _obstruction_key(residues):
        return tuple(sorted(tuple(str(r.get(key) or "") for key in
            ("chain", "name", "number", "insertion_code", "segment")) for r in residues))

    def is_obstruction_highlighted(self, residues) -> bool:
        return bool(self._obstruction_highlight and
                    self._obstruction_highlight["key"] == self._obstruction_key(residues))

    def clear_obstruction_highlight(self) -> None:
        retained = self._obstruction_highlight
        if retained and retained["object"] in self.cmd.get_names("objects"):
            if retained["added"]:
                self.cmd.select_list("du_obstruction_added", retained["object"], retained["added"], mode="index")
                self.cmd.hide("sticks", "du_obstruction_added")
        self.cmd.delete("du_obstruction_added")
        self.cmd.delete("du_obstruction")
        self._obstruction_highlight = None
        self.widget.update()

    def highlight_obstruction_residues(self, residues: list[dict]) -> dict[str, Any]:
        """Toggle exact-residue sticks, without a persistent atom-selection overlay."""
        objects = self.cmd.get_object_list("polymer.protein and enabled")
        receptor = next((name for name in ("du_receptor", "receptor", "du_linked_receptor")
                         if name in objects), None)
        if receptor is None:
            if len(objects) != 1:
                raise ValueError("The displayed receptor cannot be identified unambiguously")
            receptor = objects[0]
        atoms = self.cmd.get_model(receptor).atom
        indices = []
        for residue in residues:
            if not all(key in residue for key in ("chain", "name", "number")):
                raise ValueError("Obstruction evidence lacks an exact residue identity")
            resi = str(residue["number"]) + str(residue.get("insertion_code") or "")
            matches = [atom for atom in atoms if str(atom.chain) == str(residue["chain"])
                       and str(atom.resn) == str(residue["name"]) and str(atom.resi) == resi
                       and ("segment" not in residue or str(atom.segi) == str(residue["segment"]))]
            if not matches or len({str(atom.segi) for atom in matches}) != 1:
                raise ValueError(f"Recorded residue {residue['name']}{resi}{residue['chain']} does not map uniquely to the current receptor")
            indices.extend(int(atom.index) for atom in matches)
        if not indices:
            raise ValueError("No obstructing residues were recorded")
        view = self.cmd.get_view()
        try:
            if self.is_obstruction_highlighted(residues) and self._obstruction_highlight["object"] == receptor:
                self.clear_obstruction_highlight()
                return {"highlighted": False, "object": receptor, "atom_count": 0}
            if self._obstruction_highlight:
                self.clear_obstruction_highlight()
            existing_sticks = {int(atom.index) for atom in self.cmd.get_model("rep sticks").atom
                               if str(atom.model) == receptor}
            self.cmd.select_list("du_obstruction", receptor, sorted(set(indices)), mode="index")
            try:
                self.cmd.show("sticks", "du_obstruction")
            finally:
                # The named selection is only a temporary atom-addressing aid.
                # Keeping it enabled paints pink selection markers over sticks.
                # Deleting it does not undo the representation or affect users'
                # own named selections in the full PyMOL interface.
                self.cmd.delete("du_obstruction")
            self._obstruction_highlight = {"key": self._obstruction_key(residues), "object": receptor,
                "added": sorted(set(indices) - existing_sticks)}
        finally:
            self.cmd.set_view(view)
        self.widget.update()
        return {"highlighted": True, "object": receptor, "atom_count": len(set(indices))}

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
        if self._obstruction_highlight:
            self.clear_obstruction_highlight()
        self.cmd.load(str(session), partial=0)
        # A saved PyMOL session can restore its own mouse bindings, including
        # atom selection. Reapply the embedded viewer's deliberate picking mode.
        self.cmd.button('single_left', 'none',
                        'pk1' if getattr(self.widget, '_du_interaction_review', False) else 'cent')
        self.cmd.deselect()
        from .scene_style import apply_native_display_scale
        apply_native_display_scale(self.widget)
        self.widget._du_box_bounds = None
        self._pocket_surface_styles = {}
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
        self.expand_scene_clipping()
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
            self.clear_linked_contacts()
            self.cmd.delete("du_multi_pose_*")
            self.cmd.delete("du_review_pose")
            self.cmd.load(str(pose), "du_review_pose", zoom=0)
            self.cmd.show("sticks", "du_review_pose")
        finally:
            self.cmd.set("auto_zoom", auto_zoom)
            self.cmd.set_view(view)
        self.expand_scene_clipping()
        self.review_pose = pose
        self.widget.update()
        return {"path": str(pose), "object_name": "du_review_pose"}

    def show_multiple_review_poses(self, selections):
        """Overlay exact retained SDF records sharing one receptor coordinate frame."""
        groups = {}
        receptors = []
        for root, pose_id in selections:
            root = Path(root).resolve()
            if int(pose_id) < 1:
                raise ValueError('Pose IDs must be positive.')
            groups.setdefault(root, set()).add(int(pose_id))
            receptor = root / 'receptor.pdb'
            if not receptor.is_file():
                raise FileNotFoundError(f'Receptor is missing: {receptor}')
            receptors.append(receptor)
        if not groups or len({hashlib.sha256(path.read_bytes()).hexdigest() for path in receptors}) != 1:
            raise ValueError('Selected poses must share the same retained receptor.')
        blocks = {}
        for root, wanted in groups.items():
            with (root / 'all_poses.sdf').open(encoding='utf-8', errors='strict') as source:
                record, number = [], 1
                for line in source:
                    if line.strip() == '$$$$':
                        if number in wanted:
                            block = ''.join(record)
                            if 'M  END' not in block:
                                raise ValueError(f'Pose {number} has an invalid SDF record.')
                            blocks[(root, number)] = block.split('M  END', 1)[0] + 'M  END\n'
                            if all((root, pose) in blocks for pose in wanted):
                                break
                        record, number = [], number + 1
                    else:
                        record.append(line)
            if not all((root, pose) in blocks for pose in wanted):
                raise ValueError('One or more selected poses are absent from the retained SDF.')
        self.clear_linked_contacts()
        previous_view = self.cmd.get_view()
        previous_auto_zoom = self.cmd.get_setting_int('auto_zoom')
        receptor_hash = hashlib.sha256(receptors[0].read_bytes()).hexdigest()
        reuse_receptor = (getattr(self, '_linked_receptor_hash', None) == receptor_hash
                          and 'du_linked_receptor' in self.cmd.get_names('objects'))
        try:
            self.cmd.set('auto_zoom', 0)
            for name in self.cmd.get_names('objects'):
                self.cmd.disable(name)
            self.cmd.delete('du_multi_pose_*')
            if reuse_receptor:
                self.cmd.enable('du_linked_receptor')
            else:
                self.cmd.delete('du_linked_receptor')
                self.cmd.load(str(receptors[0]), 'du_linked_receptor', zoom=0)
                self.cmd.hide('everything', 'du_linked_receptor')
                self.cmd.show('cartoon', 'du_linked_receptor')
                self.cmd.color('gray70', 'du_linked_receptor and elem C')
            colors = ('red', 'marine', 'orange', 'magenta', 'cyan', 'yellow', 'salmon', 'violet')
            for index, (root, pose_id) in enumerate(selections):
                name = f'du_multi_pose_{index + 1}'
                self.cmd.read_molstr(blocks[(Path(root).resolve(), int(pose_id))], name)
                self.cmd.show('sticks', name)
                self.cmd.color(colors[index % len(colors)], name + ' and elem C')
            self.cmd.set('scene_buttons', 0)
            self._linked_receptor_hash = receptor_hash
        finally:
            self.cmd.set('auto_zoom', previous_auto_zoom)
            self.cmd.set_view(previous_view)
        self.expand_scene_clipping()
        self.widget.update()

    def show_linked_pose(self, ligand, receptor, *, highlight=False, frame_receptor=True, ligand_color="gray70"):
        """Review exact coordinates in one engine, preserving the same-receptor camera."""
        ligand, receptor = Path(ligand).resolve(), Path(receptor).resolve()
        from ..pose_visuals import LIGAND_COLORS
        if ligand_color not in LIGAND_COLORS:
            raise ValueError("Unsupported retained-pose color")
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
            # A new ligand must never inherit the previous pose's contact sticks,
            # labels or CGO state, even when its receptor is reused.
            self.clear_linked_contacts()
            self.cmd.delete('du_multi_pose_*')
            if not reuse and self._obstruction_highlight:
                self.clear_obstruction_highlight()
            for name in objects:
                self.cmd.disable(name)
            # Saved representative sessions carry PyMOL scene buttons; those
            # belong to the old session, not the selected result being shown.
            self.cmd.set('scene_buttons', 0)
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
            self.cmd.color(ligand_color, "du_review_pose and elem C")
            self.cmd.enable("du_review_pose")
            self.cmd.delete("du_ligand_highlight")
            if highlight:
                self.cmd.select("du_ligand_highlight", "du_review_pose")
            self._linked_receptor_hash = digest
            self.review_pose = ligand
        finally:
            self.cmd.set("auto_zoom", auto_zoom)
            self.cmd.set_view(view)
        if not reuse and frame_receptor:
            self.cmd.orient("du_linked_receptor", animate=0)
            self.cmd.zoom("du_linked_receptor", buffer=8, complete=1, animate=0)
        if frame_receptor:
            self.expand_scene_clipping()
        self.widget.update()
        return {"path": str(ligand), "highlighted": highlight}

    def clear_linked_contacts(self):
        if 'du_linked_receptor' in self.cmd.get_names('objects'):
            self.cmd.hide('sticks', 'du_linked_receptor')
            self.cmd.hide('labels', 'du_linked_receptor')
        self.cmd.delete('du_review_plip_contacts')
        self._contact_highlights = {}
        self._review_atoms = None
        self._review_labels = set()
        self._review_label_anchors = {}
        self._plip_contacts = []
        self._plip_contacts_visible = True
        self._plip_types_visible = {}
        self.widget.update()

    def clear_site_review_overlays(self):
        self.clear_linked_contacts()
        for name in self.cmd.get_names("objects"):
            if name == "du_review_pose" or name.startswith(("du_multi_pose_", "du_evidence_")):
                self.cmd.disable(name)
        self.widget.update()

    def set_site_review_visibility(self, *, has_selection, show_boxes):
        names = self.cmd.get_names("objects")
        if "du_box" in names:
            (self.cmd.enable if has_selection and show_boxes else self.cmd.disable)("du_box")
        for name in names:
            if not has_selection or not show_boxes:
                if name.startswith("candidate_box_") or name == "ligand_site_box":
                    self.cmd.disable(name)
            if not has_selection:
                if name.startswith("du_pocket_space_") and name != "du_pocket_space_src":
                    self.cmd.hide("surface", name)
                if name.startswith(("du_evidence_", "ligand_site_representative")):
                    self.cmd.disable(name)
        self.widget.update()

    def show_linked_interactions(self, view, *, focus_on_new_receptor=True):
        """Browse a retained representative with its own PLIP contacts, no rerun."""
        self.clear_linked_contacts()
        self.cmd.disable('du_review_pose')
        digest = hashlib.sha256(Path(view.receptor).read_bytes()).hexdigest()
        reuse = (getattr(self, '_linked_receptor_hash', None) == digest
                 and 'du_linked_receptor' in self.cmd.get_names('objects'))
        self.show_linked_pose(view.ligand, view.receptor, frame_receptor=False,
                              ligand_color=getattr(view, 'ligand_color', 'gray70'))
        self.cmd.show('cartoon', 'du_linked_receptor')
        from .plip_contacts import contacts
        recorded = contacts(view.interactions)
        residues = list({(c['residue']['chain'], c['residue']['number'], c['residue']['name']):
                         c['residue'] for c in recorded}.values())
        self._review_atoms = tuple(self.cmd.get_model('du_linked_receptor').atom)
        # Validate every residue before adding any contact geometry. A missing
        # report or mismatched receptor leaves only the newly selected ligand.
        for residue in residues:
            self._contact_residue_atoms(residue)
        for residue in residues:
            self.set_contact_residue_visible(residue, True)
        styles = self.show_review_contacts(view.interactions)
        if not reuse and focus_on_new_receptor:
            self.focus_interaction_review()
        else:
            self.expand_scene_clipping()
        return styles, residues

    def begin_interaction_review(self, view):
        """Snapshot the user's scene; the paired review borrows this same engine."""
        import copy
        snapshot = {"session": self.cmd.get_session(cache=0, compress=0), "view": self.cmd.get_view(),
                    "linked_hash": getattr(self, "_linked_receptor_hash", None),
                    "review_pose": self.review_pose,
                    "obstruction": copy.deepcopy(self._obstruction_highlight),
                    "float_labels": self.cmd.get_setting_int('float_labels'),
                    "interaction_input": getattr(self.widget, '_du_interaction_review', False)}
        snapshot['contacts'] = {name: copy.deepcopy(getattr(self, name)) for name in (
            '_contact_highlights', '_review_labels', '_review_label_anchors',
            '_plip_contacts', '_plip_contacts_visible', '_plip_types_visible')}
        snapshot['review_atoms'] = self._review_atoms
        try:
            self._contact_highlights = {}
            self.show_linked_pose(view.ligand, view.receptor, highlight=False, frame_receptor=False,
                                  ligand_color=getattr(view, "ligand_color", "gray70"))
            # This review is local to the ligand, not a whole-protein view.
            # Contact toggles add sticks; the complete scene is restored on close.
            self.cmd.hide("everything", "du_linked_receptor")
            self.cmd.show('cartoon', 'du_linked_receptor')
            self._review_atoms = tuple(self.cmd.get_model('du_linked_receptor').atom)
            self._review_labels = set()
            self._review_label_anchors = {}
            self._plip_contacts = []
            self._plip_contacts_visible = True
            self._plip_types_visible = {}
        except Exception:
            self.end_interaction_review(snapshot)
            raise
        return snapshot

    def focus_interaction_review(self):
        """Frame the ligand and exactly mapped contacts once when opening a pair.

        Contacts can span several chains. Never frame the full receptor or
        change zoom again on label clicks or checkbox toggles.
        """
        if not self.cmd.count_atoms("du_review_pose"):
            raise ValueError("The matching review ligand is unavailable")
        self.cmd.zoom("du_review_pose or (du_linked_receptor and rep sticks)",
                      buffer=2, complete=0, animate=0)
        self.center_review_ligand()
        self.expand_scene_clipping()

    def show_pocket_space(self, manifest, ranks, color):
        """Display only verified alpha grid volume; never infer a void from residues."""
        colors = color if isinstance(color, dict) else {rank: color for rank in ranks}
        if any(value not in POCKET_RGB for value in colors.values()):
            raise ValueError('Pocket color is not supported')
        camera = self.cmd.get_view()
        clipped_camera = camera
        try:
            names = self.cmd.get_names('objects')
            if getattr(self, '_pocket_space_hash', None) != manifest['grid_sha256'] or 'du_pocket_space_src' not in names:
                for name in names:
                    if name.startswith('du_pocket_space_'):
                        self.cmd.delete(name)
                self.cmd.load(manifest['grid'], 'du_pocket_space_src', zoom=0)
                self.cmd.hide('everything', 'du_pocket_space_src')
                self.cmd.disable('du_pocket_space_src')
                self._pocket_space_hash = manifest['grid_sha256']
                self._pocket_surface_styles = {}
            names = self.cmd.get_names('objects')
            import re
            for name in names:
                if name.startswith('du_pocket_space_'):
                    self.cmd.disable(name)
                elif name in self.pockets or re.fullmatch(r'(?:du_pocket_\d+|pocket_\d+_cavity|.*_pocket_\d+)', name):
                    self.cmd.hide('surface', name)
            rendered = []
            for rank in ranks:
                if str(rank) not in manifest['counts']:
                    continue
                name = f'du_pocket_space_{int(rank)}'
                if name not in names:
                    self.cmd.create(name, f'du_pocket_space_src and resi {int(rank)}', zoom=0)
                    self.cmd.hide('everything', name)
                    self.cmd.alter(name, f"vdw={float(manifest['display_radius_angstrom'])}")
                # Reapply after restoring an older session as well as new loads.
                if (name not in names
                        or getattr(self, '_pocket_surface_styles', {}).get(name) != POCKET_SURFACE_STYLE):
                    self.cmd.set('surface_solvent', 0, name)
                    self.cmd.set('solvent_radius', POCKET_SURFACE_PROBE, name)
                    self.cmd.set('surface_type', 0, name)
                    self.cmd.set('surface_carve_selection', '', name)
                    self.cmd.set('surface_quality', 2, name)
                    self.cmd.rebuild(name)
                    if not hasattr(self, '_pocket_surface_styles'):
                        self._pocket_surface_styles = {}
                    self._pocket_surface_styles[name] = POCKET_SURFACE_STYLE
                _set_pocket_color(self.cmd, colors[int(rank)], name)
                self.cmd.show('surface', name)
                self.cmd.set('transparency', 0.32, name)
                self.cmd.set('two_sided_lighting', 1)
                self.cmd.enable(name)
                rendered.append(name)
            if rendered:
                # clip atoms computes camera-space bounds natively. Widen only;
                # never recenter, rezoom, rotate, or replace a deliberately wide slab.
                self.cmd.set_view(camera)
                self.cmd.clip('atoms', float(manifest['display_radius_angstrom']) +
                              POCKET_SURFACE_PROBE + 1.0, ' or '.join(rendered))
                bounds = self.cmd.get_view()
                clipped_camera = list(camera)
                clipped_camera[15] = min(camera[15], bounds[15])
                clipped_camera[16] = max(camera[16], bounds[16])
        finally:
            self.cmd.set_view(clipped_camera)
        self.expand_scene_clipping()
        self.widget.update()
        return rendered

    def end_interaction_review(self, snapshot):
        self.cmd.set_session(snapshot["session"])
        from .scene_style import apply_native_display_scale
        apply_native_display_scale(self.widget)
        self.cmd.set('float_labels', snapshot.get('float_labels', 0))
        self.cmd.set_view(snapshot["view"])
        self._linked_receptor_hash = snapshot["linked_hash"]
        self.review_pose = snapshot["review_pose"]
        self._obstruction_highlight = snapshot["obstruction"]
        self._contact_highlights = {}
        self._review_atoms = snapshot.get('review_atoms')
        self._review_labels = set()
        self._review_label_anchors = {}
        self._plip_contacts = []
        self._plip_types_visible = {}
        for name, value in snapshot.get('contacts', {}).items():
            setattr(self, name, value)
        self.widget._du_interaction_review = snapshot.get('interaction_input', False)
        if hasattr(self.cmd, 'button'):
            self.cmd.button('single_left', 'none', 'pk1' if self.widget._du_interaction_review else 'cent')
        self.widget._du_blocked_gesture = False
        self.widget.update()

    def _contact_residue_atoms(self, residue):
        """Resolve one exact source residue, never interpolate study numbering."""
        receptor = "du_linked_receptor"
        if receptor not in self.cmd.get_names("objects"):
            raise ValueError("The paired receptor is no longer loaded")
        atoms = self._review_atoms if self._review_atoms is not None else self.cmd.get_model(receptor).atom
        resi = str(residue["number"]) + str(residue.get("insertion_code") or "")
        matched = [a for a in atoms if str(a.chain) == str(residue["chain"])
                   and str(a.resn) == str(residue["name"]) and str(a.resi) == resi
                   and ("segment" not in residue or str(a.segi) == str(residue["segment"]))]
        if not matched or len({str(a.segi) for a in matched}) != 1:
            raise ValueError(f"{residue['name']} {residue['chain']}:{resi} is missing or ambiguous in the source receptor")
        return matched

    def _center_review_selection(self, selection, *, animate=False):
        camera = tuple(self.cmd.get_view())
        try:
            self.cmd.center(selection, animate=0)
            centered = list(self.cmd.get_view())
            # Only pan/origin may change. Keep rotation, depth, clipping and
            # orthoscopic scale exactly as the user set them.
            centered[:9] = camera[:9]
            centered[11] = camera[11]
            centered[15:18] = camera[15:18]
            previous = getattr(self, '_site_pan_timer', None)
            if previous is not None:
                previous.stop()
                previous.deleteLater()
                self._site_pan_timer = None
            if animate:
                # Native PyMOL view interpolation advances at ~30 positions/s
                # even when the viewport renders faster. Advance using elapsed
                # time on Qt's precise timer so dropped frames do not slow the pan.
                self.cmd.set_view(camera)
                self.widget._du_fast_animation = True
                timer = QtCore.QTimer(self.widget)
                timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
                timer.setInterval(16)
                elapsed = QtCore.QElapsedTimer()
                elapsed.start()
                def advance():
                    if getattr(self.widget, '_du_stopped', False):
                        timer.stop()
                        return
                    amount = min(1.0, elapsed.elapsed() / 450.0)
                    eased = amount * amount * (3.0 - 2.0 * amount)
                    frame = list(camera)
                    for index in (9, 10, 12, 13, 14):
                        frame[index] = camera[index] + (centered[index] - camera[index]) * eased
                    self.cmd.set_view(frame)
                    self.widget.update()
                    if amount >= 1.0:
                        timer.stop()
                        self.widget._du_fast_animation = False
                        self._site_pan_timer = None
                        timer.deleteLater()
                timer.timeout.connect(advance)
                self._site_pan_timer = timer
                timer.start()
            else:
                self.widget._du_fast_animation = False
                self.cmd.set_view(centered)
        except Exception:
            self.cmd.set_view(camera)
            raise
        self.widget.update()

    def center_contact_residue(self, residue):
        matched = self._contact_residue_atoms(residue)
        temporary = "du_center_" + uuid4().hex
        try:
            self.cmd.select_list(temporary, "du_linked_receptor",
                                 sorted({int(a.index) for a in matched}), mode="index")
            self._center_review_selection(temporary)
        finally:
            self.cmd.delete(temporary)

    def center_review_point(self, center, *, animate=False):
        """Center a recorded box without changing the camera's zoom or rotation."""
        name = 'du_temporary_box_center'
        try:
            self.cmd.pseudoatom(name, pos=[float(value) for value in center])
            self._center_review_selection(name, animate=animate)
        finally:
            self.cmd.delete(name)
        if not animate:
            self.expand_scene_clipping()

    def center_pocket(self, number, *, animate=False):
        name = f'du_pocket_space_{int(number)}'
        if name not in self.cmd.get_names('objects') or not self.cmd.count_atoms(name):
            raise ValueError('The selected pocket surface is not available')
        self._center_review_selection(name, animate=animate)

    def center_evidence_ligand(self, path, *, animate=False):
        name = f"du_evidence_{hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()[:12]}"
        if name not in self.cmd.get_names('objects') or not self.cmd.count_atoms(name):
            raise ValueError('The selected evidence ligand is not loaded')
        self._center_review_selection(name, animate=animate)

    def center_review_ligand(self, *, animate=False):
        if "du_review_pose" not in self.cmd.get_names("objects") or not self.cmd.count_atoms("du_review_pose"):
            raise ValueError("The matching review ligand is no longer loaded")
        self._center_review_selection("du_review_pose", animate=animate)

    def center_displayed_pose(self, index=0, *, animate=False):
        names = self.cmd.get_names('objects')
        overlay = f'du_multi_pose_{int(index) + 1}'
        name = overlay if overlay in names else ('du_review_pose' if int(index) == 0 else overlay)
        if name not in names or not self.cmd.count_atoms(name):
            raise ValueError('The selected pose is not loaded')
        self._center_review_selection(name, animate=animate)

    def set_contact_residue_visible(self, residue, visible):
        """Independent sticks toggles on the exact paired receptor; no markers/pan."""
        receptor = "du_linked_receptor"
        matched = self._contact_residue_atoms(residue)
        key = self._obstruction_key([residue])
        tracked = self._contact_highlights.get(key)
        if visible and tracked:
            return True
        if not visible and not tracked:
            return False
        camera = self.cmd.get_view()
        temporary = "du_contact_" + uuid4().hex
        try:
            if visible:
                indices = sorted({int(a.index) for a in matched})
                existing = ({index for item in self._contact_highlights.values() for index in item['added']}
                            if self._review_atoms is not None else
                            {int(a.index) for a in self.cmd.get_model("du_linked_receptor and rep sticks").atom})
                self.cmd.select_list(temporary, receptor, indices, mode="index")
                self.cmd.show("sticks", temporary)
                self._contact_highlights[key] = {"added": sorted(set(indices) - existing)}
            else:
                if tracked["added"]:
                    self.cmd.select_list(temporary, receptor, tracked["added"], mode="index")
                    self.cmd.hide("sticks", temporary)
                del self._contact_highlights[key]
        finally:
            self.cmd.delete(temporary)
            self.cmd.set_view(camera)
        self.widget.update()
        if self._plip_contacts:
            self._refresh_review_contacts()
        return bool(visible)

    def set_review_cartoon_visible(self, visible):
        (self.cmd.show if visible else self.cmd.hide)('cartoon', 'du_linked_receptor')
        self.widget.update()

    def enable_review_picking(self):
        """Native picks label entire exact residues, without persistent pick marks."""
        from pymol.wizard import Wizard
        adapter = self
        class ResidueLabelWizard(Wizard):
            def get_event_mask(self):
                return Wizard.event_mask_pick
            def do_pick(self, bondFlag):
                try:
                    indices = self.cmd.index('pk1')
                    if len(indices) == 1:
                        model = self.cmd.get_model('pk1').atom
                        if model:
                            self.cmd.center('pk1', animate=0)
                            adapter.expand_scene_clipping()
                            atom = model[0]
                            adapter.widget.residuePicked.emit(dict(
                                object=indices[0][0], name=atom.resn, chain=atom.chain,
                                number=atom.resi, segment=atom.segi))
                finally:
                    self.cmd.unpick()
        self.cmd.set_wizard(ResidueLabelWizard(_self=self.cmd))
        self.cmd.button('single_left', 'none', 'pk1')
        self.widget._du_interaction_review = True

    def toggle_review_residue_label(self, residue):
        if residue.get('object', 'du_linked_receptor') != 'du_linked_receptor':
            return None
        return self.set_review_residue_label(
            residue, self._obstruction_key([residue]) not in self._review_labels)

    def has_review_residue_labels(self):
        return bool(self._review_labels)

    def set_review_labels_visible(self, residues, visible):
        """Label exact visible contacts or clear only labels added by this review."""
        if visible:
            # Validate the entire request before changing any label.
            for residue in residues:
                self._contact_residue_atoms(residue)
            for residue in residues:
                self.set_review_residue_label(residue, True)
        else:
            for index in self._review_label_anchors.values():
                selection = f'du_linked_receptor and index {index}'
                self.cmd.label(selection, '""')
                self.cmd.hide('labels', selection)
            self._review_label_anchors.clear()
            self._review_labels.clear()
            self.widget.update()
        return self.has_review_residue_labels()

    def set_review_residue_label(self, residue, visible):
        if residue.get('object', 'du_linked_receptor') != 'du_linked_receptor':
            return None
        atoms = self._contact_residue_atoms(residue)
        anchor = next((a for a in atoms if a.name == 'CA'), atoms[0])
        key = self._obstruction_key([residue])
        selection = f'du_linked_receptor and index {int(anchor.index)}'
        if bool(visible) == (key in self._review_labels):
            return bool(visible)
        self.cmd.label(selection, repr(f"{residue['name']} {residue['chain']}:{residue['number']}") if visible else '""')
        (self.cmd.show if visible else self.cmd.hide)('labels', selection)
        self.cmd.set('label_color', 'black', 'du_linked_receptor')
        self.cmd.set('label_size', 22, 'du_linked_receptor')
        self.cmd.set('label_font_id', 7, 'du_linked_receptor')
        self.cmd.set('label_outline_color', 'white', 'du_linked_receptor')
        # The interactive depth-test switch is global in the native renderer.
        # Save/restore it explicitly; object-level label style remains scoped.
        self.cmd.set('float_labels', 1)
        if visible:
            self._review_labels.add(key)
            self._review_label_anchors[key] = int(anchor.index)
        else:
            self._review_labels.discard(key)
            self._review_label_anchors.pop(key, None)
        self.widget.update()
        return visible

    def show_review_contacts(self, report):
        from .plip_contacts import contacts, STYLES
        self._plip_contacts = contacts(report)
        self._plip_types_visible = {c['kind']: True for c in self._plip_contacts}
        self._refresh_review_contacts()
        return {kind: STYLES[kind] for kind in {c['kind'] for c in self._plip_contacts}}

    def set_review_contacts_visible(self, visible):
        self._plip_contacts_visible = bool(visible)
        self._refresh_review_contacts()

    def set_review_contact_type_visible(self, kind, visible):
        if kind not in self._plip_types_visible:
            raise ValueError('This PLIP interaction type is not present in the review')
        self._plip_types_visible[kind] = bool(visible)
        self._refresh_review_contacts()

    def _refresh_review_contacts(self):
        from pymol import cgo
        from .plip_contacts import STYLES
        lines = []
        if self._plip_contacts_visible:
            for contact in self._plip_contacts:
                if not self._plip_types_visible.get(contact['kind'], True):
                    continue
                if self._obstruction_key([contact['residue']]) not in self._contact_highlights:
                    continue  # hiding a residue also hides its attached contacts
                _, color, dashed = STYLES[contact['kind']]
                rgb = tuple(int(color[i:i+2], 16) / 255 for i in (1, 3, 5))
                start, end = contact['start'], contact['end']
                length = math.dist(start, end)
                if length < 1e-6:
                    continue
                steps = max(1, math.ceil(length / 0.55)) if dashed else 1
                for step in range(steps):
                    t0, t1 = step / steps, min(1, (step + (0.65 if dashed else 1)) / steps)
                    a = tuple(start[i] + t0 * (end[i] - start[i]) for i in range(3))
                    b = tuple(start[i] + t1 * (end[i] - start[i]) for i in range(3))
                    # Cylinders stay legible on drivers that clamp GL line width
                    # to one pixel. Colors/endpoints remain those from PLIP.
                    lines.extend([cgo.CYLINDER, *a, *b, 0.12, *rgb, *rgb])
        if lines:
            # state=0 (PyMOL's default) APPENDS a geometry state. The viewer
            # stays on state 1, making type toggles appear all-or-none. Replace
            # the displayed state instead, without accumulating stale geometry.
            self.cmd.load_cgo(lines, 'du_review_plip_contacts', state=1, zoom=0)
            self.cmd.enable('du_review_plip_contacts')
        else:
            self.cmd.disable('du_review_plip_contacts')
        self.widget.update()

    def show_evidence_ligand(self, path: Path | str, receptor_path: Path | str | None = None):
        return self.show_evidence_ligands([path], receptor_path)

    def show_evidence_ligands(self, paths: list[Path | str], receptor_path: Path | str | None = None):
        ligands = [Path(path).resolve() for path in paths]
        if not ligands or any(not path.is_file() or path.suffix.lower() != ".pdb" for path in ligands):
            raise FileNotFoundError("Evidence comparison requires existing retained PDB ligands")
        self.sync_evidence_ligands(ligands)
        self.frame_evidence_ligands(ligands)
        self.evidence_ligand = ligands[-1]
        return {"paths": [str(path) for path in ligands]}

    def frame_evidence_ligands(self, paths):
        names = [f"du_evidence_{hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()[:12]}"
                 for path in paths]
        if names:
            selection = ' or '.join(names)
            if self.cmd.count_atoms(selection):
                self.cmd.zoom(selection, buffer=2, complete=0, animate=0)
                self.expand_scene_clipping()
                self.widget.update()

    def label_evidence_ligands(self, records, visible):
        """Label the selected retained ligand objects with their compound names."""
        objects = set(self.cmd.get_names('objects'))
        for path, label in records:
            name = f"du_evidence_{hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()[:12]}"
            if name not in objects:
                continue
            selection = f'first ({name})'
            self.cmd.label(selection, repr(str(label)) if visible else '""')
            (self.cmd.show if visible else self.cmd.hide)('labels', selection)
            if visible:
                self._style_site_label(name)
        self.widget.update()

    def label_pockets(self, numbers, visible):
        """Label displayed pocket surfaces without altering their colors."""
        objects = set(self.cmd.get_names('objects'))
        for number in numbers:
            name = f'du_pocket_space_{int(number)}'
            if name not in objects:
                continue
            selection = f'first ({name})'
            self.cmd.label(selection, repr(f'P{int(number)}') if visible else '""')
            (self.cmd.show if visible else self.cmd.hide)('labels', selection)
            if visible:
                self._style_site_label(name)
        self.widget.update()

    def _style_site_label(self, name):
        # Distribute labels around their anchors instead of assigning every
        # label the same offset. This reduces collisions in crowded views.
        offsets = ((3.0, 2.5), (-3.0, 2.5), (3.0, -2.5), (-3.0, -2.5),
                   (0.0, 3.5), (0.0, -3.5), (4.0, 0.5), (-4.0, 0.5))
        offset = offsets[int(hashlib.sha256(name.encode()).hexdigest()[:8], 16) % len(offsets)]
        self.cmd.set('label_color', 'black', name)
        self.cmd.set('label_font_id', 7, name)
        self.cmd.set('label_size', 25, name)
        self.cmd.set('label_bg_color', 'white', name)
        self.cmd.set('label_bg_transparency', 0.15, name)
        self.cmd.set('label_padding', [0.16, 0.12, 0], name)
        self.cmd.set('label_outline_color', 'white', name)
        self.cmd.set('label_position', [offset[0], offset[1], 2.0], name)
        self.cmd.set('label_connector', 0, name)
        self.cmd.set('float_labels', 1)

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
        self.expand_scene_clipping()
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

    def frame_receptor_overview(self) -> bool:
        selection = 'polymer and enabled'
        if 'du_receptor' in self.cmd.get_names('objects', enabled_only=1):
            selection = 'du_receptor and polymer'
        if not self.cmd.count_atoms(selection):
            return False
        self.cmd.zoom(selection, buffer=3, complete=0, animate=0)
        width, height = self.cmd.get_viewport()
        if width > 0 and height > 0 and self.cmd.get_setting_int('orthoscopic'):
            # PyMOL's orthographic zoom uses depth and vertical field of view.
            # Fit the receptor's camera-space rectangle instead of its sphere.
            view = list(self.cmd.get_view())
            rotation = (view[0:3], view[3:6], view[6:9])
            projected = (self.cmd.get_coords(selection) - view[12:15]) @ rotation
            low = projected.min(axis=0)
            high = projected.max(axis=0)
            required_height = max(high[1] - low[1] + 4, (high[0] - low[0] + 4) * height / width)
            half_angle = math.radians(self.cmd.get_setting_float('field_of_view') / 2)
            distance = required_height / (2 * 0.95 * math.tan(half_angle))
            old_distance = -view[11]
            view[9] = -float(low[0] + high[0]) / 2
            view[10] = -float(low[1] + high[1]) / 2
            view[11] = -distance
            view[15] = max(1.0, view[15] + distance - old_distance)
            view[16] = max(view[15] + 1.0, view[16] + distance - old_distance)
            self.cmd.set_view(view)
        self.expand_scene_clipping()
        self.widget.update()
        return True

    def _frame_whole_protein(self) -> None:
        selection = self._protein_selection()
        if self.cmd.count_atoms(selection):
            self.cmd.orient(selection, animate=0)
            self.cmd.zoom(selection, buffer=8, complete=1, animate=0)
        self.expand_scene_clipping()

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
