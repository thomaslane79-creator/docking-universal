import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from docking_universal.gui.qt import QtWidgets
from docking_universal.gui.cluster_contacts import ClusterContactControls
from docking_universal.gui.linked_pose_review import PoseView
from docking_universal.viewer.embedded_pymol import EmbeddedPymolAdapter
from docking_universal.viewer.plip_contacts import STYLES
from tests.test_embedded_pymol_adapter import FakeWidget


class ClusterContactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_compact_key_independently_toggles_only_3d_and_resets_for_new_cluster(self):
        adapter = Mock()
        controls = ClusterContactControls(adapter)
        residues = [dict(name='ASP', chain='A', number='30')]
        styles = {k: STYLES[k] for k in ('hydrogen_bond', 'hydrophobic_interaction')}
        controls.set_contacts(styles, residues)
        self.assertFalse(controls.isHidden())
        adapter.set_review_contacts_visible.assert_not_called()
        button = controls.types.buttons['hydrogen_bond']
        self.assertEqual(button.text(), 'Hydrogen bond')
        self.assertIn('2D diagram stays unchanged', button.toolTip())
        button.click()
        adapter.set_review_contact_type_visible.assert_called_once_with('hydrogen_bond', False)
        self.assertTrue(controls.visible_types['hydrophobic_interaction'])
        controls.contacts.setChecked(False)
        adapter.set_review_contacts_visible.assert_called_once_with(False)
        self.assertFalse(button.isEnabled())
        controls.contacts.setChecked(True)
        self.assertFalse(button.isChecked())
        controls.labels.setChecked(True)
        adapter.set_review_labels_visible.assert_called_once_with(residues, True)
        controls.set_contacts({'salt_bridge': STYLES['salt_bridge']}, [])
        self.assertEqual(controls.visible_types, {'salt_bridge': True})
        self.assertNotIn('hydrogen_bond', controls.types.buttons)
        self.assertTrue(controls.contacts.isChecked())
        self.assertFalse(controls.labels.isChecked())
        controls.unavailable('Missing exact report')
        self.assertFalse(controls.contacts.isEnabled())
        self.assertEqual(controls.key.text(), 'Missing exact report')
        controls.close()

    def test_native_display_scale_does_not_restore_a_headless_sessions_tiny_gui_or_change_camera(self):
        from docking_universal.viewer.scene_style import apply_native_display_scale
        widget = FakeWidget()
        widget.devicePixelRatioF = lambda: 2.
        widget.cmd.set = Mock()
        camera = widget.cmd.get_view()
        apply_native_display_scale(widget)
        widget.cmd.set.assert_called_once_with('display_scale_factor', 2)
        self.assertEqual(widget.cmd.get_view(), camera)
        widget.cmd.set.reset_mock()
        widget.devicePixelRatioF = lambda: 1.
        apply_native_display_scale(widget)
        widget.cmd.set.assert_called_once_with('display_scale_factor', 1)

    def test_textured_text_is_limited_to_the_native_mac_retina_full_interface(self):
        from docking_universal.viewer.scene_style import apply_native_display_scale
        widget = FakeWidget()
        widget.devicePixelRatioF = lambda: 2.
        widget.cmd.set = Mock()
        camera = widget.cmd.get_view()
        for system, full, expected in [('darwin',True,True), ('darwin',False,False),
                                       ('win32',True,False), ('linux',True,False)]:
            widget._du_full_interface = full
            widget.cmd.set.reset_mock()
            apply_native_display_scale(widget, system=system)
            self.assertEqual(('use_shaders',1) in [call.args for call in widget.cmd.set.call_args_list], expected)
            widget.cmd.set.assert_any_call('display_scale_factor', 2)
            self.assertEqual(widget.cmd.get_view(), camera)

    def test_cluster_switch_maps_exact_residues_and_clears_old_contacts_without_camera_change(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            receptor, ligand = root / 'receptor.pdb', root / 'pose.sdf'
            receptor.write_text('retained receptor')
            ligand.write_text('retained ligand')
            widget = FakeWidget()
            adapter = EmbeddedPymolAdapter(widget)
            adapter.cmd.get_model = Mock(return_value=SimpleNamespace(atom=[]))
            adapter._contact_residue_atoms = Mock(return_value=[])
            adapter.set_contact_residue_visible = Mock()
            adapter.show_review_contacts = Mock(return_value={'hydrogen_bond': STYLES['hydrogen_bond']})
            adapter.focus_interaction_review = Mock()
            view = PoseView(ligand, receptor, root / 'diagram.png', root / 'report.xml', 'Docked representative')
            residue = dict(name='ASP', chain='B', number='25')
            with patch('docking_universal.viewer.plip_contacts.contacts', return_value=[dict(residue=residue)]):
                styles, residues = adapter.show_linked_interactions(view)
            self.assertEqual(residues, [residue])
            adapter._contact_residue_atoms.assert_called_once_with(residue)
            adapter.set_contact_residue_visible.assert_called_once_with(residue, True)
            adapter.show_review_contacts.assert_called_once_with(view.interactions)
            adapter.focus_interaction_review.assert_called_once()
            camera = widget.cmd.get_view()
            adapter._plip_contacts = ['old cluster contacts']
            adapter._plip_types_visible = {'old': False}
            adapter._contact_highlights = {'old': {}}
            widget.cmd.objects.append('du_review_plip_contacts')
            with patch('docking_universal.viewer.plip_contacts.contacts', side_effect=FileNotFoundError('missing report')):
                with self.assertRaises(FileNotFoundError):
                    adapter.show_linked_interactions(view)
            self.assertEqual(adapter._plip_contacts, [])
            self.assertEqual(adapter._contact_highlights, {})
            self.assertEqual(adapter._plip_types_visible, {})
            self.assertNotIn('du_review_plip_contacts', widget.cmd.objects)
            self.assertEqual(widget.cmd.get_view(), camera)
            self.assertEqual(adapter.focus_interaction_review.call_count, 1)
