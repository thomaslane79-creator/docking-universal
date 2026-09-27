import tempfile
import unittest
from pathlib import Path

from docking_universal.services.bound_ligands import detect_bound_ligands


def atom(serial, name, resname, chain, residue, element, record="HETATM"):
    return (
        f"{record:<6}{serial:5d} {name:<4} {resname:>3} {chain}{residue:4d}    "
        f"{0.0:8.3f}{0.0:8.3f}{0.0:8.3f}{1.0:6.2f}{0.0:6.2f}          {element:>2}\n"
    )


class BoundLigandDetectionTests(unittest.TestCase):
    def test_detects_and_ranks_nonwater_hetero_residues(self):
        with tempfile.TemporaryDirectory() as temporary:
            pdb = Path(temporary) / "entry.pdb"
            pdb.write_text(
                atom(1, "O", "HOH", "A", 1, "O")
                + "".join(atom(i + 2, f"C{i}", "LIG", "A", 401, "C") for i in range(8))
                + atom(20, "ZN", "ZN", "A", 500, "ZN")
                + atom(21, "H1", "LIG", "A", 401, "H")
                + atom(22, "CA", "ALA", "A", 2, "C", record="ATOM")
            )
            candidates = detect_bound_ligands(pdb)
            self.assertEqual([item.resname for item in candidates], ["LIG", "ZN"])
            self.assertEqual(candidates[0].heavy_atom_count, 8)
            self.assertEqual(candidates[0].locations, ("A:401",))
            self.assertEqual(candidates[0].instances[0].identity["residue_number"], "401")
            self.assertIn("ligand/cofactor", candidates[0].label)

    def test_groups_repeated_residue_names_without_hiding_locations(self):
        with tempfile.TemporaryDirectory() as temporary:
            pdb = Path(temporary) / "entry.pdb"
            pdb.write_text(
                atom(1, "C1", "DRG", "A", 10, "C")
                + atom(2, "C2", "DRG", "A", 10, "C")
                + atom(3, "C1", "DRG", "B", 20, "C")
            )
            candidate = detect_bound_ligands(pdb)[0]
            self.assertEqual(candidate.residue_count, 2)
            self.assertEqual(candidate.locations, ("A:10", "B:20"))
            self.assertEqual(
                [(item.chain_id, item.residue_number) for item in candidate.instances],
                [("A", "10"), ("B", "20")],
            )

    def test_detects_mmcif_hetero_residue_without_treating_polymer_as_ligand(self):
        from tests.test_structure_input import MMCIF

        with tempfile.TemporaryDirectory() as temporary:
            cif = Path(temporary) / "entry.cif"
            cif.write_text(MMCIF)
            candidates = detect_bound_ligands(cif)
            self.assertEqual([item.resname for item in candidates], ["LIG"])
            self.assertEqual(candidates[0].instances[0].chain_id, "B")
            self.assertEqual(candidates[0].instances[0].residue_number, "401")


if __name__ == "__main__":
    unittest.main()
