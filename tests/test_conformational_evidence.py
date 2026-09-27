import json
import tempfile
import unittest
from pathlib import Path

from docking_universal.conformational_evidence import derive_conformational_evidence


def atom_row(name, xyz, *, related=False, entry="1LIG", alignment="1LIG_A_to_A"):
    common = {"record_type": "ATOM", "atom_name": name, "alternate_location": "",
              "occupancy": 1.0, "element": name[0]}
    if related:
        return {**common, "entry": entry, "alignment_id": alignment,
                "reference_chain": "A", "reference_residue_name": "LYS",
                "reference_residue_number": "10", "aligned_xyz": xyz}
    return {**common, "chain": "A", "residue_name": "LYS", "residue_number": "10", "xyz": xyz}


class ConformationalEvidenceTests(unittest.TestCase):
    def fixture(self, root):
        (root / "reference").mkdir()
        (root / "atom_observations").mkdir()
        reference = {"N": [0, 0, 0], "CA": [1, 0, 0], "C": [1, 1, 0], "O": [1, 2, 0],
                     "CB": [1, -1, 0], "CG": [2, -1, 0], "CD": [3, -1, 0]}
        (root / "reference/atom_observations.jsonl").write_text("".join(
            json.dumps(atom_row(name, xyz)) + "\n" for name, xyz in reference.items()))
        alignments = []
        for index, side_y in enumerate((1.0, 1.5), 1):
            alignment_id = f"{index}LIG_A_to_A"
            coordinates = dict(reference)
            coordinates.update({"CB": [1, side_y, 0], "CG": [2, side_y, 1], "CD": [3, side_y, 1]})
            if index == 2:
                coordinates["O"] = [1, 4, 0]
            path = root / f"atom_observations/{alignment_id}.jsonl"
            path.write_text("".join(json.dumps(atom_row(
                name, xyz, related=True, entry=f"{index}LIG", alignment=alignment_id,
            )) + "\n" for name, xyz in coordinates.items()))
            alignments.append({"entry": f"{index}LIG", "alignment_id": alignment_id,
                               "source_chain": "A", "ligand_context": "ligand_bound",
                               "atom_observations": str(path.relative_to(root))})
        manifest = root / "structural_ensemble_manifest.json"
        manifest.write_text(json.dumps({
            "schema_name": "docking-universal-structural-ensemble", "schema_version": 1,
            "reference": {"atom_observations": "reference/atom_observations.jsonl"},
            "accepted_alignments": alignments,
        }))
        return manifest

    def test_repeated_changes_are_suggestions_not_selections(self):
        with tempfile.TemporaryDirectory() as temporary:
            record = derive_conformational_evidence(self.fixture(Path(temporary)))
            residue = record["residue_aggregates"][0]
            self.assertEqual(residue["changed_conformation_count"], 2)
            self.assertEqual(residue["interpretation"], "repeated side-chain conformational difference")
            self.assertTrue(residue["suggest_for_flexible_residue_review"])
            self.assertIn("side-chain flexibility alone may be insufficient", residue["warning"])
            self.assertEqual(record["selection_policy"], "evidence_only_user_decides")
            self.assertNotIn("selected_residues", record)
            self.assertTrue((Path(temporary) / "conformational_evidence.json").is_file())

    def test_missing_reference_observations_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "structural_ensemble_manifest.json"
            manifest.write_text('{"accepted_alignments": []}')
            with self.assertRaisesRegex(ValueError, "no retained reference"):
                derive_conformational_evidence(manifest)

    def test_current_side_chain_clash_is_retained_as_occlusion_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.fixture(root)
            ligand = root / "bound_ligand.pdb"
            ligand.write_text(
                f"HETATM    1  C1  LIG Z   1    {1.0:8.3f}{-1.2:8.3f}{0.0:8.3f}  1.00 20.00           C\nEND\n"
            )
            record = derive_conformational_evidence(
                manifest,
                ligand_evidence=[{
                    "entry": "1LIG", "aligned_chain": "A",
                    "source_ligand_id": "1LIG/LIG/Z/1",
                    "aligned_ligand_pdb": "bound_ligand.pdb",
                }],
                ligand_evidence_root=root,
            )
            first = record["observations"][0]["known_ligand_accessibility"][0]
            self.assertTrue(first["current_conformation_clashes_with_observed_ligand"])
            self.assertTrue(first["consistent_with_side_chain_occlusion"])
            aggregate = record["residue_aggregates"][0]
            self.assertEqual(aggregate["known_ligand_occlusion_count"], 1)
            self.assertIn("consistent with side-chain occlusion", aggregate["accessibility_interpretation"])


if __name__ == "__main__":
    unittest.main()
