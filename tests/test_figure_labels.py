"""Saved report callouts stay readable without changing molecular geometry."""
import unittest
import tempfile
from pathlib import Path
from docking_universal.viewer.figure_labels import label_contact_residues, round_contact_label_backgrounds


class FakeCommand:
    def __init__(self):
        self.settings = {}
        self.labels = []
        self.view = [1,0,0,0,1,0,0,0,1,0,0,-20,0,0,0,1,100,0]

    def get_names(self, kind):
        return ['plip_contact_residues_chain_A']

    def iterate(self, selection, expression, space):
        for index,name,resi in ((1,'N','30'),(2,'CA','30'),(3,'CA','47')):
            space['rows'].append(dict(model='protein',index=index,name=name,
                                     resn='ASP' if resi=='30' else 'ILE',resi=resi,chain='A',segi=''))

    def get_view(self): return self.view[:]
    def get_setting_float(self, name): return 30.0
    def get_setting_int(self, name): return 1
    def get_atom_coords(self, selection): return [int(selection.split()[-1]),0,0]
    def hide(self, *args): pass
    def deselect(self): pass
    def set(self, name, value, selection='all'): self.settings[(name,selection)] = value
    def label(self, selection, value): self.labels.append((selection,value))


class FigureLabelTests(unittest.TestCase):
    def test_rounded_callout_restores_scene_at_corners(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temporary:
            base, result = Path(temporary)/'base.png', Path(temporary)/'result.png'
            Image.new('RGB', (400, 300), 'blue').save(base)
            Image.new('RGB', (400, 300), 'blue').save(result)
            round_contact_label_backgrounds(result, base, [{'label': 'A1', 'screen_point': [0, 0, -1]}])
            with Image.open(result) as picture:
                self.assertEqual(picture.getpixel((20, 20)), (0, 0, 255))
                self.assertEqual(picture.getpixel((200, 137)), (255, 255, 255))

    def test_foreground_leader_connects_to_projected_atom(self):
        from PIL import Image
        cmd = FakeCommand()
        rows = label_contact_residues(cmd, viewport=(400, 300))
        self.assertEqual(cmd.settings['label_connector', 'all'], 0)
        self.assertAlmostEqual(rows[0]['anchor_screen_point'][0], .2799, places=3)
        self.assertEqual(rows[0]['anchor_screen_point'][1], 0)
        with tempfile.TemporaryDirectory() as temporary:
            base, result = Path(temporary)/'base.png', Path(temporary)/'result.png'
            Image.new('RGB', (400, 300), 'blue').save(base)
            Image.new('RGB', (400, 300), 'blue').save(result)
            round_contact_label_backgrounds(result, base, rows)
            with Image.open(result) as picture:
                self.assertLess(max(picture.getpixel((250, 150))), 100)

    def test_bold_font_keeps_size_compact_placement_and_one_label_per_residue(self):
        cmd = FakeCommand()
        before = cmd.get_view()
        rows = label_contact_residues(cmd)
        self.assertEqual(cmd.settings['label_font_id','all'],7)  # PyMOL Sans Bold
        self.assertEqual(cmd.settings['label_size','all'],40)
        self.assertEqual(cmd.settings['label_color','all'],'black')
        self.assertEqual([r['label'] for r in rows],['Asp30A','Ile47A'])
        self.assertEqual([r['index'] for r in rows],[2,3])
        self.assertTrue(all(abs(r['screen_point'][0])==.68 for r in rows))
        self.assertTrue(all(r['screen_point'][2] == -1. for r in rows))
        self.assertEqual(cmd.get_view(),before)


if __name__ == '__main__': unittest.main()
