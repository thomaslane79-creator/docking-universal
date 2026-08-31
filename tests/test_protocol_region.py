import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "docking_universal_region", ROOT / "libexec" / "docking_universal_region.py"
)
REGION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REGION)


def atom(serial, name, resname, chain, resnum, x, y, z):
    return (
        f"ATOM  {serial:5d} {name:^4s} {resname:>3s} {chain:1s}{resnum:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           C\n"
    )


class ProtocolRegionTests(unittest.TestCase):
    def test_protein_pdb_validation_requires_parseable_atom_records(self):
        with tempfile.TemporaryDirectory() as directory:
            valid = Path(directory) / "valid.pdb"
            invalid = Path(directory) / "invalid.pdb"
            valid.write_text(atom(1, "CA", "ALA", "A", 1, 0, 0, 0))
            invalid.write_text("ATOM malformed\nHETATM also malformed\n")
            self.assertTrue(REGION.validate_protein_pdb(valid))
            with self.assertRaisesRegex(SystemExit, "not a valid protein PDB"):
                REGION.validate_protein_pdb(invalid)

    def test_four_interactive_region_choices(self):
        for answer, expected in enumerate(REGION.REGION_CHOICES, 1):
            with self.subTest(answer=answer), patch("builtins.input", return_value=str(answer)):
                self.assertEqual(REGION.choose_region(), expected)

    def test_fpocket_can_be_automatic_or_reviewed(self):
        with patch("builtins.input", return_value=""):
            self.assertEqual(REGION.choose_fpocket_selection(), "automatic")
        with patch("builtins.input", return_value="2"):
            self.assertEqual(REGION.choose_fpocket_selection(), "reviewed")

    def test_residue_box_resolves_chain_and_uses_margin(self):
        with tempfile.TemporaryDirectory() as directory:
            pdb = Path(directory) / "target.pdb"
            pdb.write_text(
                atom(1, "CA", "HIS", "A", 57, 0, 0, 0)
                + atom(2, "CB", "HIS", "A", 57, 2, 4, 6)
                + atom(3, "CA", "HIS", "B", 57, 30, 30, 30)
            )
            box, residues = REGION.residue_box(pdb, ["A:HIS57"], margin=8)
        self.assertEqual(residues, ["A:HIS57"])
        self.assertEqual(box["center_z"], 3)
        self.assertEqual(box["size_x"], 18)
        self.assertEqual(box["size_y"], 20)
        self.assertEqual(box["size_z"], 22)

    def test_chainless_residue_must_be_unambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            pdb = Path(directory) / "target.pdb"
            pdb.write_text(
                atom(1, "CA", "HIS", "A", 57, 0, 0, 0)
                + atom(2, "CA", "HIS", "B", 57, 10, 0, 0)
            )
            with self.assertRaisesRegex(SystemExit, "ambiguous"):
                REGION.residue_box(pdb, ["HIS57"])

    def test_whole_protein_box_uses_coordinate_bounds_and_margin(self):
        with tempfile.TemporaryDirectory() as directory:
            pdb = Path(directory) / "target.pdbqt"
            pdb.write_text(
                atom(1, "CA", "ALA", "A", 1, -1, 2, 3)
                + atom(2, "CA", "ALA", "A", 2, 9, 12, 23)
            )
            box = REGION.whole_protein_box(pdb, margin=4)
        self.assertEqual(box["center_x"], 4)
        self.assertEqual(box["size_x"], 18)
        self.assertEqual(box["size_z"], 28)

    def test_engine_recommendation_uses_approved_search_space(self):
        localized = {
            "center_x": 0, "center_y": 0, "center_z": 0,
            "size_x": 26, "size_y": 26, "size_z": 26,
        }
        broad = dict(localized, size_x=51, size_y=48, size_z=62)
        self.assertEqual(REGION.recommend_engine(localized, REGION.REGION_FPOCKET)[0], "vina")
        self.assertEqual(REGION.recommend_engine(broad, REGION.REGION_RESIDUES)[0], "qvinaw")
        self.assertEqual(REGION.recommend_engine(localized, REGION.REGION_WHOLE_PROTEIN)[0], "qvinaw")

    def test_engine_recommendation_boundary_is_explicit(self):
        base = {"center_x": 0, "center_y": 0, "center_z": 0, "size_y": 20, "size_z": 20}
        immediately_below = dict(base, size_x=39.999)
        at_threshold = dict(base, size_x=40.0)
        self.assertEqual(
            REGION.recommend_engine(immediately_below, REGION.REGION_FPOCKET)[0],
            "vina",
        )
        self.assertEqual(
            REGION.recommend_engine(at_threshold, REGION.REGION_FPOCKET)[0],
            "qvinaw",
        )

    def test_engine_override_is_recorded(self):
        box = {
            "center_x": 0, "center_y": 0, "center_z": 0,
            "size_x": 26, "size_y": 26, "size_z": 26,
        }
        selection = REGION.choose_engine(
            box, REGION.REGION_FPOCKET, requested="qvinaw", interactive=False
        )
        self.assertEqual(selection["recommended_engine"], "vina")
        self.assertEqual(selection["selected_engine"], "qvinaw")
        self.assertTrue(selection["user_overrode_recommendation"])

    def test_box_files_include_configuration_and_wireframe(self):
        with tempfile.TemporaryDirectory() as directory:
            conf = Path(directory) / "whole-protein.conf"
            REGION.write_box_files(conf, {
                "center_x": 1, "center_y": 2, "center_z": 3,
                "size_x": 50, "size_y": 48, "size_z": 62,
            })
            self.assertIn("size_z = 62.000", conf.read_text())
            self.assertTrue(conf.with_name("whole-protein_box.pdb").is_file())

    def test_receptor_box_preflight_rejects_nonoverlapping_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            receptor = Path(directory) / "receptor.pdbqt"
            receptor.write_text(atom(1, "CA", "ALA", "A", 1, 0, 0, 0))
            near = Path(directory) / "near.conf"
            near.write_text(
                "center_x = 0\ncenter_y = 0\ncenter_z = 0\n"
                "size_x = 20\nsize_y = 20\nsize_z = 20\n"
            )
            far = Path(directory) / "far.conf"
            far.write_text(
                "center_x = 999\ncenter_y = 999\ncenter_z = 999\n"
                "size_x = 20\nsize_y = 20\nsize_z = 20\n"
            )
            self.assertEqual(REGION.receptor_atoms_in_box(receptor, near), 1)
            with self.assertRaisesRegex(SystemExit, "does not overlap any receptor atoms"):
                REGION.receptor_atoms_in_box(receptor, far)


if __name__ == "__main__":
    unittest.main()
