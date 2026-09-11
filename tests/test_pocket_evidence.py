#!/usr/bin/env python3
"""Scientific unit tests for PDB-derived fpocket evidence collection."""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


MODULE = Path(__file__).resolve().parents[1] / "libexec" / "docking_universal_pocket_evidence.py"
SPEC = importlib.util.spec_from_file_location("docking_universal_pocket_evidence", MODULE)
EVIDENCE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EVIDENCE
SPEC.loader.exec_module(EVIDENCE)


def atom(record, serial, atom_name, residue, chain, number, xyz, element="C"):
    return (f"{record:<6}{serial:5d} {atom_name:^4} {residue:>3} {chain:1}{number:4d}    "
            f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00 20.00          {element:>2}\n")


def protein(chain="A", offset=(0.0, 0.0, 0.0)):
    names = ["ALA", "GLY", "SER", "THR", "LEU", "ASP", "LYS", "VAL", "PHE", "TYR", "ASN", "GLU"]
    lines = []
    for index, name in enumerate(names, 1):
        xyz = np.array([index * 1.5, (index % 3) * 0.7, (index % 2) * 0.4]) + offset
        lines.append(atom("ATOM", index, "CA", name, chain, index, xyz))
    return "".join(lines)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class PocketEvidenceTests(unittest.TestCase):
    def test_evidence_class_separates_same_protein_exact_sequence_and_homolog(self):
        self.assertEqual(EVIDENCE.evidence_class({"UNP:P1"}, 0.92, 1.0), "same_protein")
        self.assertEqual(EVIDENCE.evidence_class(set(), 1.0, 1.0), "exact_sequence_match")
        self.assertEqual(EVIDENCE.evidence_class(set(), 0.94, 1.0), "close_structural_homolog")

    def test_overlapping_evidence_boxes_merge_when_combined_volume_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = []
            # The first two ligands overlap directly.  The third occupies an
            # adjacent but strongly overlapping search region, so the final
            # recommendation should consolidate all three observations.
            for index, offset in enumerate((0.0, 2.0, 12.0), 1):
                path = root / f"ligand{index}.pdb"
                path.write_text("".join(
                    atom("HETATM", atom_index, f"C{atom_index}", "LIG", "A", index,
                         (offset + atom_index, 0.0, 0.0))
                    for atom_index in range(1, 5)
                ))
                rows.append({"entry": f"E{index}", "ligand": "LIG",
                             "ligand_chain": "A", "aligned_ligand_pdb": path.name,
                             "evidence_class": "same_protein", "matched_cavity": None})
            groups = EVIDENCE.group_ligand_sites(
                {"evidence": rows}, root,
                atom_contact_cutoff=1.1, minimum_ligand_overlap=0.5,
            )
            self.assertEqual([group["member_count"] for group in groups], [3])
            self.assertEqual(groups[0]["box"]["size_x"], 26.0)
            self.assertEqual(groups[0]["box"]["center_x"], 8.5)
            self.assertEqual(groups[0]["representative_ligand"]["entry"], "E3")
            self.assertEqual(groups[0]["site_identity"]["canonical_label"], "L1")
            self.assertEqual(groups[0]["minimum_box_overlap_fraction"], 0.35)
            self.assertEqual(groups[0]["maximum_combined_box_volume_angstrom3"], 64000.0)

    def test_box_overlap_does_not_merge_past_the_recorded_volume_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = []
            for index, offset in enumerate((0.0, 12.0), 1):
                path = root / f"ligand{index}.pdb"
                path.write_text(atom("HETATM", 1, "C1", "LIG", "A", index,
                                     (offset, 0.0, 0.0)))
                rows.append({"entry": f"E{index}", "ligand": "LIG",
                             "ligand_chain": "A", "ligand_residue": str(index),
                             "aligned_ligand_pdb": path.name,
                             "evidence_class": "same_protein", "matched_cavity": None})
            groups = EVIDENCE.group_ligand_sites(
                {"evidence": rows}, root, maximum_combined_box_volume=17000.0,
            )
            self.assertEqual(len(groups), 2)

    def test_same_fpocket_number_does_not_merge_spatially_separate_sites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = []
            for index, offset in enumerate((0.0, 30.0), 1):
                path = root / f"ligand{index}.pdb"
                path.write_text(atom("HETATM", 1, "C1", "LIG", "A", index,
                                     (offset, 0.0, 0.0)))
                rows.append({"entry": f"E{index}", "ligand": "LIG",
                             "ligand_chain": "A", "aligned_ligand_pdb": path.name,
                             "evidence_class": "same_protein", "matched_cavity": 3,
                             "pocket_relationships": [{
                                 "pocket_number": 3, "cavity_match": True,
                                 "all_heavy_atoms_inside": True,
                             }]})
            groups = EVIDENCE.group_ligand_sites({"evidence": rows}, root)
            # Pocket numbers are local identifiers, not proof that distant
            # ligand observations occupy one physical site.
            self.assertEqual(len(groups), 2)
            self.assertEqual(
                [group["site_identity"]["canonical_label"] for group in groups],
                ["P3", "P3"],
            )

    def test_recommended_box_contains_corresponding_fpocket_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            cavity_root = Path(directory)
            evidence_root = cavity_root / "pdb_site_evidence"
            evidence_root.mkdir()
            ligand = evidence_root / "1ABC_LIG_A_1.pdb"
            ligand.write_text(atom("HETATM", 1, "C1", "LIG", "A", 1,
                                   (0.0, 0.0, 0.0)))
            frozen = cavity_root / "frozen_pockets"
            frozen.mkdir()
            (frozen / "pocket1_atm.pdb").write_text(
                atom("ATOM", 1, "CA", "ALA", "A", 1, (-15.0, 0.0, 0.0))
                + atom("ATOM", 2, "CA", "ALA", "A", 2, (15.0, 0.0, 0.0))
            )
            row = {
                "entry": "1ABC", "ligand": "LIG", "ligand_chain": "A",
                "ligand_residue": "1", "aligned_ligand_pdb": ligand.name,
                "evidence_class": "same_protein", "matched_cavity": 1,
                "pocket_relationships": [{
                    "pocket_number": 1, "cavity_match": True,
                    "all_heavy_atoms_inside": True,
                }],
            }
            group = EVIDENCE.group_ligand_sites(
                {"evidence": [row]}, evidence_root,
            )[0]
            # A cavity may support the site without forcing an oversized
            # docking region.  The 38 A cavity-inclusive extent exceeds the
            # default 36 A per-axis cap, so the ligand-contained box is kept.
            self.assertEqual(group["box"]["size_x"], 26.0)
            self.assertEqual(group["box_evidence"]["included_fpocket_candidates"], [])
            self.assertEqual(group["maximum_box_dimension_angstrom"], 36.0)
            self.assertEqual(group["box_evidence"]["basis"], "aligned ligand heavy atoms")

    def test_uncontained_contact_match_cannot_merge_remote_ligands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = []
            for index, offset in enumerate((0.0, 30.0), 1):
                path = root / f"ligand{index}.pdb"
                path.write_text(atom("HETATM", 1, "C1", "LIG", "A", index,
                                     (offset, 0.0, 0.0)))
                rows.append({
                    "entry": f"E{index}", "ligand": "LIG", "ligand_chain": "A",
                    "aligned_ligand_pdb": path.name, "evidence_class": "same_protein",
                    "matched_cavity": 3,
                    "pocket_relationships": [{
                        "pocket_number": 3, "cavity_match": True,
                        "all_heavy_atoms_inside": False,
                    }],
                })
            groups = EVIDENCE.group_ligand_sites({"evidence": rows}, root)
            self.assertEqual(len(groups), 2)
            self.assertTrue(all(group["site_identity"]["canonical_label"].startswith("L")
                                for group in groups))

    def test_chain_selection_prefers_ligand_chain_and_flags_ambiguous_fallback(self):
        def alignment(chain):
            return {"chain_id": chain, "rank_score": 1.0, "rmsd": 0.2}

        strong_other = (alignment("B"), {"contact_fraction": 1.0, "minimum_distance_angstrom": 1.0})
        same_chain = (alignment("A"), {"contact_fraction": 0.7, "minimum_distance_angstrom": 2.0})
        chosen, ambiguous, used_same_chain = EVIDENCE.choose_ligand_alignment(
            [strong_other, same_chain], "A",
        )
        self.assertEqual(chosen[0]["chain_id"], "A")
        self.assertFalse(ambiguous)
        self.assertTrue(used_same_chain)

        near_tie_a = (alignment("B"), {"contact_fraction": 0.8, "minimum_distance_angstrom": 1.2})
        near_tie_b = (alignment("C"), {"contact_fraction": 0.75, "minimum_distance_angstrom": 1.5})
        _, ambiguous, used_same_chain = EVIDENCE.choose_ligand_alignment(
            [near_tie_a, near_tie_b], "Z",
        )
        self.assertTrue(ambiguous)
        self.assertFalse(used_same_chain)

        # A named source chain that exists but failed structural acceptance
        # must not be silently replaced by another related subunit.
        _, ambiguous, used_same_chain = EVIDENCE.choose_ligand_alignment(
            [strong_other], "A", available_chain_ids={"A", "B"},
        )
        self.assertTrue(ambiguous)
        self.assertFalse(used_same_chain)

    def test_representative_prefers_exact_sequence_over_larger_homolog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = []
            for entry, evidence_class, atom_count in (
                ("EXACT", "exact_sequence_match", 20),
                ("HOMOLOG", "close_structural_homolog", 40),
            ):
                path = root / f"{entry}.pdb"
                path.write_text("".join(
                    atom("HETATM", index, f"C{index}", "LIG", "A", 1,
                         (index * 0.05, 0.0, 0.0))
                    for index in range(1, atom_count + 1)
                ))
                rows.append({
                    "entry": entry, "ligand": "LIG", "ligand_chain": "A",
                    "aligned_ligand_pdb": path.name,
                    "ligand_heavy_atom_count": atom_count,
                    "evidence_class": evidence_class,
                })
            group = EVIDENCE.group_ligand_sites({"evidence": rows}, root)[0]
            self.assertEqual(group["representative_ligand"]["entry"], "EXACT")
            self.assertEqual(
                group["representative_ligand"]["evidence_class"],
                "exact_sequence_match",
            )

    def test_cavity_match_ignores_incidental_box_containment(self):
        ligand = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        pockets = {
            1: ligand + np.array([3.0, 0.0, 0.0]),
            2: ligand + np.array([20.0, 0.0, 0.0]),
        }
        scores, matched, reason = EVIDENCE.classify_cavity_match(ligand, pockets)
        self.assertEqual(matched, 1)
        self.assertGreater(scores[1]["ligand_contact_fraction"], scores[2]["ligand_contact_fraction"])
        self.assertIn("unique cavity match", reason)

    def test_equivalent_homooligomer_chain_prefers_reference_chain_label(self):
        common = (1.0, 1.0, 1.0)
        ranked = [
            (*common, "A", "chain-a", [], {"UNP:P1"}),
            (*common, "B", "chain-b", [], {"UNP:P1"}),
        ]
        selected = EVIDENCE.choose_alignment_candidate(ranked, "A", {"UNP:P1"})
        self.assertEqual(selected[3], "A")

    def test_protein_database_identifiers_parse_chain_specific_uniprot_accessions(self):
        text = (
            "DBREF  4EY4 A    2   543  UNP    P22303   ACES_HUMAN      33    574\n"
            "DBREF  4EY4 B    2   543  UNP    P22303   ACES_HUMAN      33    574\n"
        )
        self.assertEqual(EVIDENCE.protein_database_identifiers(text), {
            "A": {"UNP:P22303"}, "B": {"UNP:P22303"},
        })

    def test_ligand_filter_excludes_water_and_ions(self):
        text = atom("HETATM", 1, "O", "HOH", "A", 1, (0, 0, 0), "O")
        text += atom("HETATM", 2, "ZN", "ZN", "A", 2, (0, 0, 0), "ZN")
        for index in range(6):
            text += atom("HETATM", index + 3, f"C{index}", "LIG", "B", 9, (index, 0, 0))
        ligands = EVIDENCE.deposited_ligands(text, "1ABC")
        self.assertEqual([(item.name, len(item.atoms)) for item in ligands], [("LIG", 6)])

    def test_crystallization_additive_is_not_site_evidence(self):
        text = "".join(
            atom("HETATM", index, f"C{index}", "GOL", "A", 10, (index, 0, 0))
            for index in range(1, 7)
        )
        self.assertEqual(EVIDENCE.deposited_ligands(text, "1ABC"), [])

    def test_modified_polymer_residue_is_not_ligand_evidence(self):
        text = "MODRES 1ABC CSO A  67  CYS  CYSTEINE S-HYDROXYLATED\n"
        for index, name in enumerate(("N", "CA", "C", "O", "CB", "SG"), 1):
            text += atom("HETATM", index, name, "CSO", "A", 67, (index, 0, 0))
        self.assertEqual(EVIDENCE.deposited_ligands(text, "1ABC"), [])

    def test_superposition_recovers_translated_chain(self):
        reference = EVIDENCE.protein_chains(protein())["A"]
        moving = EVIDENCE.protein_chains(protein(offset=(8, -4, 3)))["A"]
        pairs, identity, coverage = EVIDENCE.chain_match(reference, moving)
        rotation, translation, rmsd = EVIDENCE.superposition(reference, moving, pairs)
        self.assertAlmostEqual(identity, 1.0)
        self.assertAlmostEqual(coverage, 1.0)
        self.assertLess(rmsd, 1e-10)
        fitted = moving[0].xyz @ rotation + translation
        np.testing.assert_allclose(fitted, reference[0].xyz, atol=1e-10)

    def test_collection_records_evidence_without_selecting_a_pocket(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receptor = root / "target.pdb"
            receptor.write_text(protein())
            boxes = []
            for index, center in enumerate(((5.0, 0.0, 0.0), (25.0, 0.0, 0.0)), 1):
                box = root / f"pocket{index}.conf"
                box.write_text(
                    "\n".join(f"center_{axis} = {value}" for axis, value in zip("xyz", center))
                    + "\nsize_x = 10\nsize_y = 10\nsize_z = 10\n"
                )
                boxes.append(box)
            candidate = protein(offset=(10, 0, 0))
            for index in range(6):
                candidate += atom("HETATM", 50 + index, f"C{index}", "DRG", "Z", 1,
                                  (15.0 + index * 0.1, 0.0, 0.0))
            search = json.dumps({"result_set": [{"identifier": "9XYZ_1"}]}).encode()

            def opener(request, timeout=30):
                if "search.rcsb.org" in request.full_url:
                    return FakeResponse(search)
                return FakeResponse(candidate.encode())

            record = EVIDENCE.collect_pocket_evidence(
                receptor, boxes, root / "evidence", query_identity_cutoff=0.9,
                max_entries=5, opener=opener,
            )
            self.assertEqual(record["selection_policy"], "evidence_only_user_decides")
            self.assertEqual(record["evidence"][0]["nearest_pocket"], 1)
            self.assertTrue(record["evidence"][0]["ligand_fully_inside_box"])
            self.assertEqual(record["evidence"][0]["ligand_heavy_atom_count"], 6)
            aligned = root / "evidence" / record["evidence"][0]["aligned_ligand_pdb"]
            self.assertTrue(aligned.is_file())
            self.assertNotIn("selected_pocket", record)
            self.assertTrue((root / "evidence/pdb_ligand_site_evidence.json").is_file())
            self.assertTrue((root / "evidence/pdb_ligand_site_evidence.tsv").is_file())
            headings = (root / "evidence/pdb_ligand_site_evidence.tsv").read_text().splitlines()[0]
            self.assertIn("protein_identity_basis", headings)
            self.assertIn("shared_protein_identifiers", headings)

    def test_each_ligand_is_transformed_with_its_contacting_protein_chain(self):
        """Equivalent crystal copies must collapse onto one reference site."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receptor = root / "target.pdb"
            receptor.write_text(protein("A"))
            box = root / "pocket1.conf"
            box.write_text(
                "center_x = 5\ncenter_y = 0\ncenter_z = 0\n"
                "size_x = 14\nsize_y = 14\nsize_z = 14\n"
            )
            candidate = protein("A", offset=(10, 0, 0))
            candidate += protein("C", offset=(50, 0, 0))
            candidate += "".join(
                atom("HETATM", 100 + index, f"C{index}", "DRG", "B", 1,
                     (15.0 + index * 0.1, 0.0, 0.0))
                for index in range(6)
            )
            candidate += "".join(
                atom("HETATM", 200 + index, f"C{index}", "DRG", "D", 1,
                     (55.0 + index * 0.1, 0.0, 0.0))
                for index in range(6)
            )
            search = json.dumps({"result_set": [{"identifier": "9SYM_1"}]}).encode()

            def opener(request, timeout=30):
                if "search.rcsb.org" in request.full_url:
                    return FakeResponse(search)
                return FakeResponse(candidate.encode())

            record = EVIDENCE.collect_pocket_evidence(
                receptor, [box], root / "evidence", opener=opener,
            )
            self.assertEqual(len(record["evidence"]), 2)
            aligned_by_ligand_chain = {
                row["ligand_chain"]: row["aligned_chain"] for row in record["evidence"]
            }
            self.assertEqual(aligned_by_ligand_chain, {"B": "A", "D": "C"})
            self.assertEqual(len(record["ligand_site_groups"]), 1)
            self.assertEqual(record["ligand_site_groups"][0]["member_count"], 2)
            self.assertTrue(all(
                row["alignment_selection_basis"]
                == "ligand contact to structurally accepted protein chain"
                for row in record["evidence"]
            ))

    def test_collection_rejects_sequence_match_with_excessive_ca_rmsd(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receptor = root / "target.pdb"
            receptor.write_text(protein())
            box = root / "pocket1.conf"
            box.write_text(
                "center_x = 5\ncenter_y = 0\ncenter_z = 0\n"
                "size_x = 10\nsize_y = 10\nsize_z = 10\n"
            )
            candidate_lines = []
            names = ["ALA", "GLY", "SER", "THR", "LEU", "ASP", "LYS", "VAL", "PHE", "TYR", "ASN", "GLU"]
            for index, name in enumerate(names, 1):
                # Preserve sequence identity while introducing a non-rigid
                # backbone deformation that cannot be removed by Kabsch fit.
                xyz = (index * 1.5, 8.0 if index % 2 else -8.0, index % 3)
                candidate_lines.append(atom("ATOM", index, "CA", name, "A", index, xyz))
            search = json.dumps({"result_set": [{"identifier": "9BAD_1"}]}).encode()

            def opener(request, timeout=30):
                if "search.rcsb.org" in request.full_url:
                    return FakeResponse(search)
                return FakeResponse("".join(candidate_lines).encode())

            record = EVIDENCE.collect_pocket_evidence(
                receptor,
                [box],
                root / "evidence",
                maximum_ca_rmsd_angstrom=2.0,
                opener=opener,
            )
            self.assertEqual(record["evidence"], [])
            self.assertEqual(
                record["skipped"][0]["reason"],
                "C-alpha backbone RMSD exceeds structural-similarity limit",
            )
            self.assertGreater(record["skipped"][0]["ca_rmsd_angstrom"], 2.0)
            self.assertEqual(record["query"]["maximum_ca_rmsd_angstrom"], 2.0)

    def test_related_high_identity_protein_can_cross_an_accession_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receptor = root / "target.pdb"
            receptor.write_text(
                "DBREF  1REF A    1    12  UNP    P11111   TEST_ONE         1     12\n"
                + protein()
            )
            box = root / "pocket1.conf"
            box.write_text(
                "center_x = 5\ncenter_y = 0\ncenter_z = 0\n"
                "size_x = 10\nsize_y = 10\nsize_z = 10\n"
            )
            candidate = (
                "DBREF  2BAD A    1    12  UNP    P22222   TEST_TWO         1     12\n"
                + protein()
                + "".join(atom("HETATM", 100 + i, f"C{i}", "LIG", "B", 1, (i + 1, 0, 0)) for i in range(6))
            )
            search = json.dumps({"result_set": [{"identifier": "2BAD_1"}]}).encode()

            def opener(request, timeout=30):
                if "search.rcsb.org" in request.full_url:
                    return FakeResponse(search)
                return FakeResponse(candidate.encode())

            record = EVIDENCE.collect_pocket_evidence(
                receptor, [box], root / "evidence", opener=opener,
            )
            self.assertEqual(len(record["evidence"]), 1)
            self.assertEqual(
                record["evidence"][0]["protein_identity_basis"],
                "high sequence identity and C-alpha similarity despite accession mismatch",
            )
            self.assertEqual(record["evidence"][0]["shared_protein_identifiers"], [])
            self.assertEqual(record["query"]["reference_protein_identifiers"], ["UNP:P11111"])

    def test_summary_requires_full_containment_and_retains_partial_overlap_as_warning(self):
        record = {"evidence": [
            {"entry": "1AAA", "nearest_pocket": 2, "ligand_heavy_atom_fraction_inside_box": 1.0, "ligand_fully_inside_box": True},
            {"entry": "1AAB", "nearest_pocket": 2, "ligand_heavy_atom_fraction_inside_box": 0.7, "ligand_fully_inside_box": False},
            {"entry": "1AAC", "nearest_pocket": 1, "ligand_heavy_atom_fraction_inside_box": 0.0, "ligand_fully_inside_box": False},
            {"entry": "1AAD", "nearest_pocket": 1, "pocket_relationships": [
                {"pocket_number": 1, "heavy_atom_fraction_inside": 1.0, "all_heavy_atoms_inside": True},
                {"pocket_number": 3, "heavy_atom_fraction_inside": 0.25, "all_heavy_atoms_inside": False},
            ]},
        ]}
        self.assertEqual(EVIDENCE.summarize_pocket_evidence(record), {
            1: {"contained_ligands": 1, "overlapping_ligands": 0, "entries": ["1AAD"],
                "ligands": ["unknown"],
                "source_pairs": [{"pdb_id": "1AAD", "ligand_id": "unknown"}],
                "partial_entries": [], "partial_ligands": [], "partial_source_pairs": [],
                "example_ligand": None, "example_entry": "1AAD",
                "example_heavy_atom_count": 0, "example_aligned_ligand_pdb": None,
                "example_ccd_ideal_sdf": None},
            2: {"contained_ligands": 1, "overlapping_ligands": 1, "entries": ["1AAA"],
                "ligands": ["unknown"],
                "source_pairs": [{"pdb_id": "1AAA", "ligand_id": "unknown"}],
                "partial_entries": ["1AAB"], "partial_ligands": ["unknown"],
                "partial_source_pairs": [{"pdb_id": "1AAB", "ligand_id": "unknown"}],
                "example_ligand": None, "example_entry": "1AAA",
                "example_heavy_atom_count": 0, "example_aligned_ligand_pdb": None,
                "example_ccd_ideal_sdf": None},
            3: {"contained_ligands": 0, "overlapping_ligands": 1, "entries": [],
                "ligands": [], "source_pairs": [], "partial_entries": ["1AAD"],
                "partial_ligands": ["unknown"],
                "partial_source_pairs": [{"pdb_id": "1AAD", "ligand_id": "unknown"}],
                "example_ligand": None, "example_entry": None,
                "example_heavy_atom_count": 0, "example_aligned_ligand_pdb": None,
                "example_ccd_ideal_sdf": None},
        })

    def test_summary_lists_ligands_and_chooses_largest_as_example(self):
        record = {"evidence": [
            {"entry": "1AAA", "ligand": "SML", "ligand_heavy_atom_count": 12,
             "aligned_ligand_pdb": "aligned_ligands/small.pdb",
             "ccd_ideal_sdf": "ccd/SMALL_ideal.sdf", "nearest_pocket": 1,
             "ligand_heavy_atom_fraction_inside_box": 1.0, "ligand_fully_inside_box": True},
            {"entry": "2BBB", "ligand": "BIG", "ligand_heavy_atom_count": 31,
             "aligned_ligand_pdb": "aligned_ligands/big.pdb",
             "ccd_ideal_sdf": "ccd/BIG_ideal.sdf", "nearest_pocket": 1,
             "ligand_heavy_atom_fraction_inside_box": 1.0, "ligand_fully_inside_box": True},
        ]}
        item = EVIDENCE.summarize_pocket_evidence(record)[1]
        self.assertEqual(item["ligands"], ["BIG", "SML"])
        self.assertEqual(item["source_pairs"], [
            {"pdb_id": "1AAA", "ligand_id": "SML"},
            {"pdb_id": "2BBB", "ligand_id": "BIG"},
        ])
        self.assertEqual(item["example_ligand"], "BIG")
        self.assertEqual(item["example_heavy_atom_count"], 31)
        self.assertEqual(item["example_aligned_ligand_pdb"], "aligned_ligands/big.pdb")


if __name__ == "__main__":
    unittest.main()
