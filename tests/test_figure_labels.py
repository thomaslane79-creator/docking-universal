"""Saved report callouts stay readable without changing molecular geometry."""
import unittest
from docking_universal.viewer.figure_labels import label_contact_residues


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
    def get_atom_coords(self, selection): return [int(selection.split()[-1]),0,0]
    def hide(self, *args): pass
    def deselect(self): pass
    def set(self, name, value, selection='all'): self.settings[(name,selection)] = value
    def label(self, selection, value): self.labels.append((selection,value))


class FigureLabelTests(unittest.TestCase):
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
        self.assertEqual(cmd.get_view(),before)


if __name__ == '__main__': unittest.main()
