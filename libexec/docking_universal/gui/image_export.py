"""Local, presentation-only PNG exports; never rewrite scientific inputs."""
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from .qt import QtCore, QtGui, QtWidgets


class ExportCancelled(Exception):
    """User cancelled a visual render; never publish a partial image."""


class _RayCapture(QtCore.QThread):
    def __init__(self, cmd):
        super().__init__()
        self.cmd = cmd
        self.cancelled = False
        self.image = None
        self.error = None

    def run(self):
        try:
            with TemporaryDirectory(prefix='du-ray-export-') as directory:
                path = Path(directory) / 'view.png'
                if not self.cancelled:
                    # CPU ray tracing needs no GL context; run off the GUI thread.
                    self.cmd.png(str(path), ray=1, prior=0, quiet=1)
                if not self.cancelled:
                    self.image = QtGui.QImage(str(path)).copy()
                    if self.image.isNull():
                        raise ValueError('PyMOL did not produce a valid ray-traced PNG.')
        except Exception as exc:
            self.error = exc


def _ray_image(viewer):
    application = QtWidgets.QApplication.instance()
    if application is None or QtCore.QThread.currentThread() != application.thread():
        raise ValueError('Start ray image exports from the Qt GUI thread.')
    if getattr(viewer, '_du_ray_export_active', False):
        raise ValueError('A ray-traced export is already running in this PyMOL session.')
    worker = _RayCapture(viewer.cmd)

    class RayProgress(QtWidgets.QDialog):
        def cancel_render(self):
            worker.cancelled = True
            self.message.setText('Cancelling ray-traced image…')
            self.cancel.setEnabled(False)
            viewer.cmd.interrupt()  # upstream asynchronous, lock-free abort

        def reject(self):
            self.cancel_render()  # stay open until native rendering has stopped

        def closeEvent(self, event):
            if worker.isRunning():
                self.cancel_render()
                event.ignore()
            else:
                event.accept()

    progress = RayProgress(viewer.window())
    progress.setWindowTitle('Rendering ray-traced image')
    progress.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
    layout = QtWidgets.QVBoxLayout(progress)
    progress.message = QtWidgets.QLabel('Ray-tracing the current PyMOL view…\nThis may take longer. Docking and PLIP are not rerun.')
    layout.addWidget(progress.message)
    bar = QtWidgets.QProgressBar()
    bar.setRange(0, 0)
    layout.addWidget(bar)
    progress.cancel = QtWidgets.QPushButton('Cancel')
    progress.cancel.clicked.connect(progress.cancel_render)
    layout.addWidget(progress.cancel)
    worker.finished.connect(progress.accept)
    application.aboutToQuit.connect(progress.cancel_render)
    viewer._du_ray_export_active = True
    try:
        worker.start()
        progress.exec()
        worker.wait()
        if worker.cancelled:
            raise ExportCancelled()
        if worker.error:
            raise worker.error
        return worker.image
    finally:
        application.aboutToQuit.disconnect(progress.cancel_render)
        viewer._du_ray_export_active = False
        progress.deleteLater()



@dataclass
class ImageExport:
    image: QtGui.QImage
    context: dict
    protected_paths: tuple = ()

    def save(self, destination):
        destination = Path(destination)
        if destination.suffix.lower() != '.png':
            raise ValueError('Choose a PNG filename.')
        if destination.resolve() in {Path(p).resolve() for p in self.protected_paths}:
            raise ValueError('Export to a new filename; retained study files cannot be replaced.')
        if self.image.isNull():
            raise ValueError('No rendered image is available to save.')
        image = self.image.copy()
        image.setText('Docking Universal export', json.dumps(self.context, sort_keys=True))
        # Atomic replacement: an encoding/write failure leaves an existing file intact.
        output = QtCore.QSaveFile(str(destination))
        if not output.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
            raise OSError(output.errorString())
        if not image.save(output, 'PNG'):
            output.cancelWriting()
            raise OSError('PNG encoding failed; the destination was not replaced.')
        if not output.commit():
            raise OSError(output.errorString())
        return destination


def capture_pymol_image(viewer, *, ray=False):
    """Use native PNG rendering, excluding Qt controls and the PyMOL object GUI."""
    if viewer is None or not hasattr(viewer, 'cmd'):
        raise ValueError('The embedded PyMOL view is not available.')
    if ray:
        return _ray_image(viewer)
    with TemporaryDirectory(prefix='du-image-export-') as directory:
        path = Path(directory) / 'view.png'
        # Explicit prior=0 avoids exporting a stale earlier ray/render buffer.
        # No ray tracing, representation changes, camera moves or new engine.
        # The upstream widget context manager makes the actual GL context
        # current and marks it valid for PyMOL's native export API.
        with viewer:
            viewer.cmd.png(str(path), ray=0, prior=0, quiet=1)
        image = QtGui.QImage(str(path))
        if image.isNull():
            raise ValueError('PyMOL did not produce a valid current-view PNG.')
        return image.copy()


def diagram_export(view):
    if view is None:
        raise ValueError('Select a retained 2D diagram first.')
    path = Path(view.diagram)
    image = QtGui.QImage(str(path))
    if image.isNull():
        raise ValueError('The selected retained diagram cannot be decoded.')
    return ImageExport(image, {
        'kind': 'retained_2d_diagram', 'label': view.label,
        'coordinate_kind': 'experimental' if view.experimental else view.coordinate_kind,
        'source_diagram': str(path.resolve()), 'source_resolution': [image.width(), image.height()],
        'note': 'Original-resolution retained diagram; no recalculation or UI click outlines.'},
        tuple(p for p in (view.diagram, view.ligand, view.receptor, view.interactions) if p))


def pymol_export(viewer, context=None, protected_paths=(), *, ray=False):
    image = capture_pymol_image(viewer, ray=ray)
    return ImageExport(image, dict(context or {}, kind='custom_pymol_view',
        camera=list(viewer.cmd.get_view()),
        rendering='ray_traced' if ray else 'opengl',
        note='Current customized native PyMOL view; not a regenerated scientific report.'), protected_paths)


def paired_export(view, viewer, legend, *, ray=False):
    """Clean image panels, not a screenshot of buttons, scrollbars or checkboxes."""
    diagram = diagram_export(view)
    scene = capture_pymol_image(viewer, ray=ray)
    height = scene.height()
    left = diagram.image.scaledToHeight(height, QtCore.Qt.TransformationMode.SmoothTransformation)
    gap, margin = 28, 28
    width = left.width() + scene.width() + gap + 2 * margin
    font = QtGui.QFont()
    font.setPixelSize(22)
    metrics = QtGui.QFontMetrics(font)
    basis = ('Experimental structure — PLIP contacts from deposited coordinates; not a docked pose.'
             if view.experimental else
             'Docked pose — PLIP contacts from this exact retained docking pose.'
             if view.coordinate_kind == 'docked' else 'Retained coordinates — source kind unspecified.')
    caption = view.label + '\n' + basis
    caption_height = metrics.boundingRect(QtCore.QRect(0, 0, width - 2 * margin, 10000),
        QtCore.Qt.TextFlag.TextWordWrap, caption).height() + 2 * margin
    # A clean, color-matched key for only the contact types currently shown in 3D.
    key_items, x, y = [], margin, margin
    for name, color in legend:
        item_width = metrics.horizontalAdvance(name) + 54
        if x + item_width > width - margin and x > margin:
            x, y = margin, y + metrics.height() + 12
        key_items.append((name, color, x, y))
        x += item_width
    legend_height = y + metrics.height() + margin
    image = QtGui.QImage(width, caption_height + height + legend_height,
                         QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor('white'))
    painter = QtGui.QPainter(image)
    painter.setFont(font)
    painter.setPen(QtGui.QColor('black'))
    painter.drawText(QtCore.QRect(margin, margin, width - 2 * margin, caption_height - margin),
                     QtCore.Qt.TextFlag.TextWordWrap, caption)
    painter.drawImage(margin, caption_height, left)
    painter.drawImage(margin + left.width() + gap, caption_height, scene)
    if key_items:
        for name, color, x, y in key_items:
            top = caption_height + height + y
            painter.fillRect(x, top + 4, 18, 18, QtGui.QColor(color))
            painter.drawText(x + 26, top + metrics.ascent(), name)
    else:
        painter.drawText(margin, caption_height + height + margin + metrics.ascent(), '3D contacts hidden')
    painter.end()
    context = dict(diagram.context, kind='custom_paired_panel',
                   camera=list(viewer.cmd.get_view()), visible_3d_contacts=legend,
                   rendering_3d='ray_traced' if ray else 'opengl',
                   note='Custom visual export; not a regenerated scientific report.')
    return ImageExport(image, context, diagram.protected_paths)


def export_dialog(parent, label, prepare):
    location = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.PicturesLocation)
    destination, _ = QtWidgets.QFileDialog.getSaveFileName(
        parent, 'Save ' + label, str(Path(location) / 'docking-universal-image.png'), 'PNG image (*.png)')
    if not destination:
        return None
    path = Path(destination)
    if not path.suffix:
        path = path.with_suffix('.png')
        # The static native dialog may have confirmed the extensionless name,
        # not this final PNG destination. Never overwrite that file silently.
        if path.exists() and QtWidgets.QMessageBox.question(
                parent, 'Replace image?', f'{path.name} already exists. Replace it?',
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No) != QtWidgets.QMessageBox.StandardButton.Yes:
            return None
    try:
        result = prepare().save(path)
    except ExportCancelled:
        return None
    except Exception as exc:
        QtWidgets.QMessageBox.warning(parent, 'Image export failed', str(exc))
        return None
    if hasattr(parent, 'statusBar'):
        parent.statusBar().showMessage(f'Saved image: {result}', 10000)
    elif hasattr(parent, 'status'):
        parent.status.setText(f'Saved image: {result}')
    return result


def save_image_button(parent, sources):
    """One compact menu; sources are (label, available callback, prepare callback)."""
    button = QtWidgets.QToolButton(parent)
    button.setObjectName('save_review_image')
    button.setText('Save image…')
    button.setToolTip('Save a local PNG of the current view or retained figure; no scientific recalculation.')
    button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
    menu = QtWidgets.QMenu(button)
    actions = []
    for label, available, prepare in sources:
        action = menu.addAction(label)
        action.triggered.connect(lambda _checked=False, name=label, make=prepare: export_dialog(parent, name, make))
        actions.append((action, available))
    menu.aboutToShow.connect(lambda: [action.setEnabled(bool(available())) for action, available in actions])
    button.setMenu(menu)
    return button
