#!/usr/bin/env python3
"""Ensure report assets remain independent for every selected docking site."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "libexec" / "docking-universal-report-figures.py"
SPEC = importlib.util.spec_from_file_location("docking_universal_report_figures", SCRIPT)
FIGURES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIGURES)


class MultiSiteReportFigureTests(unittest.TestCase):
    def test_overlapping_fpocket_candidates_share_one_bounded_display_box(self):
        with tempfile.TemporaryDirectory() as temporary:
            cavity = Path(temporary)
            diagnostics = cavity / "pocket_selection.tsv"
            diagnostics.write_text(
                "decision\trank_order\tpocket_file\n"
                "selected\t1\tpocket1_atm.pdb\n"
                "selected\t2\tpocket2_atm.pdb\n"
                "selected\t3\tpocket3_atm.pdb\n"
            )
            frozen = cavity / "frozen_pockets"
            frozen.mkdir()
            centers = {1: (29.5, 15.0, 5.9), 2: (25.1, -0.4, 10.9), 3: (24.5, 2.2, 0.0)}
            for number, center in centers.items():
                (cavity / f"target_pocket{number}.conf").write_text(
                    f"center_x = {center[0]}\ncenter_y = {center[1]}\ncenter_z = {center[2]}\n"
                    "size_x = 26\nsize_y = 26\nsize_z = 26\n"
                )
                pocket_points = [center]
                if number == 1:
                    pocket_points = [(center[0], 0.0, center[2]),
                                     (center[0], 30.0, center[2])]
                (frozen / f"pocket{number}_atm.pdb").write_text("".join(
                    f"HETATM{index:5d}  C   POC A   1    {point[0]:8.3f}{point[1]:8.3f}{point[2]:8.3f}  1.00  0.00           C\n"
                    for index, point in enumerate(pocket_points, 1)
                ) + "END\n")
            colors = {f"pocket{number}_atm.pdb": color for number, color in enumerate(FIGURES.TOP_COLORS, 1)}
            rows = [
                {"decision": "selected", "rank_order": str(number),
                 "pocket_file": f"pocket{number}_atm.pdb"}
                for number in (1, 2, 3)
            ]
            groups = FIGURES.displayed_fpocket_box_groups(diagnostics, rows, colors)
            self.assertEqual([group["numbers"] for group in groups], [[1], [2, 3]])
            self.assertEqual(tuple(groups[1]["geometry"][f"size_{axis}"] for axis in "xyz"),
                             (26.0, 26.0, 26.0))

    def test_ligand_artifact_identity_includes_residue_number(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            correct = Path(temp_dir) / "4IG0_1FG_A_602.pdb"
            wrong_residue = Path(temp_dir) / "4IG0_1FG_A_601.pdb"
            correct.write_text("END\n")
            wrong_residue.write_text("END\n")
            member = {
                "entry": "4IG0", "ligand": "1FG",
                "ligand_chain": "A", "ligand_residue": "602",
            }
            self.assertTrue(FIGURES.ligand_artifact_matches_member(correct, member))
            self.assertFalse(FIGURES.ligand_artifact_matches_member(wrong_residue, member))

    def test_single_ligand_site_is_integrated_into_main_cavity_panel_at_high_resolution(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            diagnostics = study / "preparation/target/cavity/pocket_selection.tsv"
            diagnostics.parent.mkdir(parents=True)
            diagnostics.write_text(
                "decision\trank_order\tpocket_file\nselected\t1\tpocket1_atm.pdb\n"
            )
            receptor = study / "preparation/target/receptor/receptor.pdb"
            receptor.parent.mkdir(parents=True)
            receptor.write_text("END\n")
            pocket = diagnostics.parent / "frozen_pockets/pocket1_atm.pdb"
            pocket.parent.mkdir()
            pocket.write_text(
                "HETATM    1  C   POC A   1       1.000   2.000   3.000  1.00  0.00           C\nEND\n"
            )
            candidate_box = diagnostics.parent / "target_pocket1_box.pdb"
            candidate_box.write_text("HETATM    1  C   BOX A   1       0.000   0.000   0.000  1.00  0.00           C\nEND\n")
            (diagnostics.parent / "target_pocket1.conf").write_text(
                "center_x = 0\ncenter_y = 0\ncenter_z = 0\n"
                "size_x = 26\nsize_y = 26\nsize_z = 26\n"
            )
            ligand = diagnostics.parent / "pdb_site_evidence/aligned_ligands/1ABC_LIG_A_1.pdb"
            ligand.parent.mkdir(parents=True)
            ligand.write_text(
                "HETATM    1  C1  LIG A   1       0.000   0.000   0.000  1.00  0.00           C\nEND\n"
            )
            output = study / "report/cavity_panel_B_structure.png"
            output.parent.mkdir()
            group = {
                "representative_ligand": {
                    "entry": "1ABC", "ligand": "LIG",
                    "aligned_ligand_pdb": "aligned_ligands/1ABC_LIG_A_1.pdb",
                },
                "box": {"center_x": 0, "center_y": 0, "center_z": 0,
                        "size_x": 26, "size_y": 26, "size_z": 26},
            }

            def fake_pymol(_command, **_kwargs):
                output.write_bytes(b"not-a-real-png")
                return mock.Mock(returncode=0, stderr="")

            with mock.patch.object(FIGURES.subprocess, "run", side_effect=fake_pymol), \
                    mock.patch.object(FIGURES, "trim_white_png"):
                self.assertTrue(FIGURES.render_all_cavity_candidates(
                    diagnostics, "target_pocket1.conf", output,
                    output.with_suffix(".pse"), "pymol",
                    ligand_site_group=group,
                ))
            pml = output.with_suffix(".pml").read_text()
            self.assertIn("show sticks, ligand_site_representative", pml)
            self.assertIn("show sticks, ligand_site_box", pml)
            self.assertIn("show sticks, candidate_box_P1", pml)
            self.assertIn('label pocket_label_1, "Pocket 1"', pml)
            self.assertIn("set label_color, red, pocket_label_1", pml)
            self.assertIn("png " + str(output.resolve()) + ", 3600, 2400", pml)

    def test_multisite_overview_requires_at_least_two_sites(self):
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = Path(temporary) / "preparation/target/cavity/pocket_selection.tsv"
            diagnostics.parent.mkdir(parents=True)
            diagnostics.write_text("decision\trank_order\tpocket_file\n")
            self.assertFalse(FIGURES.build_ligand_site_overview(
                diagnostics, [{"members": [{}], "box": {}}],
                Path(temporary) / "overview.png", "pymol",
            ))

    def test_multisite_overview_renders_retained_fpockets_as_transparent_surfaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            diagnostics = study / "preparation/target/cavity/pocket_selection.tsv"
            diagnostics.parent.mkdir(parents=True)
            diagnostics.write_text(
                "decision\trank_order\tpocket_file\nselected\t1\tpocket1_atm.pdb\n"
            )
            receptor = study / "preparation/target/receptor/receptor.pdb"
            receptor.parent.mkdir(parents=True)
            receptor.write_text("END\n")
            pocket = diagnostics.parent / "frozen_pockets/pocket1_atm.pdb"
            pocket.parent.mkdir()
            pocket.write_text(
                "HETATM    1  C   POC A   1       1.000   2.000   3.000  1.00  0.00           C\nEND\n"
            )
            ligand_dir = diagnostics.parent / "pdb_site_evidence/aligned_ligands"
            ligand_dir.mkdir(parents=True)
            entries = ("1AAA", "2BBB", "3CCC", "4DDD", "5EEE", "6FFF", "7GGG")
            for entry in entries:
                (ligand_dir / f"{entry}_LIG_A_1.pdb").write_text(
                    "HETATM    1  C1  LIG A   1       0.000   0.000   0.000  1.00  0.00           C\nEND\n"
                )
            geometry = {"center_x": 0, "center_y": 0, "center_z": 0,
                        "size_x": 26, "size_y": 26, "size_z": 26}
            groups = [
                {"site_number": index, "members": [{"entry": entry, "ligand": "LIG",
                 "ligand_chain": "A", "ligand_residue": "1", "evidence_class": "same_protein",
                 "aligned_ligand_pdb": f"aligned_ligands/{entry}_LIG_A_1.pdb"}], "box": geometry}
                for index, entry in enumerate(entries, start=1)
            ]
            output = study / "report/ligand_site_overview.png"
            output.parent.mkdir()

            def fake_pymol(command, **_kwargs):
                Path(command[-1]).with_suffix(".png").write_bytes(b"not-a-real-png")
                return mock.Mock(returncode=0, stderr="")

            combined_page_sizes = []

            def fake_combine(_panels, combined_output, _start_index=0):
                combined_page_sizes.append((len(_panels), _start_index))
                combined_output.write_bytes(b"combined")
                return True

            with mock.patch.object(FIGURES.subprocess, "run", side_effect=fake_pymol), \
                    mock.patch.object(FIGURES, "trim_white_png"), \
                    mock.patch.object(FIGURES, "combine_ligand_site_panels", side_effect=fake_combine):
                self.assertTrue(FIGURES.build_ligand_site_overview(
                    diagnostics, groups, output, "pymol"
                ))
            pml = output.with_name("ligand_site_overview_site_1.pml").read_text()
            self.assertIn("show surface, fpocket_1", pml)
            self.assertIn("set transparency, 0.88, fpocket_1", pml)
            self.assertNotIn('label pocket_label_1, "Pocket 1"', pml)
            self.assertIn("color forest, site_ligand", pml)
            self.assertIn("show cartoon, receptor", pml)
            self.assertIn("zoom all, 16", pml)
            self.assertIn("set ray_clip_near, 0", pml)
            self.assertIn("clip slab, 200", pml)
            self.assertEqual(combined_page_sizes, [(6, 0), (1, 6), (7, 0)])

    def test_remote_singleton_without_fpocket_match_stays_table_only(self):
        self.assertFalse(FIGURES.ligand_site_group_deserves_figure({
            "member_count": 1, "matched_cavity_counts": {},
        }))
        self.assertTrue(FIGURES.ligand_site_group_deserves_figure({
            "member_count": 2, "matched_cavity_counts": {},
        }))
        self.assertTrue(FIGURES.ligand_site_group_deserves_figure({
            "member_count": 1, "matched_cavity_counts": {"3": 1},
        }))

    def test_ligand_site_figure_uses_translucent_fpocket_surface_and_frames_complete_box(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            diagnostics = study / "preparation/target/cavity/pocket_selection.tsv"
            diagnostics.parent.mkdir(parents=True)
            diagnostics.write_text(
                "decision\trank_order\tpocket_file\nselected\t1\tpocket1_atm.pdb\n"
            )
            receptor = study / "preparation/target/receptor/receptor.pdb"
            receptor.parent.mkdir(parents=True)
            receptor.write_text("END\n")
            pocket = diagnostics.parent / "frozen_pockets/pocket1_atm.pdb"
            pocket.parent.mkdir()
            pocket.write_text("END\n")
            ligand = diagnostics.parent / "pdb_site_evidence/aligned_ligands/1ABC_LIG_A_1.pdb"
            ligand.parent.mkdir(parents=True)
            ligand.write_text(
                "HETATM    1  C1  LIG A   1       0.000   0.000   0.000  1.00  0.00           C\nEND\n"
            )
            output = study / "report/ligand_site_group_1.png"
            output.parent.mkdir()
            group = {
                "site_number": 1,
                "members": [{
                    "entry": "1ABC", "ligand": "LIG", "ligand_chain": "A",
                    "ligand_residue": "1",
                    "evidence_class": "exact_sequence_match",
                    "aligned_ligand_pdb": "aligned_ligands/1ABC_LIG_A_1.pdb",
                }],
                "matched_cavity_counts": {"1": 1},
                "box": {"center_x": 0, "center_y": 0, "center_z": 0,
                        "size_x": 26, "size_y": 26, "size_z": 26},
            }

            def fake_pymol(command, **_kwargs):
                Path(command[-1]).with_suffix(".png").write_bytes(b"not-a-real-png")
                return mock.Mock(returncode=0, stderr="")

            with mock.patch.object(FIGURES.subprocess, "run", side_effect=fake_pymol), \
                    mock.patch.object(FIGURES, "trim_white_png"):
                self.assertTrue(FIGURES.build_ligand_site_group_figure(
                    diagnostics, group, output, "pymol"
                ))
            pml = output.with_suffix(".pml").read_text()
            self.assertIn("show surface, fpocket_1", pml)
            self.assertIn("set transparency_mode, 1", pml)
            self.assertIn("set ray_transparency_contrast, 0.25", pml)
            self.assertIn("set transparency, 0.86, fpocket_1", pml)
            self.assertIn("hide everything, proposed_box", pml)
            self.assertIn("color forest, representative_ligand", pml)
            self.assertIn("color forest, proposed_box", pml)
            self.assertIn("orient receptor", pml)
            self.assertIn("zoom all, 14", pml)

    def test_pocket_figure_excludes_partial_or_cavity_mismatched_ligands(self):
        record = {"evidence": [
            {"ligand": "GOOD", "pocket_relationships": [{
                "pocket_number": 1, "cavity_match": True, "all_heavy_atoms_inside": True,
            }]},
            {"ligand": "PARTIAL", "pocket_relationships": [{
                "pocket_number": 1, "cavity_match": True, "all_heavy_atoms_inside": False,
            }]},
            {"ligand": "INCIDENTAL", "pocket_relationships": [{
                "pocket_number": 1, "cavity_match": False, "all_heavy_atoms_inside": True,
            }]},
        ]}
        self.assertEqual(
            [row["ligand"] for row in FIGURES.supporting_ligand_rows(record, 1)],
            ["GOOD"],
        )

    def test_selected_box_numbers_map_to_the_matching_retained_pockets(self):
        rows = [
            {"decision": "selected", "rank_order": "1", "pocket_file": "pocket1_atm.pdb"},
            {"decision": "selected", "rank_order": "2", "pocket_file": "pocket4_atm.pdb"},
            {"decision": "selected", "rank_order": "3", "pocket_file": "pocket8_atm.pdb"},
            {"decision": "selected", "rank_order": "4", "pocket_file": "pocket10_atm.pdb"},
            {"decision": "selected", "rank_order": "5", "pocket_file": "pocket13_atm.pdb"},
        ]
        self.assertEqual(
            FIGURES._selected_pocket_files(rows, ["6C0N_pocket1.conf", "6C0N_pocket5.conf"]),
            [
                ("6C0N_pocket1.conf", "pocket1_atm.pdb"),
                ("6C0N_pocket5.conf", "pocket13_atm.pdb"),
            ],
        )

    def test_each_site_receives_distinct_report_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            for site in ("site_1", "site_2"):
                analysis = study / "compounds" / "ligand_a" / site / "pose_analysis"
                analysis.mkdir(parents=True)
                (analysis / "cluster_summary.csv").write_text(
                    "energy_rank,cluster_id,best_energy_kcal_per_mol,pose_count,rmsd_angstrom\n"
                    "1,1,-7.0,1,0.0\n"
                )

            def plot(_analysis, output, **_kwargs):
                output.write_bytes(b"plot")
                output.with_suffix(".csv").write_text(
                    "energy_rank,cluster_id,best_energy_kcal_per_mol,pose_count,rmsd_angstrom\n"
                    "1,1,-7.0,1,0.0\n"
                )
                return True

            def overlay(_receptor, _ligands, _colors, output, _session, _pymol):
                output.write_bytes(b"overlay")
                return True

            def combine(_first, _second, output, **_kwargs):
                output.write_bytes(b"combined")
                return True

            with mock.patch.object(FIGURES, "plot_clusters", side_effect=plot), \
                    mock.patch.object(FIGURES, "materialize_cluster_representatives", return_value=[]), \
                    mock.patch.object(FIGURES, "render_overlay", side_effect=overlay), \
                    mock.patch.object(FIGURES, "combine_panels", side_effect=combine), \
                    mock.patch.object(FIGURES, "combine_cluster_snapshots", return_value=False), \
                    mock.patch.object(FIGURES, "render_plip2d", return_value=False):
                outputs = FIGURES.build_compound_figures(study, "pymol", None)

            expected = [
                study / "report/ligand_a_site_1_panels_AB.png",
                study / "report/ligand_a_site_2_panels_AB.png",
            ]
            self.assertTrue(all(path.is_file() for path in expected))
            self.assertTrue(all(str(path) in outputs for path in expected))


if __name__ == "__main__":
    unittest.main()
