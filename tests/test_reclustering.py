"""Analysis revisions must preserve scored poses and never start docking."""
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from docking_universal.services.reclustering import input_hashes, load_retained_records

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / 'libexec/docking-universal-cluster-poses.py'

class ReclusteringTests(unittest.TestCase):
    def setUp(self):
        from rdkit import Chem
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.source = self.root / 'pose_analysis'; self.source.mkdir()
        writer = Chem.SDWriter(str(self.source / 'all_poses.sdf'))
        for index, offset in enumerate((0.0, 0.6, 2.2), 1):
            mol = Chem.MolFromSmiles('CCO'); conf = Chem.Conformer(3)
            for atom, xyz in enumerate(((0, 0, 0), (1.4, 0, 0), (2.2, 1, 0))):
                conf.SetAtomPosition(atom, (xyz[0] + offset, xyz[1], xyz[2]))
            mol.AddConformer(conf); mol.SetDoubleProp('DockingUniversal_Energy', -7.0 + index)
            writer.write(mol)
        writer.close()
        fields = ['pose_id','cluster_id','selected_cluster','seed','conformer','model','energy_kcal_per_mol','source']
        with (self.source / 'pose_inventory.csv').open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
            for i in range(1, 4):
                writer.writerow(dict(zip(fields, (i, i, 'yes', 41001, 'state-1', i, -7+i, 'original.pdbqt'))))
        (self.source / 'cluster_summary.csv').write_text('cluster_id,chemical_state\n1,1\n2,1\n3,1\n')
        (self.source / 'clustering_manifest.json').write_text(json.dumps({'pose_count':3,'engine':'vina','cluster_rmsd_angstrom':1.5}))
        (self.source / 'receptor.pdb').write_text('ATOM      1  CA  GLY A   1      10.000  10.000  10.000  1.00 20.00           C\nEND\n')
        self.before = input_hashes(self.source)

    def tearDown(self):
        self.assertEqual(input_hashes(self.source), self.before)
        self.temp.cleanup()

    def run_worker(self, cutoff='1.5', output=None, engine='vina', extra=()):
        out = output or self.root / 'revision'
        result = subprocess.run([sys.executable, str(WORKER), '--retained-analysis', str(self.source),
                                 '--out', str(out), '--engine', engine, '--cluster-rmsd', str(cutoff), *extra],
                                env={**os.environ, 'PYTHONPATH':str(ROOT/'libexec')}, capture_output=True, text=True)
        return result, out

    def test_every_pose_score_state_and_order_are_loaded(self):
        records, hashes = load_retained_records(self.source, 'vina')
        self.assertEqual(hashes, self.before)
        self.assertEqual([r['energy'] for r in records], [-6, -5, -4])
        self.assertEqual([r['state'] for r in records], ['1'] * 3)

    def test_wrong_engine_is_not_relabelled(self):
        with self.assertRaisesRegex(ValueError, 'engine differs'):
            load_retained_records(self.source, 'adgpu')

    def test_revision_preserves_original_sdf_and_never_docks(self):
        result, out = self.run_worker()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((out/'clustering_manifest.json').read_text())
        self.assertEqual(report['new_docking_jobs'], 0)
        self.assertEqual(report['source_input_sha256'], self.before)
        self.assertEqual((out/'all_poses.sdf').read_bytes(), (self.source/'all_poses.sdf').read_bytes())
        self.assertEqual(report['engine'], 'vina')
        self.assertEqual(report['pose_count'], 3)

    def test_looser_cutoff_changes_grouping_not_scores(self):
        result, tight = self.run_worker('1.0', self.root/'tight')
        self.assertEqual(result.returncode, 0, result.stderr)
        result, loose = self.run_worker('2.0', self.root/'loose')
        self.assertEqual(result.returncode, 0, result.stderr)
        a = json.loads((tight/'clustering_manifest.json').read_text())
        b = json.loads((loose/'clustering_manifest.json').read_text())
        self.assertGreater(a['cluster_count'], b['cluster_count'])
        for folder in (tight, loose):
            with (folder/'pose_inventory.csv').open() as handle:
                self.assertEqual([float(r['energy_kcal_per_mol']) for r in csv.DictReader(handle)], [-6,-5,-4])

    def test_old_output_is_never_overwritten(self):
        output = self.root/'existing'; output.mkdir(); (output/'keep').write_text('original')
        result, _ = self.run_worker(output=output)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((output/'keep').read_text(), 'original')
        self.assertEqual(list(output.iterdir()), [output/'keep'])

    def test_nonfinite_cutoffs_are_rejected_before_writing(self):
        for value in ('nan', 'inf', '-inf', '0'):
            result, out = self.run_worker(value)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(out.exists())

    def test_a_different_receptor_is_rejected(self):
        receptor = self.root/'other.pdb'; receptor.write_text('different')
        result, out = self.run_worker(extra=('--receptor', str(receptor)))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(out.exists())

    def test_input_count_mismatch_cannot_silently_drop_poses(self):
        data = json.loads((self.source/'clustering_manifest.json').read_text())
        data['pose_count'] = 2
        (self.source/'clustering_manifest.json').write_text(json.dumps(data))
        self.before = input_hashes(self.source)
        with self.assertRaisesRegex(ValueError, 'counts disagree'):
            load_retained_records(self.source, 'vina')

if __name__ == '__main__':
    unittest.main()
