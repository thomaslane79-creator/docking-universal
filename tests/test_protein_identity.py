import importlib.util
from pathlib import Path
import tempfile
import unittest

from docking_universal.services.protein_identity import (
    identity_from_metadata, read_protein_identity, target_identity_text,
)

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("identity_report", ROOT / "libexec/docking-universal-pdf-report.py")
REPORT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(REPORT)

MMCIF = """data_2R8N
_entry.id 2R8N
_struct.title 'Unbound protease'
loop_
_entity.id
_entity.type
_entity.pdbx_description
_entity.pdbx_fragment
1 polymer 'Pol protein' 'HIV-1 protease subtype C'
2 non-polymer GLYCEROL ?
3 polymer RNA ?
loop_
_entity_poly.entity_id
_entity_poly.type
_entity_poly.pdbx_strand_id
1 'polypeptide(L)' A
3 polyribonucleotide B
loop_
_entity_src_gen.entity_id
_entity_src_gen.pdbx_gene_src_scientific_name
_entity_src_gen.pdbx_host_org_scientific_name
1 'Human immunodeficiency virus 1' 'Escherichia coli'
"""


class ProteinIdentityTests(unittest.TestCase):
    def test_exact_cif_distinguishes_source_species_and_host_and_excludes_ligands_rna(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "input.cif"
            source.write_text(MMCIF)
            before = source.read_bytes()
            identity = read_protein_identity(source)
            self.assertEqual(source.read_bytes(), before)
        self.assertEqual(identity["structure_id"], "2R8N")
        self.assertEqual(len(identity["proteins"]), 1)
        protein = identity["proteins"][0]
        self.assertEqual(protein["name"], "Pol protein")
        self.assertEqual(protein["source_species"], ["Human immunodeficiency virus 1"])
        self.assertEqual(protein["expression_hosts"], ["Escherichia coli"])
        target, species = target_identity_text(identity, "input")
        self.assertIn("HIV-1 protease subtype C", target)
        self.assertTrue(target.endswith("[2R8N]"))
        self.assertNotIn("[structure", target)
        self.assertNotIn("Escherichia", species)

    def test_natural_and_synthetic_sources_remain_per_entity(self):
        metadata = {
            "entity": {"id": ["1", "2"], "pdbx_description": ["Protein X", "Protein Y"]},
            "entity_poly": {"entity_id": ["1", "2"], "type": ["polypeptide(L)"] * 2,
                            "pdbx_strand_id": ["A,B", "C"]},
            "entity_src_nat": {"entity_id": ["1"], "pdbx_organism_scientific": ["Species X"]},
            "pdbx_entity_src_syn": {"entity_id": ["2"], "organism_scientific": ["Species Y"]},
        }
        identity = identity_from_metadata(metadata)
        target, species = target_identity_text(identity, "entry")
        self.assertIn("Protein X [chains A,B]", target)
        self.assertIn("Protein Y [chains C]", target)
        self.assertEqual(species, "Chains A,B: Species X; Chains C: Species Y")

    def test_unknown_does_not_guess_identity_from_filename_or_host(self):
        identity = identity_from_metadata({
            "entity": {"id": ["1"], "pdbx_description": [None]},
            "entity_poly": {"entity_id": ["1"], "type": ["polypeptide(L)"]},
            "entity_src_gen": {"entity_id": ["1"], "pdbx_gene_src_scientific_name": ["?"],
                               "pdbx_host_org_scientific_name": ["Escherichia coli"]},
        })
        target, species = target_identity_text(identity, "HumanProtein")
        self.assertIn("not recorded", target)
        self.assertIn("Not recorded", species)
        self.assertNotIn("Escherichia", species)

    def test_pdb_compnd_source_continuations_and_entity_mapping(self):
        pdb = "\n".join([
            "HEADER" + " " * 56 + "1ABC",
            "COMPND    MOL_ID: 1; MOLECULE: LONG",
            "COMPND   2 PROTEIN NAME; CHAIN: A;",
            "SOURCE    MOL_ID: 1; ORGANISM_SCIENTIFIC: Homo sapiens;",
            "SOURCE   2 EXPRESSION_SYSTEM: Escherichia coli;",
            "ATOM      1  CA  GLY A   1       0.000   0.000   0.000  1.00 10.00           C",
        ])
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "entry.pdb"
            source.write_text(pdb)
            identity = read_protein_identity(source)
        self.assertEqual(identity["proteins"][0]["name"], "LONG PROTEIN NAME")
        self.assertEqual(identity["proteins"][0]["source_species"], ["Homo sapiens"])
        self.assertEqual(identity["structure_id"], "1ABC")

    def test_old_metadata_is_supplemented_only_from_its_exact_retained_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "assets").mkdir()
            source = root / "assets/source.cif"
            source.write_text(MMCIF)
            protocol = {"coordinate_source": {"structure": "assets/source.cif", "evidence": {
                "deposited_metadata": {},
            }, "structure_sha256": REPORT.sha256(source)}}
            identity = REPORT.report_target_identity(root, {}, protocol, root / "protocol.json", "")
            self.assertEqual(identity["proteins"][0]["source_species"], ["Human immunodeficiency virus 1"])
            source.write_text(MMCIF.replace("Human immunodeficiency virus 1", "Wrong species"))
            identity = REPORT.report_target_identity(root, {}, protocol, root / "protocol.json", "")
            self.assertFalse(identity["proteins"])

    def test_portable_snapshot_wins_over_unavailable_original_paths(self):
        expected = {"structure_id": "2R8N", "proteins": [{"name": "Pol protein",
                    "source_species": ["Human immunodeficiency virus 1"]}]}
        identity = REPORT.report_target_identity(Path("/nonexistent"), {}, {
            "target_identity": expected, "coordinate_source": {"structure": "/gone.cif"},
        }, None, "")
        self.assertEqual(identity, expected)


if __name__ == "__main__":
    unittest.main()
