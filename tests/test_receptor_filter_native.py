import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from docking_universal.receptor_filter import disulfide_templates, filter_receptor_pdb

ROOT = Path(__file__).resolve().parents[1]


class NativeReceptorFilterTests(unittest.TestCase):
    def linked_reference_fixture(self, source):
        def atom(i, name, res, chain, number, element):
            return (f'HETATM{i:5d} {name:>4} {res:>3} {chain}{number:4d}    '
                    f'{i:8.3f}{0:8.3f}{0:8.3f}  1.00 20.00          {element:>2}\n')
        def link(first, second):
            line = list(' ' * 80); line[:6] = 'LINK  '
            for offset, (name, residue, chain, number) in ((0, first), (30, second)):
                line[12+offset:16+offset] = f'{name:>4}'
                line[17+offset:20+offset] = f'{residue:>3}'
                line[21+offset] = chain
                line[22+offset:26+offset] = f'{number:4d}'
            return ''.join(line) + '\n'
        source.write_text(
            link(('C1', 'GNP', 'A', 200), ('MG', 'MG', 'A', 201))
            + link(('C1', 'GNP', 'B', 200), ('MG', 'MG', 'A', 201))
            + 'ATOM      1  CA  ALA A   1       1.000   0.000   0.000  1.00 20.00           C\n'
            + atom(2, 'C1', 'GNP', 'A', 200, 'C') + atom(3, 'C2', 'GNP', 'A', 200, 'C')
            + atom(4, 'MG', 'MG', 'A', 201, 'MG')
            + atom(5, 'C1', 'GNP', 'B', 200, 'C') + atom(6, 'C2', 'GNP', 'B', 200, 'C'))

    def test_exact_metal_associated_reference_is_withheld_without_losing_other_components(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);source=root/'source.pdb';output=root/'receptor.pdb'
            self.linked_reference_fixture(source);original=source.read_bytes()
            reference=dict(resname='GNP',chain='A',number='200',insertion_code='')
            result=filter_receptor_pdb(source,output,bound_reference=reference)
            self.assertEqual(source.read_bytes(),original)
            atoms=[line for line in output.read_text().splitlines() if line.startswith(('ATOM  ','HETATM'))]
            self.assertEqual(len(atoms),4)
            self.assertFalse(any(line[17:20].strip()=='GNP' and line[21]=='A' for line in atoms))
            self.assertEqual(sum(line[17:20].strip()=='GNP' and line[21]=='B' for line in atoms),2)
            self.assertTrue(any(line[17:20].strip()=='MG' for line in atoms))
            self.assertEqual(result['bound_reference_separation']['withheld_from_scored_receptor_atom_records'],2)

    def test_missing_or_covalently_attached_reference_requires_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.pdb';output=root/'receptor.pdb'
            self.linked_reference_fixture(source)
            with self.assertRaisesRegex(ValueError,'exact bound reference'):
                filter_receptor_pdb(source,output,bound_reference=dict(resname='GNP',chain='Z',number='200'))
            lines=source.read_text().splitlines(keepends=True)
            row=list(lines[0]);row[47:50]='ALA';row[51]='A';row[52:56]='   1'
            lines[0]=''.join(row);source.write_text(''.join(lines))
            with self.assertRaisesRegex(ValueError,'covalent-reference review'):
                filter_receptor_pdb(source,output,bound_reference=dict(resname='GNP',chain='A',number='200'))
            self.assertFalse(output.exists())

    @unittest.skipIf(os.name == 'nt', 'POSIX engine wrapper')
    def test_posix_exact_reference_filter_matches_native_and_writes_audit(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.pdb';output=root/'receptor.pdb';expected=root/'native.pdb'
            self.linked_reference_fixture(source)
            subprocess.run(['bash','-c',
                '. "$1"; PYTHON_COMMAND="$4"; LIBEXEC_DIR="$5"; '
                'REQUESTED_LIGAND=GNP; REQUESTED_LIGAND_CHAIN=A; REQUESTED_LIGAND_RESSEQ=200; '
                'filter_receptor_input "$2" "$3"', 'reference-filter',
                str(ROOT/'libexec/docking-universal-prepare-support.sh'),str(source),str(output),
                sys.executable,str(ROOT/'libexec')],check=True)
            filter_receptor_pdb(source,expected,bound_reference=dict(resname='GNP',chain='A',number='200',insertion_code=''))
            self.assertEqual(output.read_bytes(),expected.read_bytes())
            record=json.loads((root/'bound_reference_separation.json').read_text())
            self.assertEqual(record['bound_reference_separation']['identity']['chain'],'A')

    def test_crystal_context_and_component_policy_are_preserved(self):
        def record(kind, serial, residue, number, element="C"):
            return f"{kind:<6}{serial:5d} {'CA':^4} {residue:>3} A{number:4d}    {serial:8.3f}{0:8.3f}{0:8.3f}{1:6.2f}{20:6.2f}          {element:>2}\n"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "input.pdb", root / "filtered.pdb"
            source.write_text("CRYST1   46.711   46.711  100.708  90.00  90.00  90.00 P 41 21 2     8\n"
                "SCALE1      0.021408  0.000000  0.000000        0.00000\n"
                "MODRES 1ABC CSO A   2  CYS  S-HYDROXYCYSTEINE\n"
                "LINK         CA  ALA A   1                 C1  ADX A 101\n"
                + record("ATOM", 1, "ALA", 1) + record("HETATM", 2, "CSO", 2)
                + record("HETATM", 3, "ADX", 101) + record("HETATM", 4, "ADX", 101)
                + record("HETATM", 5, "LIG", 201) + record("HETATM", 6, "HOH", 301, "O")
                + record("HETATM", 7, "ZN", 401, "ZN") + record("HETATM", 8, "NA", 402, "NA"), encoding="utf-8")
            original = source.read_bytes()
            result = filter_receptor_pdb(source, target)
            text = target.read_text(encoding="utf-8")
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(result["retained_linked_components"], ["ADX:A:101"])
            self.assertEqual(sum(line.startswith("ATOM  ") for line in text.splitlines()), 2)
            for retained in ("CRYST1", "SCALE1", "CSO", "ADX", "ZN"):
                self.assertIn(retained, text)
            for omitted in ("LIG", "HOH", "NA"):
                self.assertNotIn(omitted, text)

    @unittest.skipIf(os.name == "nt", "Compare the original POSIX implementation on its native platform")
    def test_public_receptors_match_original_filter_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = sorted((ROOT / "examples/tutorials").glob("*/inputs/*.pdb"))
            self.assertTrue(sources)
            for number, source in enumerate(sources):
                with self.subTest(source=source.name):
                    expected, actual = root / f"legacy-{number}.pdb", root / f"native-{number}.pdb"
                    subprocess.run(["bash", "-c", '. "$1"; filter_receptor_input "$2" "$3"', "filter-parity",
                                    str(ROOT / "libexec/docking-universal-prepare-support.sh"), str(source), str(expected)], check=True)
                    filter_receptor_pdb(source, actual)
                    self.assertEqual(actual.read_bytes(), expected.read_bytes())
                    assignments = subprocess.check_output(["bash", "-c", '. "$1"; disulfide_template_assignments "$2"', "disulfide-parity",
                        str(ROOT / "libexec/docking-universal-prepare-support.sh"), str(source)], text=True).strip()
                    self.assertEqual(disulfide_templates(source), assignments)
