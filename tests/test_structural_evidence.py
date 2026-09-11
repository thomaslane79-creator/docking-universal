import json
import tempfile
import unittest
from pathlib import Path

from docking_universal.structural_evidence import StructuralEnsembleReader


class StructuralEvidenceReaderTests(unittest.TestCase):
    def fixture(self, root):
        atoms = root / "atom_observations"
        atoms.mkdir(parents=True)
        rows = [
            {
                "entry": "1ABC", "alignment_id": "1ABC_A_to_A", "record_type": "ATOM",
                "atom_name": "CA", "alternate_location": "", "source_chain": "A",
                "source_residue_name": "TYR", "source_residue_number": "42",
                "reference_chain": "A", "reference_residue_name": "TYR",
                "reference_residue_number": "42", "occupancy": 1.0, "b_factor": 18.0,
                "element": "C", "aligned_xyz": [0.0, 0.0, 0.0],
            },
            {
                "entry": "1ABC", "alignment_id": "1ABC_A_to_A", "record_type": "ATOM",
                "atom_name": "CB", "alternate_location": "A", "source_chain": "A",
                "source_residue_name": "TYR", "source_residue_number": "42",
                "reference_chain": "A", "reference_residue_name": "TYR",
                "reference_residue_number": "42", "occupancy": 0.6, "b_factor": 31.5,
                "element": "C", "aligned_xyz": [1.0, 0.0, 0.0],
            },
            {
                "entry": "1ABC", "alignment_id": "1ABC_A_to_A", "record_type": "ATOM",
                "atom_name": "CG", "alternate_location": "A", "source_chain": "A",
                "source_residue_name": "TYR", "source_residue_number": "42",
                "reference_chain": "A", "reference_residue_name": "TYR",
                "reference_residue_number": "42", "occupancy": 0.6, "b_factor": 34.0,
                "element": "C", "aligned_xyz": [2.0, 0.5, 0.0],
            },
        ]
        observations = atoms / "1ABC_A_to_A.jsonl"
        observations.write_text("".join(json.dumps(row) + "\n" for row in rows))
        manifest = root / "structural_ensemble_manifest.json"
        manifest.write_text(json.dumps({
            "schema_name": "docking-universal-structural-ensemble",
            "schema_version": 1,
            "accepted_alignments": [{"atom_observations": "atom_observations/1ABC_A_to_A.jsonl"}],
        }))
        return manifest

    def test_same_schema_supplies_b_factor_and_rotamer_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = StructuralEnsembleReader(self.fixture(Path(directory)))
            b_factors = reader.b_factor_inputs()
            conformations = reader.residue_conformation_inputs()
            self.assertEqual([row["b_factor"] for row in b_factors], [18.0, 31.5, 34.0])
            self.assertEqual(list(conformations), ["A/TYR/42"])
            self.assertEqual(
                [atom["atom_name"] for atom in conformations["A/TYR/42"][0]["atoms"]],
                ["CB", "CG"],
            )
            self.assertEqual(conformations["A/TYR/42"][0]["atoms"][0]["alternate_location"], "A")
            self.assertEqual(conformations["A/TYR/42"][0]["atoms"][0]["occupancy"], 0.6)

    def test_reader_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "structural_ensemble_manifest.json"
            manifest.write_text(json.dumps({
                "schema_name": "docking-universal-structural-ensemble",
                "schema_version": 1,
                "accepted_alignments": [{"atom_observations": "../outside.jsonl"}],
            }))
            with self.assertRaisesRegex(ValueError, "escapes its root"):
                StructuralEnsembleReader(manifest).atom_observations()

    def test_reader_rejects_unknown_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "structural_ensemble_manifest.json"
            manifest.write_text('{"schema_name":"other","schema_version":1}')
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                StructuralEnsembleReader(manifest)


if __name__ == "__main__":
    unittest.main()
