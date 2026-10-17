import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from docking_universal.gui.linked_pose_review import (
    pose_view, control_view, interaction_contacts, comparison_summary, write_comparison_report,
)


class LinkedIdentityTests(unittest.TestCase):
    def test_global_closest_control_diagram_links_exact_pose_and_rank_color(self):
        from docking_universal.pose_visuals import write_pose_view
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            diagram, ligand, receptor, xml = [root / name for name in
                ('control_lowest_rmsd_plip2d.png', 'best_rmsd_pose.sdf', 'receptor.pdb', 'report.xml')]
            for path in (diagram, ligand, receptor, xml):
                path.write_text(path.name)
            self.assertIsNone(pose_view(diagram))
            write_pose_view(diagram, ligand, receptor, xml, 'Global lowest experimental-RMSD pose', 'red', pose_id=38)
            view = pose_view(diagram)
            self.assertEqual(view.ligand, ligand.resolve())
            self.assertEqual(view.ligand_color, 'red')
            ligand.write_text('another pose')
            self.assertIsNone(pose_view(diagram))

    def test_residue_outlines_match_clicks_at_fit_zoom_and_high_dpi(self):
        from docking_universal.gui.qt import QtCore, QtGui, QtWidgets
        from docking_universal.gui.linked_pose_review import FittedDiagramLabel
        from PyQt6.QtTest import QTest
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        label = FittedDiagramLabel()
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        residue = {'name': 'ASP', 'chain': 'A', 'number': '30'}
        label.hit_regions = [{'residue': residue, 'rect': [.2, .3, .3, .1]}]
        clicked = []
        label.residueActivated.connect(clicked.append)
        label.show()
        for width, height, dpr in ((300, 200, 1), (900, 600, 1), (600, 400, 2)):
            source = QtGui.QPixmap(width, height)
            source.fill(QtGui.QColor('white'))
            source.setDevicePixelRatio(dpr)
            label.setPixmap(source)
            label.resize(int(width / dpr + 80), int(height / dpr + 60))
            app.processEvents()
            hit, rect = label.residue_boxes()[0]
            self.assertEqual(hit['residue'], residue)
            self.assertAlmostEqual(rect.x(), 40 + .2 * width / dpr)
            self.assertAlmostEqual(rect.y(), 30 + .3 * height / dpr)
            self.assertAlmostEqual(rect.width(), .3 * width / dpr)
            QTest.mouseClick(label, QtCore.Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
            self.assertEqual(clicked[-1], residue)
            rendered = label.grab().toImage()
            # Border is a widget overlay, not a change to source image pixels.
            edge = QtCore.QPointF(rect.center().x(), rect.top()).toPoint()
            sample = rendered.pixelColor(int(edge.x() * rendered.devicePixelRatio()),
                                         int(edge.y() * rendered.devicePixelRatio()))
            self.assertNotEqual(sample, QtGui.QColor('white'))
            self.assertEqual(source.toImage().pixelColor(width // 2, height // 2), QtGui.QColor('white'))
        label.hit_regions = []
        self.assertEqual(label.residue_boxes(), [])
        label.close()

    def test_experimental_coordinates_are_not_described_as_docked(self):
        from docking_universal.gui.qt import QtWidgets
        from docking_universal.gui.linked_pose_review import LinkedPosePanel, PoseView
        from docking_universal.gui.interaction_review_window import InteractionReviewWindow
        from unittest.mock import Mock
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        with TemporaryDirectory() as directory:
            xml = Path(directory) / 'report.xml'
            xml.write_text('<report><bindingsite><interactions/></bindingsite></report>')
            for label, kind, experimental in (
                ('Experimental control ligand', 'unknown', True),
                ('2R5P · deposited interactions', 'unknown', True),
                ('MK1', 'experimental', True),
                ('Global lowest experimental-RMSD pose', 'docked', False),
                ('Unspecified legacy view', 'unknown', False),
            ):
                view = PoseView(xml, xml, xml, xml, label, coordinate_kind=kind)
                adapter = Mock()
                adapter.show_review_contacts.return_value = {}
                panel = LinkedPosePanel()
                window = InteractionReviewWindow(view, panel, QtWidgets.QWidget(), adapter)
                self.assertEqual(view.experimental, experimental)
                if experimental:
                    self.assertIn('Experimental structure only — not a docked pose', window.basis.text())
                    self.assertIn('PLIP contacts are calculated', window.basis.text())
                elif kind == 'docked':
                    self.assertTrue(window.basis.text().startswith('Docked pose'))
                else:
                    self.assertIn('source kind is not recorded', window.basis.text())
                self.assertIn('no verified residue links', panel.status.text())
                window.dispose()
                window.close()

    def test_hit_regions_require_exact_image_report_and_residue_identity(self):
        import hashlib
        import json
        from docking_universal.gui.linked_pose_review import diagram_hit_regions, contact_residues
        with TemporaryDirectory() as directory:
            root = Path(directory)
            image, xml = root / 'image.png', root / 'report.xml'
            image.write_bytes(b'image')
            xml.write_text('<report><bindingsite><interactions><hydrogen_bonds><hydrogen_bond>'
                           '<restype>ASP</restype><reschain>B</reschain><resnr>30</resnr>'
                           '</hydrogen_bond></hydrogen_bonds></interactions></bindingsite></report>')
            view = SimpleNamespace(diagram=image, interactions=xml)
            residue = {'name': 'ASP', 'chain': 'B', 'number': '30'}
            self.assertEqual(contact_residues(view), [residue])
            record = {'image_sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
                      'plip_sha256': hashlib.sha256(xml.read_bytes()).hexdigest(),
                      'regions': [{'residue': residue, 'rect': [0.1, 0.2, 0.2, 0.1]},
                                  {'residue': dict(residue, chain='A'), 'rect': [0.1, 0.2, 0.2, 0.1]}]}
            Path(str(image) + '.hit-regions.json').write_text(json.dumps(record))
            self.assertEqual(len(diagram_hit_regions(view)), 1)
            image.write_bytes(b'changed')
            self.assertEqual(diagram_hit_regions(view), [])
            image.write_bytes(b'image')
            xml.write_text('<report><bindingsite/></report>')
            self.assertEqual(diagram_hit_regions(view), [])

    def test_diagram_centers_and_checkboxes_alone_toggle_visibility(self):
        from docking_universal.gui.qt import QtWidgets
        from docking_universal.gui.linked_pose_review import LinkedPosePanel, PoseView
        from docking_universal.gui.interaction_review_window import InteractionReviewWindow
        from unittest.mock import Mock
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        with TemporaryDirectory() as directory:
            xml = Path(directory) / 'report.xml'
            xml.write_text('<report><bindingsite><interactions><hydrogen_bonds><hydrogen_bond>'
                           '<restype>ASP</restype><reschain>A</reschain><resnr>30</resnr>'
                           '</hydrogen_bond></hydrogen_bonds></interactions></bindingsite></report>')
            view = PoseView(xml, xml, xml, xml, 'deposited')
            panel, adapter = LinkedPosePanel(), Mock()
            adapter.has_review_residue_labels.return_value = False
            adapter.show_review_contacts.return_value = {
                'hydrogen_bond': ('Hydrogen bond', '#5f92ff', True),
                'hydrophobic_interaction': ('Hydrophobic contact', '#009b49', False),
            }
            window = InteractionReviewWindow(view, panel, QtWidgets.QWidget(), adapter)
            types = window.contact_type_actions
            self.assertTrue(all(b.isChecked() for b in types.values()))
            window.contact_key.linkActivated.emit('hydrogen_bond')
            adapter.set_review_contact_type_visible.assert_called_once_with('hydrogen_bond', False)
            self.assertTrue(types['hydrophobic_interaction'].isChecked())
            window.contacts.setChecked(False)
            window.contacts.setChecked(True)
            self.assertFalse(types['hydrogen_bond'].isChecked())
            self.assertTrue(types['hydrophobic_interaction'].isChecked())
            adapter.center_contact_residue.assert_not_called()
            adapter.center_review_ligand.assert_not_called()
            window.contact_key.linkActivated.emit('hydrogen_bond')
            adapter.set_review_contact_type_visible.assert_called_with('hydrogen_bond', True)
            self.assertIn('2D diagram stays unchanged', window.contact_key.toolTip())
            self.assertIn('href="hydrogen_bond"', window.contact_key.text())
            self.assertNotIn('<s>', window.contact_key.text())
            window.contact_key.linkActivated.emit('hydrogen_bond')
            self.assertIn('<s>Hydrogen bond</s>', window.contact_key.text())
            # Inline key stays within the original two-line legend footprint.
            self.assertLessEqual(window.contact_key.heightForWidth(500), 2 * window.contact_key.fontMetrics().lineSpacing() + 4)
            window.show()
            app.processEvents()
            self.assertLess(window.contact_key.geometry().bottom(), window.cartoon.geometry().top())
            self.assertLess(window.contacts.geometry().bottom(), window.residue_scroll.geometry().top())
            self.assertLess(window.residue_scroll.height(), 68)
            residue = {'name': 'ASP', 'chain': 'A', 'number': '30'}
            button = window.residue_buttons[window.key(residue)]
            self.assertTrue(button.isChecked())
            adapter.set_contact_residue_visible.reset_mock()
            window.clicked_residue(residue)
            adapter.center_contact_residue.assert_called_once_with(residue)
            self.assertTrue(button.isChecked())
            adapter.set_contact_residue_visible.assert_not_called()
            button.setChecked(False)
            adapter.set_contact_residue_visible.assert_called_with(residue, False)
            adapter.set_contact_residue_visible.reset_mock()
            window.clicked_residue(residue)
            self.assertFalse(button.isChecked())
            adapter.set_contact_residue_visible.assert_not_called()
            window.clicked_ligand()
            adapter.center_review_ligand.assert_called_once_with()
            self.assertFalse(button.isChecked())
            button.setChecked(True)
            adapter.set_contact_residue_visible.assert_called_with(residue, True)
            window.dispose()
            window.close()

    def test_residue_label_switch_and_individual_picks_stay_synchronized(self):
        from docking_universal.gui.qt import QtWidgets
        from docking_universal.gui.linked_pose_review import LinkedPosePanel, PoseView
        from docking_universal.gui.interaction_review_window import InteractionReviewWindow
        from unittest.mock import Mock
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        with TemporaryDirectory() as directory:
            xml = Path(directory) / 'report.xml'
            xml.write_text('<report><bindingsite><interactions><hydrogen_bonds><hydrogen_bond>'
                           '<restype>ASP</restype><reschain>A</reschain><resnr>30</resnr>'
                           '</hydrogen_bond></hydrogen_bonds></interactions></bindingsite></report>')
            residue = dict(name='ASP', chain='A', number='30')
            adapter, active = Mock(), set()
            adapter.show_review_contacts.return_value = {}
            def label(r, visible):
                key = InteractionReviewWindow.key(r)
                (active.add if visible else active.discard)(key)
                return visible
            def labels(residues, visible):
                if visible:
                    for r in residues:
                        label(r, True)
                else:
                    active.clear()
                return bool(active)
            adapter.set_review_labels_visible.side_effect = labels
            adapter.set_review_residue_label.side_effect = label
            adapter.has_review_residue_labels.side_effect = lambda: bool(active)
            adapter.toggle_review_residue_label.side_effect = lambda r: label(r, InteractionReviewWindow.key(r) not in active)
            panel = LinkedPosePanel()
            window = InteractionReviewWindow(PoseView(xml, xml, xml, xml, 'deposited'), panel,
                                            QtWidgets.QWidget(), adapter)
            self.assertFalse(window.labels.isChecked())
            window.labels.setChecked(True)
            adapter.set_review_labels_visible.assert_called_once_with([residue], True)
            window.clicked_3d_residue(residue)
            self.assertFalse(window.labels.isChecked())
            self.assertEqual(adapter.set_review_labels_visible.call_count, 1)
            window.clicked_3d_residue(residue)
            self.assertTrue(window.labels.isChecked())
            window.labels.setChecked(False)
            self.assertFalse(active)
            self.assertEqual(adapter.set_review_labels_visible.call_count, 2)
            button = window.residue_buttons[window.key(residue)]
            button.setChecked(False)
            window.labels.setChecked(True)
            adapter.set_review_labels_visible.assert_called_with([], True)
            self.assertFalse(window.labels.isChecked())
            self.assertFalse(button.isChecked())
            adapter.center_contact_residue.assert_not_called()
            adapter.center_review_ligand.assert_not_called()
            window.dispose()
            window.close()

    def test_boxed_ligand_heading_centers_exact_docked_pose_without_changing_diagram(self):
        from docking_universal.gui.qt import QtWidgets, QtGui
        from docking_universal.gui.linked_pose_review import LinkedPosePanel, PoseView
        from docking_universal.gui.interaction_review_window import InteractionReviewWindow
        from unittest.mock import Mock
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sdf, image, xml = root / 'pose.sdf', root / 'diagram.png', root / 'report.xml'
            sdf.write_text('PYR\n')
            source = QtGui.QPixmap(600, 600)
            source.fill(QtGui.QColor('white'))
            source.save(str(image))
            xml.write_text('<report><bindingsite><interactions/></bindingsite></report>')
            panel, adapter = LinkedPosePanel(), Mock()
            adapter.show_review_contacts.return_value = {}
            view = PoseView(sdf, xml, image, xml, 'Docked pose 3')
            panel.set_pose(view)
            window = InteractionReviewWindow(view, panel, QtWidgets.QWidget(), adapter)
            window.show()
            app.processEvents()
            before = panel.query_image.pixmap().size()
            self.assertIn('PYR', panel.heading.text())
            self.assertIn('Center ligand', panel.heading.text())
            panel.heading.click()
            adapter.center_review_ligand.assert_called_once_with()
            self.assertEqual(panel.query_image.pixmap().size(), before)
            self.assertFalse('experimental-source' in window.basis.text().lower())
            window.dispose()
            window.close()

    def test_small_window_zoom_scrolls_without_cropping_source(self):
        from docking_universal.gui.qt import QtWidgets, QtGui
        from docking_universal.gui.linked_pose_review import LinkedPosePanel, PoseView
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        with TemporaryDirectory() as directory:
            image = Path(directory) / "diagram.png"
            source = QtGui.QPixmap(1800, 1200)
            source.fill(QtGui.QColor("white"))
            source.save(str(image))
            panel = LinkedPosePanel()
            panel.resize(440, 380)
            panel.show()
            panel.set_pose(PoseView(image, image, image, image, "Deposited ligand"))
            app.processEvents()
            panel.zoom_diagram(1.0)
            app.processEvents()
            self.assertEqual(panel.query_image.pixmap().size(), source.size())
            self.assertGreater(panel._scrolls[panel.query_image].horizontalScrollBar().maximum(), 0)
            self.assertTrue(panel.compare.isHidden())
            panel.fit_diagram()
            app.processEvents()
            self.assertLessEqual(panel.query_image.width(), panel._scrolls[panel.query_image].viewport().width())
            panel.close()

    def test_cluster_and_exact_pose_use_their_own_coordinates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "receptor.pdb").write_text("receptor")
            cluster = root / "cluster_031"
            (cluster / "interactions").mkdir(parents=True)
            image = cluster / "interactions" / "representative_plip2d.png"
            image.write_bytes(b"image")
            (cluster / "representative.sdf").write_text("representative")
            self.assertEqual(pose_view(image).ligand, (cluster / "representative.sdf").resolve())
            cache = root / "pose_interactions" / "pose_0099"
            cache.mkdir(parents=True)
            exact = cache / "interaction_diagram.png"
            exact.write_bytes(b"image")
            self.assertIsNone(pose_view(exact))
            (cache / "pose.sdf").write_text("different exact pose")
            self.assertEqual(pose_view(exact).ligand, (cache / "pose.sdf").resolve())

    def test_comparison_keeps_chain_and_contact_class_distinct(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            def write(name, chain):
                path = root / name
                path.write_text(f"<report><bindingsite><interactions><hydrogen_bonds><hydrogen_bond>"
                                f"<restype>TYR</restype><reschain>{chain}</reschain><resnr>181</resnr>"
                                "</hydrogen_bond></hydrogen_bonds></interactions></bindingsite></report>")
                return SimpleNamespace(interactions=path, diagram=path)
            query, reference = write("query.xml", "A"), write("reference.xml", "B")
            summary = comparison_summary(query, reference)
            self.assertIn("Shared: none", summary)
            self.assertIn("Control only: TYR B:181", summary)
            self.assertIn("Docked only: TYR A:181", summary)
            output = root / "report.html"
            write_comparison_report(output, query, reference, query.diagram, reference.diagram)
            self.assertIn("data:image/png;base64,", output.read_text())
            self.assertIn("chemically valid atom correspondence", output.read_text())
            query.interactions.write_text("<report><bindingsite/><bindingsite/></report>")
            with self.assertRaises(ValueError):
                interaction_contacts(query.interactions)

    def test_control_requires_experimental_coordinates_and_specific_retained_layout(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            state = SimpleNamespace(workflow_data={"latest_control_output": str(root)})
            self.assertIsNone(control_view(state))
            (root / "00_inputs").mkdir()
            (root / "00_inputs" / "LIG_experimental.sdf").write_text("experimental")
            (root / "report" / "control_pose_analysis").mkdir(parents=True)
            (root / "report" / "control_pose_analysis" / "receptor.pdb").write_text("receptor")
            (root / "report" / "control_experimental_plip2d.png").write_bytes(b"image")
            self.assertEqual(control_view(state).label, "Experimental control ligand")
            (root / "00_inputs" / "OTHER_experimental.sdf").write_text("ambiguous")
            self.assertIsNone(control_view(state))
