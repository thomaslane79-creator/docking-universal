from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from docking_universal.viewer.embedded_pymol import EmbeddedPymolAdapter


class FakeCommand:
    def __init__(self):
        self.objects = ["receptor", "du_evidence_old"]
        self.view = tuple(float(value) for value in range(18))
        self.restored_view = None
        self.auto_zoom = 1
        self.loads = []
        self.disabled = []
        self.enabled = []
        self.centers = []
        self.cgo_loads = []
        self.cgo_states = {}
        self.colors = []

    def get_view(self):
        return self.view

    def set_view(self, view):
        self.restored_view = tuple(view)
        self.view = tuple(view)

    def get_setting_int(self, name):
        assert name == "auto_zoom"
        return self.auto_zoom

    def set(self, name, value, *_args):
        if name == "auto_zoom":
            self.auto_zoom = int(value)

    def get_names(self, _kind, **_kwargs):
        return list(self.objects)

    def get_extent(self, selection, state=0):
        return None  # no coordinate model unless a test provides one

    def disable(self, name):
        self.disabled.append(name)

    def load(self, path, name, zoom=1):
        self.loads.append((path, name, zoom, self.auto_zoom))
        self.objects.append(name)
        # Simulate PyMOL changing the camera when a load is allowed to zoom.
        if zoom or self.auto_zoom:
            self.view = tuple(value + 100 for value in self.view)

    def hide(self, *_args):
        pass

    def show(self, *_args):
        pass

    def color(self, *args):
        self.colors.append(args)

    def enable(self, name):
        self.enabled.append(name)

    def delete(self, name):
        if name in self.objects:
            self.objects.remove(name)

    def load_cgo(self, value, name, zoom=1, state=0):
        self.cgo_loads.append((value, name, zoom, self.auto_zoom))
        states = self.cgo_states.setdefault(name, [])
        if state == 0:
            states.append(value)
        elif state == 1:
            states[:] = [value]
        self.objects.append(name)
        if zoom or self.auto_zoom:
            self.view = tuple(value + 100 for value in self.view)

    def center(self, name, animate=0):
        self.centers.append((name, animate))
        # Model a pan: translation/origin changes while rotation, camera depth,
        # clipping, and orthoscopic scale remain unchanged.
        changed = list(self.view)
        changed[9] += 5
        changed[10] -= 3
        changed[12:15] = [20, 30, 40]
        self.view = tuple(changed)


class FakeWidget:
    def __init__(self):
        self.cmd = FakeCommand()
        self.updates = 0

    def update(self):
        self.updates += 1


class EmbeddedEvidenceCameraTests(unittest.TestCase):
    def test_linked_pose_rank_colors_survive_without_camera_or_atom_selection_changes(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            ligand, receptor = root / 'pose.sdf', root / 'receptor.pdb'
            ligand.write_text('pose')
            receptor.write_text('receptor')
            widget = FakeWidget()
            adapter = EmbeddedPymolAdapter(widget)
            camera = widget.cmd.get_view()
            for color in ('red', 'marine', 'gold', 'green', 'magenta'):
                adapter.show_linked_pose(ligand, receptor, frame_receptor=False, ligand_color=color)
                self.assertIn((color, 'du_review_pose and elem C'), widget.cmd.colors)
                self.assertEqual(widget.cmd.get_view(), camera)
            with self.assertRaises(ValueError):
                adapter.show_linked_pose(ligand, receptor, ligand_color='invalid')
    def test_starting_scene_clipping_covers_complete_geometry_without_reframing(self):
        from docking_universal.viewer.scene_style import expand_scene_clipping
        from unittest.mock import Mock
        cmd = FakeCommand()
        view = [1., 0., 0., 0., 1., 0., 0., 0., 1., 2., 3., -80., 0., 0., 0., 79., 81., 1.]
        cmd.view = tuple(view)
        cmd.get_extent = Mock(return_value=[[-10., -10., -10.], [10., 10., 10.]])
        # A CGO outside the protein isn't included in PyMOL's atom extent.
        expand_scene_clipping(cmd, [[-60., -5., -5.], [60., 5., 5.]])
        self.assertEqual(cmd.view[:15], tuple(view[:15]))
        self.assertEqual(cmd.view[17], view[17])
        self.assertLess(cmd.view[15], 80 - 120)
        self.assertGreater(cmd.view[16], 80 + 120)
        cmd.get_extent.assert_called_once_with('enabled', state=0)
        initial = cmd.view
        expand_scene_clipping(cmd, [[-60., -5., -5.], [60., 5., 5.]])
        self.assertEqual(cmd.view, initial)
        cmd.view = tuple(view[:15] + [-1000., 1000., view[17]])
        wide = cmd.view
        expand_scene_clipping(cmd)
        self.assertEqual(cmd.view, wide)

    def test_residue_label_toggles_large_outline_and_foreground_without_selection(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        widget = FakeWidget()
        widget.cmd.label, widget.cmd.set = Mock(), Mock()
        adapter = EmbeddedPymolAdapter(widget)
        adapter._review_labels = set()
        adapter._contact_residue_atoms = Mock(return_value=[SimpleNamespace(name='CA', index=42)])
        residue = dict(name='ASP', chain='A', number='30', object='du_linked_receptor')
        self.assertTrue(adapter.toggle_review_residue_label(residue))
        widget.cmd.label.assert_called_with('du_linked_receptor and index 42', repr('ASP A:30'))
        for setting, value in [('label_size', 22), ('label_font_id', 7), ('label_outline_color', 'white')]:
            widget.cmd.set.assert_any_call(setting, value, 'du_linked_receptor')
        widget.cmd.set.assert_any_call('float_labels', 1)
        self.assertFalse(adapter.toggle_review_residue_label(residue))
        widget.cmd.label.assert_called_with('du_linked_receptor and index 42', '""')
        self.assertFalse(adapter._review_labels)
        self.assertEqual(widget.cmd.get_names('selections'), ['receptor', 'du_evidence_old'])

    def test_review_label_master_switch_is_scoped_idempotent_and_validates_first(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, call
        widget = FakeWidget()
        widget.cmd.label = Mock()
        widget.cmd.hide = Mock()
        adapter = EmbeddedPymolAdapter(widget)
        residues = [dict(name='ASP', chain=chain, number='30') for chain in ('A', 'B')]
        def atoms(residue):
            if residue['chain'] == 'X':
                raise ValueError('Missing source residue')
            return [SimpleNamespace(name='CA', index=42 if residue['chain'] == 'A' else 84)]
        adapter._contact_residue_atoms = Mock(side_effect=atoms)
        camera = widget.cmd.get_view()
        self.assertFalse(adapter.has_review_residue_labels())
        with self.assertRaises(ValueError):
            adapter.set_review_labels_visible([residues[0], dict(residues[1], chain='X')], True)
        widget.cmd.label.assert_not_called()
        self.assertTrue(adapter.set_review_labels_visible(residues, True))
        self.assertEqual(len(adapter._review_labels), 2)
        self.assertEqual(widget.cmd.label.call_args_list, [
            call('du_linked_receptor and index 42', repr('ASP A:30')),
            call('du_linked_receptor and index 84', repr('ASP B:30'))])
        adapter.set_review_labels_visible(residues, True)
        self.assertEqual(widget.cmd.label.call_count, 2)
        self.assertFalse(adapter.set_review_labels_visible([], False))
        self.assertFalse(adapter._review_label_anchors)
        widget.cmd.label.assert_has_calls([
            call('du_linked_receptor and index 42', '""'),
            call('du_linked_receptor and index 84', '""')])
        widget.cmd.hide.assert_has_calls([
            call('labels', 'du_linked_receptor and index 42'),
            call('labels', 'du_linked_receptor and index 84')])
        self.assertEqual(camera, widget.cmd.get_view())
        self.assertEqual(widget.cmd.get_names('selections'), ['receptor', 'du_evidence_old'])

    def test_contacts_are_thick_colored_cylinders_with_independent_type_gates(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        from docking_universal.viewer.plip_contacts import STYLES
        widget = FakeWidget()
        widget.cmd.auto_zoom = 0
        adapter = EmbeddedPymolAdapter(widget)
        residue = {'name': 'ASP', 'chain': 'A', 'number': '30'}
        adapter._contact_highlights[adapter._obstruction_key([residue])] = {'added': []}
        adapter._plip_contacts = [dict(kind=k, residue=residue, start=(0, 0, 0), end=(3, 0, 0))
                                  for k in ('hydrogen_bond', 'hydrophobic_interaction')]
        adapter._plip_types_visible = {c['kind']: True for c in adapter._plip_contacts}
        camera = widget.cmd.view
        with patch.dict(sys.modules, {'pymol': SimpleNamespace(cgo=SimpleNamespace(CYLINDER=7))}):
            adapter._refresh_review_contacts()
            data = widget.cmd.cgo_loads[-1][0]
            self.assertTrue(all(data[i] == 7 and data[i+7] == 0.12 for i in range(0, len(data), 14)))
            self.assertGreater(len(data), 14)  # dashed hydrogen bond plus solid hydrophobic contact
            adapter.set_review_contact_type_visible('hydrogen_bond', False)
            solid = widget.cmd.cgo_loads[-1][0]
            rgb = [int(STYLES['hydrophobic_interaction'][1][i:i+2], 16)/255 for i in (1, 3, 5)]
            self.assertEqual(solid, [7, 0, 0, 0, 3, 0, 0, .12, *rgb, *rgb])
            adapter.set_review_contacts_visible(False)
            self.assertEqual(widget.cmd.disabled[-1], 'du_review_plip_contacts')
            adapter.set_review_contacts_visible(True)
            self.assertEqual(widget.cmd.cgo_loads[-1][0], solid)
            self.assertFalse(adapter._plip_types_visible['hydrogen_bond'])
            adapter.set_review_contact_type_visible('hydrophobic_interaction', False)
            self.assertEqual(widget.cmd.disabled[-1], 'du_review_plip_contacts')
            adapter.set_review_contact_type_visible('hydrogen_bond', True)
            self.assertEqual(widget.cmd.enabled[-1], 'du_review_plip_contacts')
            with self.assertRaises(ValueError):
                adapter.set_review_contact_type_visible('made_up', True)
        self.assertEqual(widget.cmd.view, camera)
        self.assertEqual(len(widget.cmd.cgo_states['du_review_plip_contacts']), 1)
        self.assertEqual(widget.cmd.cgo_states['du_review_plip_contacts'][0], widget.cmd.cgo_loads[-1][0])
        self.assertEqual(adapter._plip_contacts[0]['end'], (3, 0, 0))

    def test_pocket_surface_smooths_locally_and_only_expands_slab(self):
        from unittest.mock import Mock
        widget = FakeWidget()
        cmd = widget.cmd
        cmd.objects = ['du_pocket_space_src', 'du_pocket_space_1']
        cmd.set, cmd.rebuild = Mock(), Mock()
        def clip(*args):
            changed = list(cmd.view)
            changed[15:17] = [10.0, 30.0]
            # Even if upstream changed another field, our final view restores it.
            changed[11] = -999
            cmd.view = tuple(changed)
        cmd.clip = Mock(side_effect=clip)
        adapter = EmbeddedPymolAdapter(widget)
        adapter._pocket_space_hash = 'grid-hash'
        camera = cmd.view
        manifest = {'grid_sha256': 'grid-hash', 'counts': {'1': 12}, 'display_radius_angstrom': 1.02}
        adapter.show_pocket_space(manifest, [1], 'red')
        self.assertEqual(cmd.view[:15], camera[:15])
        self.assertEqual(cmd.view[17], camera[17])
        self.assertEqual(cmd.view[15:17], (10.0, 30.0))
        cmd.set.assert_any_call('solvent_radius', 1.4, 'du_pocket_space_1')
        cmd.set.assert_any_call('surface_solvent', 0, 'du_pocket_space_1')
        cmd.set.assert_any_call('surface_quality', 2, 'du_pocket_space_1')
        cmd.rebuild.assert_called_once_with('du_pocket_space_1')
        adapter.show_pocket_space(manifest, [1], 'marine')
        self.assertEqual(cmd.view[15:17], (10.0, 30.0))
        cmd.rebuild.assert_called_once()
        # Removing and recreating an object must not trust its stale style cache.
        cmd.delete('du_pocket_space_1')
        cmd.create = Mock(side_effect=lambda name, *a, **kw: cmd.objects.append(name))
        cmd.alter = Mock()
        adapter.show_pocket_space(manifest, [1], 'red')
        self.assertEqual(cmd.rebuild.call_count, 2)

    def test_initial_interaction_focus_frames_only_pose_and_contact_sticks(self):
        from unittest.mock import Mock
        widget = FakeWidget()
        widget.cmd.count_atoms = Mock(return_value=12)
        widget.cmd.zoom = Mock()
        adapter = EmbeddedPymolAdapter(widget)
        adapter.center_review_ligand = Mock()
        adapter.focus_interaction_review()
        widget.cmd.zoom.assert_called_once_with(
            'du_review_pose or (du_linked_receptor and rep sticks)',
            buffer=4, complete=1, animate=0)
        adapter.center_review_ligand.assert_called_once_with()
        widget.cmd.count_atoms.return_value = 0
        with self.assertRaises(ValueError):
            adapter.focus_interaction_review()

    def test_center_exact_contact_preserves_scale_rotation_and_visibility(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        widget = FakeWidget()
        cmd = widget.cmd
        cmd.objects.append('du_linked_receptor')
        cmd.get_model = Mock(return_value=SimpleNamespace(atom=[
            SimpleNamespace(index=i, chain=c, resi='30', resn='ASP', segi='')
            for i, c in ((1, 'A'), (2, 'B'))]))
        cmd.select_list, cmd.show, cmd.hide = Mock(), Mock(), Mock()
        adapter = EmbeddedPymolAdapter(widget)
        camera = cmd.view
        adapter.center_contact_residue({'chain': 'B', 'name': 'ASP', 'number': '30'})
        self.assertEqual(cmd.select_list.call_args.args[1:], ('du_linked_receptor', [2]))
        self.assertEqual(cmd.view[:9], camera[:9])
        self.assertEqual(cmd.view[11], camera[11])
        self.assertEqual(cmd.view[15:], camera[15:])
        self.assertNotEqual(cmd.view[9:11], camera[9:11])
        cmd.show.assert_not_called()
        cmd.hide.assert_not_called()
        self.assertFalse(adapter._contact_highlights)
        self.assertFalse(any(n.startswith('du_center_') for n in cmd.objects))
        with self.assertRaises(ValueError):
            adapter.center_contact_residue({'chain': 'C', 'name': 'ASP', 'number': '30'})

    def test_center_ligand_uses_only_matching_loaded_pose(self):
        from unittest.mock import Mock
        widget = FakeWidget()
        adapter = EmbeddedPymolAdapter(widget)
        with self.assertRaises(ValueError):
            adapter.center_review_ligand()
        widget.cmd.objects.append('du_review_pose')
        widget.cmd.count_atoms = Mock(return_value=10)
        camera = widget.cmd.view
        adapter.center_review_ligand()
        self.assertEqual(widget.cmd.centers[-1], ('du_review_pose', 0))
        self.assertEqual(widget.cmd.view[11], camera[11])
        self.assertEqual(widget.cmd.view[:9], camera[:9])
        self.assertEqual(widget.cmd.view[15:], camera[15:])

    def test_obstruction_highlight_matches_chain_and_insertion_without_camera_or_color_change(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        widget = FakeWidget()
        cmd = widget.cmd
        cmd.get_object_list = Mock(return_value=["receptor", "du_pocket_1"])
        model = SimpleNamespace(atom=[
            SimpleNamespace(index=index, chain=chain, resi=resi, resn="ASP", segi="")
            for index, chain, resi in ((1, "A", "30"), (2, "B", "30"), (3, "A", "30A"))
        ])
        cmd.get_model = Mock(side_effect=lambda selection: model if selection == "receptor" else SimpleNamespace(atom=[]))
        cmd.select_list = Mock()
        cmd.show = Mock()
        adapter = EmbeddedPymolAdapter(widget)
        view = cmd.view
        result = adapter.highlight_obstruction_residues([
            {"name": "ASP", "chain": "A", "number": "30", "insertion_code": "A"},
        ])
        self.assertEqual([call.args[0] for call in cmd.get_model.call_args_list], ["receptor", "rep sticks"])
        cmd.select_list.assert_called_once_with("du_obstruction", "receptor", [3], mode="index")
        cmd.show.assert_called_once_with("sticks", "du_obstruction")
        self.assertNotIn("du_obstruction", cmd.enabled)
        self.assertEqual(result["atom_count"], 1)
        self.assertEqual(cmd.view, view)
        self.assertEqual(cmd.colors, [])

    def test_second_click_removes_only_added_sticks_and_exact_selection(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, call
        widget = FakeWidget()
        cmd = widget.cmd
        atoms = [SimpleNamespace(index=i, model="receptor", chain="A", resn="ASP", resi="30", segi="") for i in (1, 2)]
        cmd.get_object_list = Mock(return_value=["receptor"])
        cmd.get_model = Mock(side_effect=lambda selection: SimpleNamespace(atom=atoms if selection == "receptor" else atoms[:1]))
        cmd.select_list, cmd.show, cmd.hide, cmd.delete = Mock(), Mock(), Mock(), Mock()
        adapter = EmbeddedPymolAdapter(widget)
        residue = [{"chain": "A", "name": "ASP", "number": "30"}]
        view = cmd.view
        self.assertTrue(adapter.highlight_obstruction_residues(residue)["highlighted"])
        self.assertTrue(adapter.is_obstruction_highlighted(residue))
        self.assertFalse(adapter.highlight_obstruction_residues(residue)["highlighted"])
        self.assertFalse(adapter.is_obstruction_highlighted(residue))
        cmd.select_list.assert_has_calls([
            call("du_obstruction", "receptor", [1, 2], mode="index"),
            call("du_obstruction_added", "receptor", [2], mode="index"),
        ])
        cmd.hide.assert_called_once_with("sticks", "du_obstruction_added")
        self.assertEqual([c.args[0] for c in cmd.delete.call_args_list], ["du_obstruction", "du_obstruction_added", "du_obstruction"])
        self.assertNotIn("du_obstruction", cmd.enabled)
        self.assertEqual(cmd.view, view)
        self.assertEqual(cmd.colors, [])

    def test_obstruction_highlight_rejects_missing_or_ambiguous_residues_before_selecting(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        widget = FakeWidget()
        cmd = widget.cmd
        cmd.get_object_list = Mock(return_value=["receptor"])
        cmd.get_model = Mock(return_value=SimpleNamespace(atom=[
            SimpleNamespace(index=i, chain="A", resi="30", resn="ASP", segi=segment)
            for i, segment in ((1, "copy1"), (2, "copy2"))
        ]))
        cmd.select_list = Mock()
        adapter = EmbeddedPymolAdapter(widget)
        for residue in ({"name": "ASP", "chain": "A", "number": "30"},
                        {"name": "ASP", "chain": "A", "number": "31"},
                        {"name": "ASP", "number": "30"}):
            with self.assertRaises(ValueError):
                adapter.highlight_obstruction_residues([residue])
        cmd.select_list.assert_not_called()

    def test_pocket_coordinate_loading_cannot_reset_protein_camera(self):
        with TemporaryDirectory() as directory:
            pocket = Path(directory) / "pocket.pdb"
            pocket.write_text("ATOM\n")
            widget = FakeWidget()
            adapter = EmbeddedPymolAdapter(widget)
            before = widget.cmd.get_view()
            adapter.show_pocket(pocket, "du_pocket_1", "red")
            self.assertEqual(widget.cmd.get_view(), before)
            self.assertEqual(widget.cmd.loads[0][2:], (0, 0))
            self.assertEqual(widget.cmd.auto_zoom, 1)

    def test_first_and_repeated_evidence_changes_preserve_exact_camera(self):
        with TemporaryDirectory() as directory:
            first = Path(directory) / "first.pdb"
            second = Path(directory) / "second.pdb"
            first.write_text("ATOM\n")
            second.write_text("ATOM\n")
            widget = FakeWidget()
            adapter = EmbeddedPymolAdapter(widget)
            protein_view = widget.cmd.get_view()

            adapter.sync_evidence_ligands([first])
            self.assertEqual(widget.cmd.get_view(), protein_view)
            self.assertEqual(widget.cmd.loads[0][2:], (0, 0))
            self.assertEqual(widget.cmd.auto_zoom, 1)

            adapter.sync_evidence_ligands([second])
            self.assertEqual(widget.cmd.get_view(), protein_view)
            self.assertEqual(widget.cmd.loads[1][2:], (0, 0))
            self.assertEqual(widget.cmd.auto_zoom, 1)
            self.assertIn("du_evidence_old", widget.cmd.disabled)

    def test_candidate_box_preserves_user_camera_and_rotation_pivot(self):
        from unittest.mock import patch

        widget = FakeWidget()
        adapter = EmbeddedPymolAdapter(widget)
        before = widget.cmd.get_view()
        fake_cgo = type("CGO", (), {
            "LINEWIDTH": 1, "BEGIN": 2, "LINES": 3, "COLOR": 4,
            "VERTEX": 5, "END": 6, "CYLINDER": 7,
        })
        with patch.dict("sys.modules", {"pymol": type("P", (), {"cgo": fake_cgo})}):
            result = adapter.show_box([20, 30, 40], [10, 12, 14], color="marine")

        after = widget.cmd.get_view()
        self.assertEqual(after[:15], before[:15])
        self.assertLessEqual(after[15], before[15])
        self.assertGreaterEqual(after[16], before[16])
        self.assertEqual(after[17], before[17])
        self.assertEqual(widget.cmd.cgo_loads[0][2:], (0, 0))
        box_cgo = widget.cmd.cgo_loads[0][0]
        self.assertEqual(box_cgo[0], fake_cgo.CYLINDER)
        self.assertEqual(box_cgo[7], 0.22)
        self.assertEqual(widget.cmd.centers, [])
        self.assertEqual(widget.cmd.auto_zoom, 1)
        self.assertEqual(result["camera"], "preserved")
        self.assertEqual(result["edge_representation"], "cylinders")
        self.assertEqual(result["edge_radius_angstrom"], 0.22)
        self.assertEqual(result["color"], "marine")
        self.assertEqual(box_cgo[8:11], [0.0, 0.5, 1.0])

    def test_candidate_highlight_replaces_retained_and_redundant_evidence_boxes(self):
        from unittest.mock import patch

        widget = FakeWidget()
        widget.cmd.objects.extend(["candidate_box_P1", "ligand_site_box"])
        adapter = EmbeddedPymolAdapter(widget)
        fake_cgo = type("CGO", (), {
            "LINEWIDTH": 1, "BEGIN": 2, "LINES": 3, "COLOR": 4,
            "VERTEX": 5, "END": 6, "CYLINDER": 7,
        })
        with patch.dict("sys.modules", {"pymol": type("P", (), {"cgo": fake_cgo})}):
            result = adapter.show_box(
                [20, 30, 40], [10, 12, 14],
                source_object_name="candidate_box_P1",
                redundant_object_names=("ligand_site_box",),
            )

        self.assertEqual(widget.cmd.disabled, ["candidate_box_P1", "ligand_site_box"])
        self.assertEqual(result["replaces"], "candidate_box_P1")
        self.assertEqual(result["hides_redundant"], ["ligand_site_box"])

    def test_associated_ligand_visibility_follows_candidate_selection(self):
        from unittest.mock import patch

        widget = FakeWidget()
        widget.cmd.objects.append("ligand_site_representative")
        adapter = EmbeddedPymolAdapter(widget)
        fake_cgo = type("CGO", (), {
            "LINEWIDTH": 1, "BEGIN": 2, "LINES": 3, "COLOR": 4,
            "VERTEX": 5, "END": 6, "CYLINDER": 7,
        })
        with patch.dict("sys.modules", {"pymol": type("P", (), {"cgo": fake_cgo})}):
            adapter.show_box(
                [20, 30, 40], [10, 12, 14],
                visible_associated_object_names=("ligand_site_representative",),
            )
            adapter.show_box([40, 50, 60], [10, 12, 14])

        self.assertIn("ligand_site_representative", widget.cmd.enabled)
        self.assertIn("ligand_site_representative", widget.cmd.disabled)

    def test_specific_evidence_selection_temporarily_hides_report_representative(self):
        from unittest.mock import patch

        with TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence.pdb"
            evidence.write_text("ATOM\n")
            widget = FakeWidget()
            widget.cmd.objects.append("ligand_site_representative")
            adapter = EmbeddedPymolAdapter(widget)
            fake_cgo = type("CGO", (), {
                "LINEWIDTH": 1, "BEGIN": 2, "LINES": 3, "COLOR": 4,
                "VERTEX": 5, "END": 6, "CYLINDER": 7,
            })
            with patch.dict("sys.modules", {"pymol": type("P", (), {"cgo": fake_cgo})}):
                adapter.show_box(
                    [20, 30, 40], [10, 12, 14],
                    visible_associated_object_names=("ligand_site_representative",),
                )
            adapter.sync_evidence_ligands([evidence])
            self.assertEqual(widget.cmd.disabled[-1], "ligand_site_representative")
            self.assertTrue(any(call[0] == "green" for call in widget.cmd.colors))

            adapter.sync_evidence_ligands([])
            self.assertEqual(widget.cmd.enabled[-1], "ligand_site_representative")


if __name__ == "__main__":
    unittest.main()
