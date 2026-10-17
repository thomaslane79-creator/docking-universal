import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, MagicMock, patch

from docking_universal.gui.qt import QtCore, QtGui, QtWidgets
from docking_universal.gui.image_export import (
    ImageExport, capture_pymol_image, diagram_export, paired_export, export_dialog, save_image_button,
    ExportCancelled, pymol_export,
)
from docking_universal.gui.linked_pose_review import PoseView


class ImageExportTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def image(self):
        image = QtGui.QImage(640, 480, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor('blue'))
        return image

    def test_save_preserves_pixels_and_embeds_source_context(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'export.png'
            source = self.image()
            metadata = {'kind': 'custom_pymol_view', 'coordinate_kind': 'experimental'}
            ImageExport(source, metadata).save(path)
            exported = QtGui.QImage(str(path))
            self.assertEqual(exported.size(), source.size())
            self.assertEqual(exported.pixelColor(400, 300), source.pixelColor(400, 300))
            self.assertEqual(json.loads(exported.text('Docking Universal export')), metadata)
            self.assertFalse(source.text('Docking Universal export'))

    def test_invalid_export_cannot_replace_retained_source_or_existing_file(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'retained.png'
            source.write_bytes(b'original')
            with self.assertRaises(ValueError):
                ImageExport(self.image(), {}, (source,)).save(source)
            with self.assertRaises(ValueError):
                ImageExport(QtGui.QImage(), {}).save(source)
            with self.assertRaises(ValueError):
                ImageExport(self.image(), {}).save(root / 'wrong.jpg')
            self.assertEqual(source.read_bytes(), b'original')
            with patch.object(QtGui.QImage, 'save', return_value=False):
                with self.assertRaises(OSError):
                    ImageExport(self.image(), {}).save(source)
            self.assertEqual(source.read_bytes(), b'original')

    def test_original_resolution_diagram_and_clean_pair_are_independent_of_fit(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'diagram.png'
            self.image().save(str(path))
            original = path.read_bytes()
            view = PoseView(path, path, path, path, 'Experimental control ligand', coordinate_kind='experimental')
            diagram = diagram_export(view)
            self.assertEqual(diagram.image.size(), self.image().size())
            self.assertEqual(diagram.context['coordinate_kind'], 'experimental')
            viewer = Mock()
            viewer.cmd.get_view.return_value = list(range(18))
            with patch('docking_universal.gui.image_export.capture_pymol_image', return_value=self.image()):
                pair = paired_export(view, viewer, [('Hydrogen bond', '#5f92ff')])
            self.assertGreater(pair.image.width(), diagram.image.width())
            self.assertEqual(pair.context['camera'], list(range(18)))
            self.assertEqual(path.read_bytes(), original)

    def test_native_capture_requests_fresh_nonray_image_not_old_buffer(self):
        viewer = MagicMock()
        def png(path, **kwargs):
            self.image().save(str(path))
        viewer.cmd.png.side_effect = png
        image = capture_pymol_image(viewer)
        self.assertFalse(image.isNull())
        self.assertEqual(viewer.cmd.png.call_args.kwargs, {'ray': 0, 'prior': 0, 'quiet': 1})
        viewer.cmd.set_view.assert_not_called()
        viewer.cmd.load.assert_not_called()
        with self.assertRaises(ValueError):
            capture_pymol_image(None)

    def test_optional_ray_export_uses_cpu_worker_and_records_rendering_kind(self):
        import threading
        viewer = QtWidgets.QWidget()
        viewer.cmd = Mock()
        viewer.cmd.get_view.return_value = list(range(18))
        main_thread = threading.get_ident()
        worker_threads = []
        def png(path, **kwargs):
            self.assertEqual(kwargs, {'ray': 1, 'prior': 0, 'quiet': 1})
            worker_threads.append(threading.get_ident())
            self.image().save(str(path))
        viewer.cmd.png.side_effect = png
        exported = pymol_export(viewer, ray=True)
        self.assertFalse(exported.image.isNull())
        self.assertEqual(exported.context['rendering'], 'ray_traced')
        self.assertNotEqual(worker_threads[0], main_thread)
        self.assertFalse(viewer._du_ray_export_active)
        viewer.cmd.set_view.assert_not_called()
        viewer.close()

    def test_cancel_interrupts_ray_without_publishing_and_cleans_busy_state(self):
        import threading
        viewer = QtWidgets.QWidget()
        viewer.cmd = Mock()
        release = threading.Event()
        def png(path, **kwargs):
            release.wait(2)
            self.image().save(str(path))
        viewer.cmd.png.side_effect = png
        viewer.cmd.interrupt.side_effect = release.set
        def cancel():
            for widget in self.app.topLevelWidgets():
                if widget.windowTitle() == 'Rendering ray-traced image':
                    widget.reject()
        QtCore.QTimer.singleShot(20, cancel)
        with self.assertRaises(ExportCancelled):
            capture_pymol_image(viewer, ray=True)
        viewer.cmd.interrupt.assert_called_once()
        self.assertFalse(viewer._du_ray_export_active)
        viewer.close()

    def test_ray_failure_is_reported_and_no_stale_image_used(self):
        viewer = QtWidgets.QWidget()
        viewer.cmd = Mock()
        viewer.cmd.png.side_effect = RuntimeError('ray failed')
        with self.assertRaisesRegex(RuntimeError, 'ray failed'):
            capture_pymol_image(viewer, ray=True)
        self.assertFalse(viewer._du_ray_export_active)
        viewer.close()

    def test_cancelled_ray_save_leaves_existing_destination_untouched(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'existing.png'
            path.write_bytes(b'previous')
            parent = QtWidgets.QWidget()
            with patch.object(QtWidgets.QFileDialog, 'getSaveFileName', return_value=(str(path), '')), \
                    patch.object(QtWidgets.QMessageBox, 'warning') as warning:
                self.assertIsNone(export_dialog(parent, 'ray', Mock(side_effect=ExportCancelled)))
            self.assertFalse(warning.called)
            self.assertEqual(path.read_bytes(), b'previous')
            parent.close()

    def test_cancel_does_not_capture_or_save_and_menu_gates_missing_sources(self):
        parent, prepare = QtWidgets.QWidget(), Mock()
        with patch.object(QtWidgets.QFileDialog, 'getSaveFileName', return_value=('', '')):
            self.assertIsNone(export_dialog(parent, '3D view', prepare))
        prepare.assert_not_called()
        button = save_image_button(parent, [('Unavailable 2D', lambda: False, prepare),
                                            ('Ready 3D', lambda: True, prepare)])
        button.menu().aboutToShow.emit()
        self.assertFalse(button.menu().actions()[0].isEnabled())
        self.assertTrue(button.menu().actions()[1].isEnabled())
        parent.close()

    def test_appending_png_requires_confirmation_for_an_existing_destination(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'custom.png'
            path.write_bytes(b'previous image')
            parent, prepare = QtWidgets.QWidget(), Mock()
            with patch.object(QtWidgets.QFileDialog, 'getSaveFileName', return_value=(str(path.with_suffix('')), '')), \
                    patch.object(QtWidgets.QMessageBox, 'question', return_value=QtWidgets.QMessageBox.StandardButton.No):
                self.assertIsNone(export_dialog(parent, '3D view', prepare))
            prepare.assert_not_called()
            self.assertEqual(path.read_bytes(), b'previous image')
            parent.close()
