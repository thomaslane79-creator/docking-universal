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
    def test_sparse_high_rank_pockets_keep_shared_unique_colors(self):
        from docking_universal.pocket_metadata import POCKET_COLORS, POCKET_COLOR_RGB, POCKET_COLOR_NAMES
        rows = [{'pocket_file': f'pocket{i}_atm.pdb', 'decision': 'selected', 'rank_order': str(i)}
                for i in (1, 21, 35, 41)]
        colors = FIGURES._displayed_pocket_colors(rows)
        self.assertEqual(len(set(colors.values())), 4)
        for rank in (1, 21, 35, 41):
            color = colors[f'pocket{rank}_atm.pdb']
            self.assertEqual(color, POCKET_COLORS[rank - 1])
            self.assertEqual(POCKET_COLOR_RGB[POCKET_COLOR_NAMES[rank - 1]], tuple(int(color[i:i+2], 16) / 255 for i in (1, 3, 5)))
        self.assertEqual(len(set(POCKET_COLORS)), len(POCKET_COLORS))
        self.assertNotIn(FIGURES.EVIDENCE_GREEN, POCKET_COLORS)

    def test_lower_ranked_supported_and_selected_pockets_remain_visible(self):
        rows = [{'pocket_file': f'pocket{i}_atm.pdb', 'decision': 'selected', 'rank_order': str(i)}
                for i in range(1, 16)]
        sites = [{'label': 'P12', 'observations': [], 'member_numbers': [12]}]
        self.assertEqual(FIGURES.overview_visible_indices(rows, sites, [{'box_label': 'P14'}]),
                         list(range(1, 11)) + [12, 14])
        colors = FIGURES._displayed_pocket_colors(rows)
        self.assertNotEqual(colors['pocket12_atm.pdb'], colors['pocket1_atm.pdb'])
        self.assertNotEqual(colors['pocket12_atm.pdb'], FIGURES.EVIDENCE_GREEN)

    def test_ligand_evidence_uses_pocket_name_or_unscored_b_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            cavity = Path(temporary)
            diagnostics = cavity / 'pockets.tsv'
            ligand = cavity / 'ligand.pdb'
            ligand.write_text('END\n')
            retained = [{'pocket_file': 'pocket1_atm.pdb', 'score': '3'},
                        {'pocket_file': 'pocket2_atm.pdb', 'score': '2'}]
            selected = [{'site_source': 'input_bound_ligand', 'site_group': {
                'members': [{'label': 'P2', 'pocket_prediction': {'pocket_file': 'pocket2_atm.pdb'}},
                            {'label': 'B1'}],
                'ligands': [{'path': str(ligand), 'observation': {'ligand': 'ID8'}}]}}]
            groups = [{'site_identity': {'canonical_label': 'L1'}, 'pocket_recovery': {},
                       'representative_ligand': {'ligand': 'ABC', 'entry': '1ABC'}}]
            sites = FIGURES.overview_evidence(diagnostics, retained, groups, selected)
            self.assertEqual([site['label'] for site in sites], ['P2', 'B1'])
            self.assertEqual(sites[0]['member_numbers'], [2])
            self.assertTrue(FIGURES.plot_evidence_overview(diagnostics, retained, sites, cavity / 'plot.png'))

    def test_ligand_only_plot_does_not_invent_a_zero_score(self):
        import matplotlib.pyplot as plt
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(plt, 'close'):
            cavity = Path(temporary)
            sites = [{'label': 'B1', 'observations': [], 'member_numbers': []}]
            self.assertTrue(FIGURES.plot_evidence_overview(cavity / 'empty.tsv', [], sites, cavity / 'plot.png'))
            axis = plt.gcf().axes[0]
            self.assertEqual(len(axis.collections), 0)
            self.assertEqual([tick.get_text() for tick in axis.get_xticklabels()], [])
            self.assertIn('Unscored ligand-only sites are shown in panel B',
                          [text.get_text() for text in axis.texts])
        plt.close('all')

    def test_ligand_defined_region_preserves_merged_prediction_labels(self):
        note = FIGURES.approved_region_plot_note([{'box_label': 'B1',
            'site_source': 'input_bound_ligand', 'site_group': {'members': [
                {'label': 'P2', 'pocket_prediction': {'score': 35.82}},
                {'label': 'P11', 'pocket_prediction': {'score': 1.7}},
                {'label': 'B1'}]}}])
        self.assertEqual(note, 'Approved box B1 = input ligand; merged with P2, P11')

    def test_overview_legend_identifies_only_rendered_gray_pockets(self):
        with tempfile.TemporaryDirectory() as temporary:
            cavity = Path(temporary)
            diagnostics = cavity / 'pockets.tsv'
            frozen = cavity / 'frozen_pockets'
            frozen.mkdir()
            rows = [{'pocket_file': f'pocket{i}.pdb', 'rank_order': str(i)}
                    for i in range(1, 12)]
            for i in (1, 4, 11):
                (frozen / f'pocket{i}.pdb').touch()
            colors = {'pocket1.pdb': '#d62728', 'pocket11.pdb': '#1f77b4'}
            legend = FIGURES.pocket_surface_legend(diagnostics, rows, colors)
            self.assertEqual(legend, [('Cavity P1', '#d62728', 'surface'),
                                      ('Other pockets', '#999999', 'surface')])
            (frozen / 'pocket4.pdb').unlink()
            self.assertEqual(FIGURES.pocket_surface_legend(diagnostics, rows, colors),
                             [('Cavity P1', '#d62728', 'surface')])

    def test_control_experimental_renderer_uses_recorded_ligand_identity(self):
        import json
        with tempfile.TemporaryDirectory() as temporary:
            control = Path(temporary)
            interactions = control / '02_experimental_pose' / 'interactions'
            interactions.mkdir(parents=True)
            (interactions / 'run_manifest.json').write_text(json.dumps({
                'ligand_filter': {'resname': 'ID8', 'chain': 'B', 'position': '602'}
            }))
            inputs = control / '00_inputs'
            inputs.mkdir()
            (inputs / 'ID8_experimental.sdf').touch()
            sources = FIGURES.ensure_control_interactions(control, {}, control / 'protocol.json', None)
            self.assertEqual(sources[0][3], 'ID8:B:602')

    def test_ligand_box_approval_is_separate_from_p2rank_score(self):
        import matplotlib.pyplot as plt
        with tempfile.TemporaryDirectory() as temporary:
            cavity = Path(temporary)
            diagnostics = cavity / 'pockets.tsv'
            diagnostics.write_text('rank_order\tpocket_file\tscore\tdecision\tpocket_engine\n'
                                   '1\tpocket1_atm.pdb\t17.47\tselected\tp2rank\n')
            with mock.patch.object(plt, 'close'):
                FIGURES.plot_cavity_selection(diagnostics, 'target_bound_ligand.conf', cavity / 'panel.png',
                    ['target_bound_ligand.conf'],
                    approved_region_note=FIGURES.approved_region_plot_note([
                        {'box_label': 'B1', 'site_source': 'input_bound_ligand'}]))
                axis = plt.gcf().axes[0]
                notes = '\n'.join(text.get_text() for text in axis.texts)
                self.assertIn('Approved box B1 = input ligand; no prediction score', notes)
                self.assertIn('P2Rank predictions', notes)
                self.assertNotIn('selected P1', notes)
                self.assertEqual(axis.collections[0].get_offsets().tolist(), [[1., 17.47]])
            plt.close('all')

    def test_p2rank_score_contract_drives_the_same_ranking_panel(self):
        with tempfile.TemporaryDirectory() as temporary:
            cavity = Path(temporary)
            diagnostics = cavity / "pocket_selection_diagnostics.tsv"
            diagnostics.write_text(
                "rank_order\tpocket_file\tscore\tprobability\tdecision\tpocket_engine\n"
                "1\tpocket1_atm.pdb\t12.12\t0.639\tselected\tp2rank\n"
                "2\tpocket2_atm.pdb\t10.17\t0.547\tselected\tp2rank\n"
                "3\tpocket3_atm.pdb\t6.04\t0.298\tselected\tp2rank\n"
            )
            output = cavity / "panel_a.png"
            self.assertTrue(FIGURES.plot_cavity_selection(
                diagnostics, "target_pocket1.conf", output,
                ["target_pocket1.conf", "target_pocket2.conf", "target_pocket3.conf"],
            ))
            self.assertTrue(output.is_file())
            with diagnostics.open() as handle:
                rows = list(__import__("csv").DictReader(handle, delimiter="\t"))
            self.assertEqual(FIGURES.pocket_engine_name(rows), "P2Rank")
            self.assertEqual(FIGURES.pocket_score(rows[0]), "12.12")

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
            stale_ligand_box = output.with_name(output.stem + "_ligand_site_box.pdb")
            stale_ligand_box.write_text("legacy redundant box\n")
            group = {
                "pocket_recovery": {"best_matching_pocket": 1},
                "members": [{
                    "entry": "1ABC", "ligand": "LIG", "matched_cavity": 1,
                    "ligand_heavy_atom_count": 1,
                    "aligned_ligand_pdb": "aligned_ligands/1ABC_LIG_A_1.pdb",
                }],
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

            (pocket.parent / 'pocket2_atm.pdb').write_text(pocket.read_text())
            with mock.patch.object(FIGURES.subprocess, "run", side_effect=fake_pymol), \
                    mock.patch.object(FIGURES, "trim_white_png"):
                self.assertTrue(FIGURES.render_all_cavity_candidates(
                    diagnostics, "target_pocket1.conf", output,
                    output.with_suffix(".pse"), "pymol",
                    ligand_site_group=group, show_labels=True,
                ))
            pml = output.with_suffix(".pml").read_text()
            self.assertIn("show sticks, ligand_site_representative", pml)
            self.assertNotIn("ligand_site_box", pml)
            self.assertFalse(stale_ligand_box.exists())
            self.assertIn("show sticks, candidate_box_P1", pml)
            self.assertIn('label pocket_label_1, "Pocket 1"', pml)
            self.assertIn("set label_color, red, pocket_label_1", pml)
            self.assertIn("png " + str(output.resolve()) + ", 3600, 2400", pml)
            with mock.patch.object(FIGURES.subprocess, "run", side_effect=fake_pymol), \
                    mock.patch.object(FIGURES, "trim_white_png"), \
                    mock.patch.object(FIGURES, "_displayed_pocket_colors", return_value={"pocket1_atm.pdb": "#d62728", "pocket2_atm.pdb": "#1f77b4"}):
                self.assertTrue(FIGURES.render_all_cavity_candidates(
                    diagnostics, "target_pocket1.conf", output, output.with_suffix(".pse"), "pymol",
                    ["target_pocket1.conf"], selected_only=True,
                    additional_selected_regions=[{"box_label": "B1", "geometry": {
                        "center_x": 40, "center_y": 38, "center_z": 86,
                        "size_x": 26, "size_y": 26, "size_z": 26},
                        "site_group": {"members": [{"pocket_prediction": {"pocket_file": "pocket2_atm.pdb"}}],
                                       "ligands": [{"path": str(ligand), "observation": {}}]}}],
                ))
            pml = output.with_suffix(".pml").read_text()
            self.assertIn("show sticks, selected_box_1", pml)
            self.assertIn("show sticks, additional_selected_box_1", pml)
            self.assertIn("color marine, additional_selected_box_1", pml)
            self.assertIn("show surface, additional_pocket_1_1", pml)
            self.assertIn("color marine, additional_pocket_1_1", pml)
            self.assertIn("show sticks, additional_ligand_1_1", pml)
            self.assertIn("color green, additional_ligand_1_1", pml)

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
            {"ligand": "COH", "pocket_relationships": [{
                "pocket_number": 1, "cavity_match": True, "all_heavy_atoms_inside": True,
            }]},
            {"ligand": "NAG", "pocket_relationships": [{
                "pocket_number": 1, "cavity_match": True, "all_heavy_atoms_inside": True,
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

            overlay_colors = []

            def overlay(_receptor, _ligands, _colors, output, _session, _pymol):
                overlay_colors.append(tuple(_colors))
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
                    mock.patch.object(FIGURES, "render_poseedit_plip2d", return_value=False):
                outputs = FIGURES.build_compound_figures(study, "pymol")

            expected = [
                study / "report/ligand_a_site_1_panels_AB.png",
                study / "report/ligand_a_site_2_panels_AB.png",
            ]
            self.assertTrue(all(path.is_file() for path in expected))
            self.assertTrue(all(str(path) in outputs for path in expected))
            self.assertTrue(overlay_colors)
            self.assertTrue(all(
                colors == ("red", "marine", "gold") for colors in overlay_colors
            ))


if __name__ == "__main__":
    unittest.main()
