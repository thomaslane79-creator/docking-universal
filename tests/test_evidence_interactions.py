import tempfile
import unittest
import json
import hashlib
import importlib.util
from unittest.mock import patch
from pathlib import Path
from docking_universal.services.evidence_interactions import evidence_inputs, materialize_inputs, evidence_diagram_path, evidence_diagram_current
from docking_universal.poseedit_renderer import LAYOUT_REVISION

try:
    from rdkit import Chem
    from rdkit.Chem import AllChem
except ImportError:
    Chem = None


@unittest.skipIf(Chem is None, "RDKit required")
class EvidenceInteractionTests(unittest.TestCase):
    def test_control_diagrams_align_reordered_atoms_to_reference(self):
        import subprocess
        import sys
        molecule = Chem.AddHs(Chem.MolFromSmiles('CC(O)N'))
        AllChem.EmbedMolecule(molecule, randomSeed=42)
        reordered = Chem.RenumberAtoms(molecule, list(reversed(range(molecule.GetNumAtoms()))))
        reference, pose = self.root / 'reference.sdf', self.root / 'reordered.sdf'
        for path, source in ((reference, molecule), (pose, reordered)):
            writer = Chem.SDWriter(str(path)); writer.write(source); writer.close()
        script = Path(__file__).resolve().parents[1] / 'libexec/docking_universal/poseedit_renderer/ligand_scene.py'
        structures = []
        for source in (reference, pose):
            output = self.root / (source.stem + '.json')
            subprocess.run([sys.executable, str(script), str(source), '--output', str(output),
                            '--alignment-reference', str(reference)], check=True, capture_output=True)
            structures.append(json.loads(output.read_text())['scene']['structures'][0])
        original = {a['additionalInformation']['sdfAtomIndex']: a['coordinates'] for a in structures[0]['atoms']}
        for atom in structures[1]['atoms']:
            old_index = molecule.GetNumAtoms() - 1 - atom['additionalInformation']['sdfAtomIndex']
            self.assertAlmostEqual(original[old_index]['x'], atom['coordinates']['x'], places=5)
            self.assertAlmostEqual(original[old_index]['y'], atom['coordinates']['y'], places=5)

    def test_2d_hydrogen_display_preserves_original_heavy_atom_ids(self):
        import subprocess
        import sys
        molecule = Chem.AddHs(Chem.MolFromSmiles('CCO'))
        AllChem.EmbedMolecule(molecule, randomSeed=42)
        # Interleave hydrogen and heavy atoms to verify IDs do not merely
        # coincide with the post-removal atom indices.
        molecule = Chem.RenumberAtoms(molecule, [3, 0, 4, 1, 2, 5, 6, 7, 8])
        ligand = self.root / 'interleaved.sdf'
        writer = Chem.SDWriter(str(ligand))
        writer.write(molecule)
        writer.close()
        output = self.root / 'scene.json'
        scene_script = Path(__file__).resolve().parents[1] / 'libexec/docking_universal/poseedit_renderer/ligand_scene.py'
        subprocess.run([sys.executable, str(scene_script), str(ligand), '--output', str(output)], check=True, capture_output=True)
        structure = json.loads(output.read_text())['scene']['structures'][0]
        heavy_indices = [a.GetIdx() for a in molecule.GetAtoms() if a.GetAtomicNum() > 1]
        self.assertEqual([a['additionalInformation']['sdfAtomIndex'] for a in structure['atoms']], heavy_indices)
        self.assertEqual([a['id'] for a in structure['atoms']], [10000 + i for i in heavy_indices])
        self.assertNotIn('H', [a['element'] for a in structure['atoms']])
        self.assertEqual({b['from'] for b in structure['bonds']} | {b['to'] for b in structure['bonds']},
                         {10000 + i for i in heavy_indices})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "structural_ensemble/source_structures/1ABC.pdb"
        self.source.parent.mkdir(parents=True)
        (self.root / "ccd").mkdir()
        (self.root / "aligned_ligands").mkdir()
        molecule = Chem.AddHs(Chem.MolFromSmiles("CCO"))
        AllChem.EmbedMolecule(molecule, randomSeed=42)
        molecule = Chem.RemoveHs(molecule)
        atoms = [line for line in Chem.MolToPDBBlock(molecule).splitlines() if line.startswith("HETATM")]
        self.selected = [line[:17] + "LIG A   9 " + line[27:] for line in atoms]
        other = [line[:17] + "LIG B  10 " + line[27:] for line in atoms]
        self.source.write_text("\n".join(self.selected + other) + "\nEND\n")
        writer = Chem.SDWriter(str(self.root / "ccd/LIG_ideal.sdf"))
        writer.write(molecule)
        writer.close()
        self.aligned = self.root / "aligned_ligands/1ABC_LIG_A_9.pdb"
        self.aligned.write_text("\n".join(self.selected))
        self.observation = {"source_ligand_id": "1ABC/LIG/A/9", "aligned_ligand_pdb": str(self.aligned)}

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_instance_uses_deposited_coordinates_and_retains_other_ligand(self):
        record = evidence_inputs(self.observation)
        cache = materialize_inputs(record)
        sdf = next(item for item in Chem.SDMolSupplier(str(cache / "ligand.sdf")) if item)
        original = Chem.MolFromPDBBlock("\n".join(self.selected) + "\nEND\n")
        for index in range(3):
            self.assertLess((sdf.GetConformer().GetAtomPosition(index)
                             - original.GetConformer().GetAtomPosition(index)).Length(), 0.001)
        self.assertIn("LIG B  10", (cache / "receptor.pdb").read_text())
        self.assertNotIn("LIG A   9", (cache / "receptor.pdb").read_text())
        self.assertEqual((cache / "complex.pdb").read_text().count("UNL Z   1"), 3)

    def test_deposited_explicit_hydrogens_do_not_duplicate_template_hydrogens(self):
        molecule = Chem.AddHs(Chem.MolFromSmiles('c1cn[nH]c1'))
        AllChem.EmbedMolecule(molecule, randomSeed=19)
        lines = [line[:17] + 'LIG A   9 ' + line[27:] for line in
                 Chem.MolToPDBBlock(molecule).splitlines() if line.startswith('HETATM')]
        self.source.write_text('\n'.join(lines) + '\nEND\n')
        self.aligned.write_text('\n'.join(lines) + '\nEND\n')
        writer = Chem.SDWriter(str(self.root / 'ccd/LIG_ideal.sdf'))
        writer.write(molecule)
        writer.close()
        cache = materialize_inputs(evidence_inputs(self.observation))
        result = next(m for m in Chem.SDMolSupplier(str(cache / 'ligand.sdf')) if m)
        self.assertEqual(Chem.MolToSmiles(result), Chem.MolToSmiles(Chem.RemoveHs(molecule)))

    def test_input_mmcif_uses_exact_atom_names_and_rejects_changed_source(self):
        molecule = Chem.AddHs(Chem.MolFromSmiles('CCO'))
        AllChem.EmbedMolecule(molecule, randomSeed=42)
        pdb_atoms = [line for line in Chem.MolToPDBBlock(molecule).splitlines() if line.startswith('HETATM')]
        names = [line[12:16].strip() for line in pdb_atoms]
        source_lines = [line[:17] + 'LIG A   9 ' + line[27:] for line in pdb_atoms]
        self.source.write_text('\n'.join(source_lines) + '\nEND\n')
        self.aligned.write_text('\n'.join(source_lines) + '\n')
        atoms = ['loop_', '_chem_comp_atom.comp_id', '_chem_comp_atom.atom_id',
                 '_chem_comp_atom.type_symbol', '_chem_comp_atom.charge']
        atoms += [f'LIG {name} {atom.GetSymbol()} 0' for name, atom in zip(names, molecule.GetAtoms())]
        bonds = ['loop_', '_chem_comp_bond.comp_id', '_chem_comp_bond.atom_id_1',
                 '_chem_comp_bond.atom_id_2', '_chem_comp_bond.value_order']
        bonds += [f'LIG {names[bond.GetBeginAtomIdx()]} {names[bond.GetEndAtomIdx()]} SING'
                  for bond in molecule.GetBonds()]
        cif = self.root / 'input.cif'
        cif.write_text('data_input\n' + '\n'.join(atoms) + '\n' + '\n'.join(bonds) + '\n')
        sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        observation = {'source': 'input_structure', 'source_ligand_id': 'input/LIG/A/9',
            'aligned_ligand_pdb': str(self.aligned), 'ligand_sha256': sha(self.aligned),
            'deposited_source': str(self.source), 'deposited_source_sha256': sha(self.source),
            'component_source': str(cif), 'component_source_sha256': sha(cif)}
        record = evidence_inputs(observation)
        self.assertEqual((record['entry'], record['ligand'], record['chain'], record['residue']),
                         ('Input', 'LIG', 'A', '9'))
        cache = materialize_inputs(record)
        typed = next(m for m in Chem.SDMolSupplier(str(cache / 'ligand.sdf')) if m)
        self.assertEqual(typed.GetNumHeavyAtoms(), 3)
        self.assertEqual((cache / 'complex.pdb').read_text().count('UNL Z   1'), len(source_lines))
        self.source.write_text(self.source.read_text() + 'REMARK changed\n')
        with self.assertRaisesRegex(ValueError, 'could not be verified'):
            evidence_inputs(observation)

    def test_missing_retained_chemistry_stops_before_analysis(self):
        (self.root / "ccd/LIG_ideal.sdf").unlink()
        with self.assertRaisesRegex(ValueError, "CCD chemistry"):
            evidence_inputs(self.observation)

    def test_source_changes_invalidate_cached_diagram(self):
        first = evidence_inputs(self.observation)["cache"]
        self.source.write_text(self.source.read_text() + "REMARK new source\n")
        self.assertNotEqual(first, evidence_inputs(self.observation)["cache"])

    def test_cached_drawing_revision_requires_exact_sources_and_keeps_old_png(self):
        cache = materialize_inputs(evidence_inputs(self.observation))
        (cache/'plip').mkdir()
        (cache/'plip/report.xml').write_text('<report/>')
        old = cache/'interaction_diagram.png'
        old.write_bytes(b'old')
        image = cache/f'interaction_diagram.{LAYOUT_REVISION}.png'
        image.write_bytes(b'new')
        self.assertFalse(evidence_diagram_current(cache))
        result = dict(layout_revision=LAYOUT_REVISION, diagram_file=image.name, diagram_kind="poseedit_interactions",
                      source_hashes={key:hashlib.sha256(path.read_bytes()).hexdigest() for key,path in {
                          'ligand':cache/'ligand.sdf','receptor':cache/'receptor.pdb',
                          'plip':cache/'plip/report.xml','diagram':image}.items()})
        (cache/'result.json').write_text(json.dumps(result))
        self.assertEqual(evidence_diagram_path(cache), image)
        self.assertTrue(evidence_diagram_current(cache))
        image.write_bytes(b'changed')
        self.assertFalse(evidence_diagram_current(cache))
        self.assertEqual(old.read_bytes(), b'old')
        result['diagram_file'] = '../outside.png'
        (cache/'result.json').write_text(json.dumps(result))
        self.assertEqual(evidence_diagram_path(cache), old)

    def test_diagram_only_worker_reuses_contacts_and_preserves_old_output_on_failure(self):
        record = evidence_inputs(self.observation)
        cache = materialize_inputs(record)
        (cache/'plip').mkdir()
        xml = cache/'plip/report.xml'
        xml.write_text('<report/>')
        old = cache/'interaction_diagram.png'
        old.write_bytes(b'old')
        metadata = cache/'result.json'
        metadata.write_text(json.dumps(record))
        request = cache/'request.json'
        request.write_text(json.dumps(record))
        script = Path(__file__).resolve().parents[1]/'libexec/docking-universal-evidence-interactions.py'
        spec = importlib.util.spec_from_file_location('evidence_worker_test', script)
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        originals = {p:p.read_bytes() for p in (xml,old,metadata,cache/'ligand.sdf',cache/'receptor.pdb')}
        with patch.object(worker,'run',side_effect=RuntimeError('layout failed')) as run, \
                patch.object(worker,'materialize_inputs') as materialize, \
                patch('sys.argv',[str(script),'--request',str(request),'--diagram-only']):
            with self.assertRaisesRegex(RuntimeError,'previous diagram and contacts were preserved'):
                worker.main()
            self.assertEqual(run.call_count,3)
            materialize.assert_not_called()
            self.assertTrue(all('render-poseedit' in str(call.args[0][1]) for call in run.call_args_list))
        self.assertEqual(originals,{p:p.read_bytes() for p in originals})
        def rendered(command):
            Path(command[command.index('--output')+1]).write_bytes(b'updated drawing')
        with patch.object(worker,'run',side_effect=rendered) as run, \
                patch.object(worker,'materialize_inputs') as materialize, \
                patch('sys.argv',[str(script),'--request',str(request),'--diagram-only']):
            worker.main()
            materialize.assert_not_called()
            self.assertEqual(run.call_count,1)
        self.assertTrue(evidence_diagram_current(cache))
        self.assertTrue(json.loads(metadata.read_text())['contacts_reused'])
        self.assertEqual(old.read_bytes(), originals[old])
        self.assertEqual(xml.read_bytes(), originals[xml])
        self.assertEqual((cache/f'result.before-{LAYOUT_REVISION}.json').read_text().strip(), json.dumps(record,indent=2))

    def test_alternate_conformation_is_not_silently_combined(self):
        text = self.source.read_text()
        self.source.write_text(text[:16] + "A" + text[17:])
        with self.assertRaisesRegex(ValueError, "alternate conformations"):
            materialize_inputs(evidence_inputs(self.observation))
