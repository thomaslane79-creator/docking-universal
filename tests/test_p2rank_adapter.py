import csv, json, tempfile, unittest
from pathlib import Path
from docking_universal.p2rank_adapter import materialize_p2rank_candidates
from docking_universal.pocket_equivalence import find_pocket_equivalences

class P2RankAdapterTests(unittest.TestCase):
    def test_large_p2rank_pocket_can_expand_beyond_legacy_36_angstrom_cap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receptor = root / "target.pdb"
            receptor.write_text(
                "ATOM      1  CA  TYR A  10       0.000   0.000   0.000  1.00 20.00           C\n"
                "ATOM      2  CA  TYR A  11      38.000   0.000   0.000  1.00 20.00           C\nEND\n"
            )
            predictions = root / "target_predictions.csv"
            predictions.write_text(
                "name,rank,score,probability,center_x,center_y,center_z,residue_ids\n"
                "pocket1,1,8.2,0.91,19,0,0,A_10 A_11\n"
            )
            cavity = root / "cavity"
            record = materialize_p2rank_candidates(predictions, receptor, cavity, "target")
            config = (cavity / "target_pocket1.conf").read_text()
            self.assertIn("size_x = 46.000", config)
            self.assertEqual(record["box_policy"]["maximum_size_angstrom"], 48.0)

    def test_detects_translated_equivalent_pockets_without_removing_either(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pockets = []
            for pocket_number, chain, shift in ((1, "A", 0.0), (2, "B", 30.0)):
                path = root / f"pocket{pocket_number}_atm.pdb"
                lines = []
                for index in range(12):
                    x, y, z = index % 4 + shift, (index // 4) % 3, index % 2
                    atom_name = f"C{index + 1}"
                    lines.append(
                        f"ATOM  {index + 1:5d} {atom_name:>4s} ALA {chain}  10    "
                        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C"
                    )
                path.write_text("\n".join(lines) + "\nEND\n")
                pockets.append(path)
            matches = find_pocket_equivalences(pockets)
            self.assertEqual(matches[0]["pockets"], [1, 2])
            self.assertEqual(matches[0]["fitted_pocket_atom_rmsd_angstrom"], 0.0)
            self.assertFalse(matches[0]["automatic_removal"])
            self.assertEqual(
                matches[0]["decision_role"],
                "neutral_evidence_for_existing_box_selection",
            )

    def test_materializes_existing_downstream_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); receptor=root/'target.pdb'; predictions=root/'target_predictions.csv'; cavity=root/'cavity'
            receptor.write_text("ATOM      1  CA  TYR A  10       1.000   2.000   3.000  1.00 20.00           C\nEND\n")
            predictions.write_text("name,rank,score,probability,center_x,center_y,center_z,residue_ids\npocket1,1,8.2,0.91,1,2,3,A_10\n")
            record=materialize_p2rank_candidates(predictions,receptor,cavity,'target')
            self.assertEqual(record['engine'],'p2rank')
            self.assertTrue((cavity/'target_pocket1.conf').is_file())
            self.assertIn('Pocket Engine : P2Rank',(cavity/'frozen_pockets/pocket1_atm.pdb').read_text())
            self.assertIn('\tselected\t',(cavity/'pocket_selection_diagnostics.tsv').read_text())
            self.assertTrue((cavity/'selected_pocket_records.txt').read_text().strip())
            self.assertEqual(json.loads((cavity/'pocket_detection_provenance.json').read_text())['retained_count'],1)

if __name__=='__main__': unittest.main()
