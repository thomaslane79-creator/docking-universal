"""Control figures are cluster summaries with independently identified minima."""
import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rdkit import Chem
from rdkit.Chem import AllChem

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("figures", ROOT / "libexec/docking-universal-report-figures.py")
figures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(figures)
pdf_spec = importlib.util.spec_from_file_location("pdf_report", ROOT / "libexec/docking-universal-pdf-report.py")
pdf_report = importlib.util.module_from_spec(pdf_spec)
pdf_spec.loader.exec_module(pdf_report)


class ControlLandscapeTests(unittest.TestCase):
    def test_pose_link_requires_matching_chemistry_and_exact_geometry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            self.assertTrue(figures.same_retained_pose(root / 'reference.sdf', root / 'reference.sdf'))
            self.assertFalse(figures.same_retained_pose(root / 'reference.sdf', root / 'all_poses.sdf'))
            self.assertFalse(figures.same_retained_pose(root / 'reference.sdf', root / 'missing.sdf'))

    def test_control_report_generates_verified_closest_and_top_three_links(self):
        from docking_universal.pose_visuals import read_pose_view
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            analysis = root / 'analysis'
            analysis.mkdir()
            self.fixture(analysis)
            (analysis / 'receptor.pdb').write_text('receptor')
            protocol = root / 'protocol.json'
            protocol.write_text('{}')
            for cid, index in ((1, 0), (99, 2)):
                cluster = analysis / f'cluster_{cid:03d}'
                (cluster / 'interactions').mkdir(parents=True)
                (cluster / 'interactions/report.xml').write_text('<report/>')
                molecules = list(Chem.SDMolSupplier(str(analysis / 'all_poses.sdf')))
                with Chem.SDWriter(str(cluster / 'representative.sdf')) as writer:
                    writer.write(molecules[index])
            interactions = root / 'best_interactions'
            interactions.mkdir()
            (interactions / 'report.xml').write_text('<report/>')
            molecules = list(Chem.SDMolSupplier(str(analysis / 'all_poses.sdf')))
            closest = root / 'best_rmsd_pose.sdf'
            with Chem.SDWriter(str(closest)) as writer:
                writer.write(molecules[1])
            def render(_xml, _sdf, output, *_args, **_kwargs):
                output.write_bytes(b'image')
                return True
            with mock.patch.object(figures, 'ensure_control_clusters', return_value=analysis), \
                 mock.patch.object(figures, 'first', return_value=analysis / 'reference.sdf'), \
                 mock.patch.object(figures, 'render_overlay', return_value=False), \
                 mock.patch.object(figures, 'ensure_control_interactions', return_value=[('lowest_rmsd', interactions, closest, 'UNL:Z:1')]), \
                 mock.patch.object(figures, 'render_plip2d', side_effect=render):
                outputs = figures.build_control_figures(root, protocol, None, None, None)
            view = read_pose_view(root / 'report/control_lowest_rmsd_plip2d.png')
            self.assertEqual(view['ligand'], closest.resolve())
            self.assertEqual(view['ligand_color'], 'red')
            self.assertIn(str(root / 'report/control_energy_rank_2_plip2d.png'), outputs)
            view = read_pose_view(root / 'report/control_energy_rank_2_plip2d.png')
            self.assertEqual(view['ligand_color'], 'marine')
            self.assertEqual(view['ligand'].name, 'control_overlay_pose_0003.sdf')

    def fixture(self, root):
        reference = Chem.AddHs(Chem.MolFromSmiles("CCO"))
        AllChem.EmbedMolecule(reference, randomSeed=42)
        poses = []
        for shift in (1.5, .4, 12):
            molecule = Chem.Mol(reference)
            for index in range(molecule.GetNumAtoms()):
                pos = molecule.GetConformer().GetAtomPosition(index)
                molecule.GetConformer().SetAtomPosition(index, (pos.x+shift, pos.y, pos.z))
            poses.append(molecule)
        for name, molecules in (("reference.sdf", [reference]), ("all_poses.sdf", poses)):
            with Chem.SDWriter(str(root / name)) as writer:
                for molecule in molecules:
                    writer.write(molecule)
        # The closest pose is within the lowest-energy cluster, but is not its
        # lowest-energy representative. A high-RMSD low-ranked cluster remains.
        (root / "pose_inventory.csv").write_text(
            "pose_id,cluster_id,seed,conformer,model,energy_kcal_per_mol\n"
            "1,1,10,conf1,1,-12\n2,1,10,conf1,2,-10\n3,99,11,conf2,1,-5\n")
        return reference

    def test_all_poses_no_fit_and_same_cluster_disagreement_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = self.fixture(root)
            points, audit = figures.control_pose_points(root, reference)
            self.assertEqual(audit["plotted_count"], 3)
            self.assertEqual(audit["excluded"], [])
            self.assertEqual([p["pose_id"] for p in points], [1, 2, 3])
            self.assertAlmostEqual(points[1]["rmsd_angstrom"], .4, places=3)
            self.assertAlmostEqual(points[2]["rmsd_angstrom"], 12, places=3)
            self.assertEqual(min(points, key=lambda p: p["energy_kcal_per_mol"])["pose_id"], 1)
            self.assertEqual(min(points, key=lambda p: p["rmsd_angstrom"])["pose_id"], 2)

    def test_render_exports_every_cluster_and_independent_member_minima(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            output = root / "control_panel_A_cluster.png"
            with mock.patch.object(figures, "cluster_rows", side_effect=AssertionError("No cluster prefilter")):
                self.assertTrue(figures.plot_clusters(root, output, root / "reference.sdf", "test ligand"))
            with output.with_suffix(".csv").open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["cluster_id"], "1")
            self.assertEqual(rows[0]["lowest_energy_pose_id"], "1")
            self.assertEqual(rows[0]["lowest_rmsd_pose_id"], "2")
            self.assertEqual(rows[0]["minima_from_same_pose"], "False")
            self.assertEqual(float(rows[0]["best_energy_kcal_per_mol"]), -12)
            self.assertAlmostEqual(float(rows[0]["rmsd_angstrom"]), .4, places=3)
            self.assertAlmostEqual(float(rows[0]["lowest_energy_pose_rmsd_angstrom"]), 1.5, places=3)
            self.assertEqual(float(rows[0]["lowest_rmsd_pose_energy_kcal_per_mol"]), -10)
            audit = json.loads(output.with_suffix(".json").read_text())
            self.assertEqual(audit["cluster_limit"], 20)
            self.assertIsNone(audit["rmsd_cutoff"])
            self.assertTrue(output.is_file())
            caption = pdf_report.control_landscape_description(output, "test ligand")
            self.assertEqual(audit["plot_scope"], "top20_control_clusters_plus_global_lowest_rmsd_pose")
            self.assertEqual(audit["plotted_pose_count"], 3)
            self.assertIn("2 control pose clusters", caption)
            self.assertIn("may belong to different poses", caption)
            self.assertEqual(audit["highlight_style"], "energy_rank_colors")
            self.assertEqual(audit["highlighted_cluster_ids"], [1, 99])
            self.assertIn("Red, blue, and gold", caption)
            self.assertIn("number of docked poses", caption)
            self.assertIn("one actual globally lowest-RMSD evaluable pose", caption)
            self.assertNotIn("diamond", caption)
            self.assertNotIn("star", caption)
            self.assertIn("top 20 clusters by lowest energy", caption)

    def test_all_pose_plot_remains_a_separate_explicit_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            output = root / "separate_all_pose_diagnostic.png"
            self.assertTrue(figures.plot_control_poses(root, output, root / "reference.sdf", "TLF"))
            with output.with_suffix(".csv").open() as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 3)
            self.assertEqual(json.loads(output.with_suffix(".json").read_text())["plot_scope"],
                             "all_retained_control_poses")

    def test_cluster_graph_states_independent_minima_on_the_figure(self):
        from matplotlib.figure import Figure

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            with mock.patch.object(Figure, "text", autospec=True, side_effect=Figure.text) as text:
                self.assertTrue(figures.plot_clusters(root, root / "clusters.png",
                                                     root / "reference.sdf", "test ligand"))
            labels = [call.args[3] for call in text.call_args_list if len(call.args) > 3]
            self.assertIn("Cluster circles: minimum energy and minimum experimental RMSD; these may come from different poses.\n"
                          "Green circle: globally lowest-RMSD pose, plotted at its own binding energy.", labels)

    def test_original_circle_population_and_axis_contract(self):
        from matplotlib.axes import Axes

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            with mock.patch.object(Axes, "scatter", autospec=True, side_effect=Axes.scatter) as scatter:
                self.assertTrue(figures.plot_clusters(root, root / "clusters.png",
                                                     root / "reference.sdf", "test ligand"))
            self.assertEqual(scatter.call_count, 3)  # Cluster circles, white-spaced ring, closest pose.
            call = scatter.call_args_list[0]
            self.assertEqual(call.args[1], [-12, -5])
            self.assertAlmostEqual(call.args[2][0], .4, places=3)
            self.assertAlmostEqual(call.args[2][1], 12, places=3)
            self.assertEqual(call.kwargs["s"], [86, 78])  # Two poses versus one.
            self.assertEqual(call.kwargs["c"], list(figures.TOP_COLORS[:2]))
            self.assertEqual(call.kwargs["marker"], "o")
            ring = scatter.call_args_list[1]
            closest = scatter.call_args_list[2]
            self.assertEqual(closest.args[1], [-10])  # NOT the cluster's minimum energy (-12).
            self.assertAlmostEqual(closest.args[2][0], .4, places=3)
            self.assertEqual(closest.kwargs["marker"], "o")
            self.assertEqual(closest.kwargs["edgecolors"], "black")
            self.assertEqual(closest.kwargs["facecolors"], figures.TOP_COLORS[0])
            self.assertEqual(ring.kwargs["facecolors"], "white")
            self.assertEqual(ring.kwargs["edgecolors"], "#008a45")
            self.assertEqual(ring.args[1:3], closest.args[1:3])
            self.assertLess(ring.kwargs["zorder"], closest.kwargs["zorder"])
            gap = (ring.kwargs["s"] ** .5 - ring.kwargs["linewidths"]
                   - closest.kwargs["s"] ** .5 - closest.kwargs["linewidths"]) / 2
            self.assertAlmostEqual(gap, 3.0)
            self.assertIn("binding energy", call.args[0].get_xlabel())
            self.assertIn("Experimental RMSD", call.args[0].get_ylabel())
            self.assertEqual(call.args[0].get_title(), "test ligand: pose recovery")

    def test_incomplete_cluster_minima_are_not_claimed_as_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = self.fixture(root)
            with mock.patch.object(figures, "rmsd_between", side_effect=[1.5, float("nan"), 12]):
                points, audit = figures.control_cluster_points(root, reference)
            self.assertEqual([point["cluster_id"] for point in points], [99])
            self.assertEqual(audit["excluded_cluster_ids"], ["1"])

    def test_white_gap_preserves_each_energy_color_and_legend_is_only_a_ring(self):
        from matplotlib.axes import Axes

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = self.fixture(root)
            for rank, color in enumerate(figures.TOP_COLORS, 1):
                with self.subTest(rank=rank):
                    poses = [{"pose_id": index, "cluster_id": str(index),
                              "energy_kcal_per_mol": -15 + index,
                              "rmsd_angstrom": .4 if index == rank else 3.0}
                             for index in range(1, 4)]
                    with mock.patch.object(figures, "read_molecule", return_value=reference), \
                         mock.patch.object(figures, "control_pose_points", return_value=(poses,
                             {"inventory_count": 3, "plotted_count": 3, "excluded": []})), \
                         mock.patch.object(Axes, "scatter", autospec=True, side_effect=Axes.scatter) as scatter, \
                         mock.patch.object(Axes, "legend", autospec=True, side_effect=Axes.legend) as legend:
                        self.assertTrue(figures.plot_clusters(root, root / "clusters.png",
                                                             root / "reference.sdf", "test"))
                    self.assertEqual(scatter.call_args_list[1].kwargs["facecolors"], "white")
                    self.assertEqual(scatter.call_args_list[2].kwargs["facecolors"], color)
                    ring = legend.call_args.kwargs["handles"][-1]
                    self.assertEqual(ring.get_markerfacecolor(), "white")
                    self.assertEqual(ring.get_markeredgecolor(), "#008a45")
                    self.assertEqual(ring.get_marker(), "o")
                    self.assertIn("Top 20 clusters by energy + globally lowest-RMSD pose",
                                  legend.call_args.kwargs["title"])

    def test_no_top_twenty_cluster_prefilter(self):
        poses = [{"pose_id": index, "cluster_id": str(index), "energy_kcal_per_mol": -index,
                  "rmsd_angstrom": index / 10} for index in range(1, 26)]
        with mock.patch.object(figures, "control_pose_points", return_value=(poses,
                {"inventory_count": 25, "plotted_count": 25, "excluded": []})):
            points, audit = figures.control_cluster_points(Path("unused"), None)
        self.assertEqual(len(points), 25)
        self.assertEqual(audit["plotted_count"], 25)

    def test_top_twenty_clusters_plus_global_pose_exports_all_clusters(self):
        from matplotlib.axes import Axes

        poses = [{"pose_id": index, "cluster_id": str(index), "energy_kcal_per_mol": -index,
                  "rmsd_angstrom": index / 10} for index in range(1, 26)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = self.fixture(root)
            output = root / "clusters.png"
            with mock.patch.object(figures, "read_molecule", return_value=reference), \
                 mock.patch.object(figures, "control_pose_points", return_value=(poses,
                         {"inventory_count": 25, "plotted_count": 25, "excluded": []})), \
                 mock.patch.object(Axes, "scatter", autospec=True, side_effect=Axes.scatter) as scatter:
                self.assertTrue(figures.plot_clusters(root, output, root / "reference.sdf", "test"))
            with output.with_suffix(".csv").open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 25)
            shown = [int(row["cluster_id"]) for row in rows if row["displayed_in_plot"] == "True"]
            self.assertEqual(shown, list(range(25, 5, -1)))
            audit = json.loads(output.with_suffix(".json").read_text())
            self.assertEqual(audit["plotted_count"], 20)
            self.assertEqual(audit["cluster_limit"], 20)
            self.assertEqual(audit["all_evaluable_cluster_count"], 25)
            self.assertEqual(audit["plotted_cluster_ids"], shown)
            self.assertEqual(audit["highlighted_cluster_ids"], [25, 24, 23])
            self.assertEqual(scatter.call_count, 3)
            self.assertEqual(scatter.call_args_list[0].kwargs["c"], list(figures.TOP_COLORS) + ["#b8c0c8"] * 17)
            self.assertEqual(scatter.call_args_list[0].kwargs["s"], [78] * 20)
            # Globally closest cluster 1 must remain visible despite its energy rank.
            self.assertEqual(audit["closest_to_crystal_pose_id"], 1)
            self.assertEqual(scatter.call_args.args[1], [-1])
            self.assertEqual(scatter.call_args.args[2], [.1])
            self.assertEqual(scatter.call_args.kwargs["facecolors"], "#b8c0c8")
            axis = scatter.call_args.args[0]
            self.assertLess(axis.get_xlim()[0], -25)
            self.assertGreater(axis.get_xlim()[1], -1)  # The high-energy closest pose is not clipped.
            self.assertIsNone(audit["rmsd_cutoff"])

    def test_caption_still_describes_older_shape_marker_images_truthfully(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "old_clusters.png"
            output.with_suffix(".json").write_text(json.dumps({
                "plot_scope": "top20_control_clusters_independent_minima", "plotted_count": 20}))
            caption = pdf_report.control_landscape_description(output, "TLF")
            self.assertIn("red diamond", caption)
            self.assertIn("blue star", caption)
            self.assertNotIn("Red, blue, and gold", caption)

    def test_3d_overlay_uses_actual_closest_pose_with_its_top_three_color(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = self.fixture(root)
            output = root / "clusters.png"
            self.assertTrue(figures.plot_clusters(root, output, root / "reference.sdf", "test"))
            paths, colors, audit = figures.control_overlay_poses(root, output, root)
            self.assertEqual(colors, ["red", "marine", "red"])
            self.assertEqual([row["pose_id"] for row in audit["poses"]], [1, 3, 2])
            closest = Chem.SDMolSupplier(str(paths[-1]), removeHs=False)[0]
            self.assertAlmostEqual(figures.rmsd_between(reference, closest), .4, places=3)
            self.assertEqual(audit["closest_to_crystal_pose"]["energy_kcal_per_mol"], -10)
            output.with_suffix(".manifest.json").write_text(json.dumps(audit))
            self.assertIn("otherwise green", pdf_report.control_overlay_description(output))

    def test_2d_interactions_use_global_closest_pose_not_lowest_energy_pose(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = self.fixture(root)
            closest_comparison = root / "closest_comparison"
            closest_comparison.mkdir()
            best_sdf = closest_comparison / "best_rmsd_pose.sdf"
            closest_molecule = list(Chem.SDMolSupplier(str(root / "all_poses.sdf"), removeHs=False))[1]
            with Chem.SDWriter(str(best_sdf)) as writer:
                writer.write(closest_molecule)
            (closest_comparison / "best_rmsd_complex.pdb").write_text("END\n")
            protocol = {
                "global_top_ranked_pose": {"summary": str(root / "energy_comparison/summary.json")},
                "global_best_sampled_pose": {"summary": str(closest_comparison / "summary.json")},
            }
            with mock.patch.object(figures.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
                sources = figures.ensure_control_interactions(root, protocol, root / "protocol.json", "plip")
            label, interactions, ligand, ligand_id = sources[-1]
            self.assertEqual(label, "lowest_rmsd")
            self.assertEqual(ligand, best_sdf)
            self.assertEqual(ligand_id, "UNL:Z:1")
            command = run.call_args.args[0]
            self.assertEqual(command[2], str(closest_comparison / "best_rmsd_complex.pdb"))
            self.assertEqual(command[command.index("--typed-ligand-sdf") + 1], str(best_sdf))
            self.assertAlmostEqual(figures.rmsd_between(reference,
                Chem.SDMolSupplier(str(ligand), removeHs=False)[0]), .4, places=3)

    def test_same_pose_in_both_roles_is_only_rendered_once_in_its_energy_color(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            output = root / "clusters.png"
            with mock.patch.object(figures, "rmsd_between", side_effect=[.1, .4, 12]):
                self.assertTrue(figures.plot_clusters(root, output, root / "reference.sdf", "test"))
            paths, colors, audit = figures.control_overlay_poses(root, output, root)
            self.assertEqual([row["pose_id"] for row in audit["poses"]], [3, 1])
            self.assertEqual(colors, ["marine", "red"])

    def test_legacy_caption_discloses_cluster_filtering(self):
        caption = pdf_report.control_landscape_description(Path("missing_legacy.png"), "TLF")
        self.assertIn("top 20 clusters", caption)
        self.assertIn("closer-to-crystal poses", caption)

    def test_control_without_experimental_reference_never_uses_docked_reference(self):
        with mock.patch.object(figures, "cluster_rows", side_effect=AssertionError("No docked reference")):
            self.assertFalse(figures.plot_clusters(Path("missing"), Path("missing.png"), control_label="TLF"))

    def test_invalid_rmsd_is_excluded_with_reason_never_replaced_by_median(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = self.fixture(root)
            with mock.patch.object(figures, "rmsd_between", side_effect=[1.5, float("nan"), 12]):
                points, audit = figures.control_pose_points(root, reference)
            self.assertEqual(len(points), 2)
            self.assertEqual(audit["excluded"][0]["pose_id"], "2")
            self.assertEqual([p["rmsd_angstrom"] for p in points], [1.5, 12])

    def test_prospective_cluster_plot_does_not_fabricate_unknown_rmsd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = self.fixture(root)
            rows = [{"cluster_id": 1, "energy_rank": 1, "best_energy_kcal_per_mol": -12},
                    {"cluster_id": 99, "energy_rank": 2, "best_energy_kcal_per_mol": -5}]
            output = root / "prospective.png"
            with mock.patch.object(figures, "cluster_rows", return_value=rows), \
                 mock.patch.object(figures, "retained_cluster_representatives", return_value={1: reference, 99: reference}), \
                 mock.patch.object(figures, "rmsd_between", side_effect=[0, float("nan")]):
                self.assertTrue(figures.plot_clusters(root, output))
            with output.with_suffix(".csv").open() as handle:
                plotted = list(csv.DictReader(handle))
            self.assertEqual(len(plotted), 1)
            self.assertEqual(plotted[0]["cluster_id"], "1")


if __name__ == "__main__":
    unittest.main()
