import csv
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from docking_universal.services.pocket_space import validate_output, cached, sha
from docking_universal.viewer.plip_contacts import contacts, STYLES


class PocketSpaceTests(unittest.TestCase):
    def test_exact_prediction_parity_and_hash_bound_cache(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            receptor = root / 'receptor.pdb'
            receptor.write_text('protein')
            stable = root / 'stable.csv'
            stable.write_text('name,rank,score,center_x,residue_ids\npocket1,1,2.49,40.0,A_30\n')
            cache = root / 'cache'
            alpha = cache / 'alpha'
            data = alpha / 'visualizations/data'
            data.mkdir(parents=True)
            prediction = alpha / 'receptor.pdb_predictions.csv'
            prediction.write_text(stable.read_text())
            grid = data / 'receptor.pdb_pocket_grid.pdb.gz'
            with gzip.open(grid, 'wt') as stream:
                stream.write('HETATM    1  C   GRD P   1      40.000  34.000  -6.000  1.00  0.00           C\n')
            record = dict(cache=str(cache), receptor=str(receptor), predictions=str(stable), version='test',
                          receptor_sha256=sha(receptor), predictions_sha256=sha(stable))
            manifest = validate_output(record)
            self.assertEqual(manifest['counts'], {'1': 1})
            self.assertEqual(cached(record), manifest)
            receptor.write_text('changed protein')
            self.assertIsNone(cached(record))
            with self.assertRaisesRegex(ValueError, 'inputs changed'):
                validate_output(record)
            receptor.write_text('protein')
            prediction.write_text(stable.read_text().replace('2.49', '9.99'))
            with self.assertRaisesRegex(ValueError, 'exactly match'):
                validate_output(record)
            prediction.write_text(stable.read_text())
            with gzip.open(grid, 'wt') as stream:
                stream.write('HETATM    1  C   GRD P  99      40.000  34.000  -6.000  1.00  0.00           C\n')
            with self.assertRaisesRegex(ValueError, 'rank'):
                validate_output(record)
            grid.write_bytes(b'tampered')
            self.assertIsNone(cached(record))

    def test_plip_coordinates_and_colors_are_not_recalculated(self):
        with TemporaryDirectory() as directory:
            xml = Path(directory) / 'report.xml'
            xml.write_text('<report><bindingsite><interactions><hydrogen_bonds><hydrogen_bond>'
                '<restype>ASP</restype><reschain>B</reschain><resnr>30</resnr>'
                '<ligcoo><x>1</x><y>2</y><z>3</z></ligcoo>'
                '<protcoo><x>4</x><y>5</y><z>6</z></protcoo>'
                '</hydrogen_bond></hydrogen_bonds></interactions></bindingsite></report>')
            line = contacts(xml)[0]
            self.assertEqual(line['start'], (1, 2, 3))
            self.assertEqual(line['end'], (4, 5, 6))
            self.assertEqual(line['residue'], dict(name='ASP', chain='B', number='30'))
            self.assertEqual(STYLES['hydrogen_bond'][1], '#5f92ff')
            self.assertEqual(STYLES['hydrophobic_interaction'][1], '#009b49')
            xml.write_text('<report><bindingsite/><bindingsite/></report>')
            with self.assertRaises(ValueError):
                contacts(xml)
