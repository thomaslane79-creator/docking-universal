import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rdkit import Chem

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("conformer_ab", ROOT / "validation/conformer_ab.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)
redock_spec = importlib.util.spec_from_file_location("redock_prepared_ab", ROOT / "validation/redock_prepared_ab.py")
redock = importlib.util.module_from_spec(redock_spec)
with mock.patch.dict(sys.modules, {"conformer_ab": benchmark}):
    redock_spec.loader.exec_module(redock)


class ConformerABTests(unittest.TestCase):
    def test_redock_coordinate_frame_guard_rejects_translation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original, prepared = root / "raw.pdb", root / "prepared.pdb"
            line = "ATOM      1  CA  PRO A   1      30.491 -29.103 -16.397  1.00 10.00           C\n"
            original.write_text(line)
            prepared.write_text(line)
            result = redock.verify_coordinate_frame(original, prepared)
            self.assertEqual(result["anchor_count"], 1)
            self.assertEqual(result["maximum_displacement_angstrom"], 0)
            prepared.write_text(line[:30] + "  34.220   7.935  12.337" + line[54:])
            with self.assertRaisesRegex(ValueError, "coordinate frame"):
                redock.verify_coordinate_frame(original, prepared)
            prepared.write_text("END\n")
            with self.assertRaisesRegex(ValueError, "anchors"):
                redock.verify_coordinate_frame(original, prepared)

    def test_relative_executable_is_resolved_before_subprocess_chdir(self):
        relative = os.path.relpath(sys.executable)
        with mock.patch.object(benchmark.shutil, "which", return_value=relative):
            self.assertEqual(benchmark.executable(relative), str(Path(sys.executable).resolve()))

    def test_retained_cross_comparison_aligns_copies_not_docking_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, pool = benchmark.independent_pool(self.source(root), 3, 42)
            water = [Chem.Mol(molecule) for molecule in pool]
            for molecule in water:
                for index in range(molecule.GetNumAtoms()):
                    position = molecule.GetConformer().GetAtomPosition(index)
                    molecule.GetConformer().SetAtomPosition(index, (position.x + 50, position.y, position.z))
            for name, molecules in (("vacuum_pruned", pool), ("water_pruned", water)):
                (root / name).mkdir()
                benchmark.sdf(root / name / "retained.sdf", molecules)
            original = (root / "water_pruned/retained.sdf").read_bytes()
            inventory, comparisons = redock.conformations(root, root)
            cross = comparisons["vacuum_rows_water_columns_rmsd_angstrom"]
            self.assertEqual(len(cross), 3)
            for index in range(3):
                self.assertLess(cross[index][index], 0.001)
            self.assertEqual((root / "water_pruned/retained.sdf").read_bytes(), original)
            self.assertGreater(inventory["water_pruned"][0].GetConformer().GetAtomPosition(0).x, 40)

    def test_retained_comparison_rejects_unreadable_ensemble(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "vacuum_pruned").mkdir()
            (root / "vacuum_pruned/retained.sdf").write_text("invalid SDF\n")
            with self.assertRaises((ValueError, OSError)):
                redock.conformations(root, root)

    def source(self, root, smiles="CCCCCC"):
        path = root / "ligand.sdf"
        benchmark.sdf(path, [Chem.MolFromSmiles(smiles)])
        return path

    def test_pool_is_deterministic_independent_and_unpruned(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.source(Path(directory))
            _, first = benchmark.independent_pool(source, 4, 42)
            _, second = benchmark.independent_pool(source, 4, 42)
            self.assertEqual(len(first), 4)
            self.assertEqual(Chem.MolToMolBlock(first[0]), Chem.MolToMolBlock(second[0]))
            # Input geometry cannot affect generation.
            translated = Chem.Mol(first[0])
            for index in range(translated.GetNumAtoms()):
                position = translated.GetConformer().GetAtomPosition(index)
                translated.GetConformer().SetAtomPosition(index, (position.x + 100, position.y, position.z))
            benchmark.sdf(source, [translated])
            _, third = benchmark.independent_pool(source, 4, 42)
            self.assertEqual(Chem.MolToMolBlock(first[0]), Chem.MolToMolBlock(third[0]))

    def test_aligned_pruning_keeps_lowest_energy_duplicate_without_moving_it(self):
        with tempfile.TemporaryDirectory() as directory:
            _, pool = benchmark.independent_pool(self.source(Path(directory)), 3, 42)
            first = pool[0]
            shifted = Chem.Mol(first)
            for index in range(shifted.GetNumAtoms()):
                position = shifted.GetConformer().GetAtomPosition(index)
                shifted.GetConformer().SetAtomPosition(index, (position.x + 50, position.y, position.z))
            original = Chem.MolToMolBlock(shifted)
            records = [{"input_id": 1, "molecule": first, "energy_kcal_mol": 10},
                       {"input_id": 2, "molecule": shifted, "energy_kcal_mol": 5}]
            kept = benchmark.prune(records, 0.75, 3)
            self.assertEqual([row["input_id"] for row in kept], [2])
            self.assertEqual(records[0]["disposition"], "near_duplicate")
            self.assertEqual(Chem.MolToMolBlock(shifted), original)

    def test_xtb_checks_mapping_convergence_and_energy_units(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, pool = benchmark.independent_pool(self.source(root), 1, 42)
            xyz = root / "xtbopt.xyz"
            Chem.MolToXYZFile(pool[0], str(xyz))
            log = "GEOMETRY OPTIMIZATION CONVERGED\n | TOTAL ENERGY -1.25 Eh |"
            _, energy = benchmark.parse_xtb(pool[0], xyz, log)
            self.assertAlmostEqual(energy, -1.25 * benchmark.HARTREE_TO_KCAL)
            with self.assertRaisesRegex(ValueError, "converged"):
                benchmark.parse_xtb(pool[0], xyz, "TOTAL ENERGY -1.25 Eh")
            with self.assertRaisesRegex(ValueError, "energy"):
                benchmark.parse_xtb(pool[0], xyz, "GEOMETRY OPTIMIZATION CONVERGED")
            xyz.write_text(xyz.read_text().replace("C ", "N ", 1))
            with self.assertRaisesRegex(ValueError, "order/elements"):
                benchmark.parse_xtb(pool[0], xyz, log)

    def test_xtb_water_is_explicit_and_single_threaded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, pool = benchmark.independent_pool(self.source(root), 1, 42)
            with mock.patch.object(benchmark, "run", return_value="log") as runner, \
                    mock.patch.object(benchmark, "parse_xtb", return_value=(pool[0], 1)):
                benchmark.minimize_xtb(pool[0], root, "/fake/xtb", True, 600)
                command = runner.call_args.args[0]
                self.assertEqual(command[-2:], ["--alpb", "water"])
                self.assertEqual(command[command.index("--parallel") + 1], "1")
                benchmark.minimize_xtb(pool[0], root, "/fake/xtb", False, 600)
                self.assertNotIn("--alpb", runner.call_args.args[0])

    def test_paired_run_retains_audit_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source(root)
            output = root / "benchmark"
            args = ["--ligand", str(source), "--out", str(output), "--attempts", "3", "--keep", "2", "--xtb", sys.executable]
            # Test orchestration, not a scientific substitute for real xTB.
            with mock.patch.object(benchmark, "run", return_value="mock version"), \
                    mock.patch.object(benchmark, "minimize_xtb", side_effect=lambda molecule, *args: benchmark.minimize_mmff(molecule)):
                self.assertEqual(benchmark.main(args), 0)
            result = json.loads((output / "summary.json").read_text())
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["embedded_count"], 3)
            self.assertEqual(set(result["arms"]), {"vacuum_pruned", "water_pruned"})
            self.assertTrue((output / "comparison.csv").is_file())
            self.assertTrue((output / "shared_initial_pool.sdf").is_file())
            with self.assertRaises(SystemExit):
                benchmark.main(args)

    def test_failed_solvent_arm_is_not_replaced_with_vacuum(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = ["--ligand", str(self.source(root)), "--out", str(root / "benchmark"),
                    "--attempts", "1", "--keep", "1", "--xtb", sys.executable]
            with mock.patch.object(benchmark, "run", return_value="mock version"), \
                    mock.patch.object(benchmark, "minimize_xtb", side_effect=ValueError("not converged")):
                with self.assertRaisesRegex(RuntimeError, "No converged"):
                    benchmark.main(args)
            result = json.loads((root / "benchmark/summary.json").read_text())
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["arms"]["water_pruned"]["converged_count"], 0)

    def test_partial_redocking_inputs_rejected(self):
        with self.assertRaises(SystemExit):
            benchmark.main(["--ligand", "unused.sdf", "--out", "unused", "--box", "unused.conf"])

    def test_redocking_uses_shared_budget_and_top_score_not_best_rmsd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source(root)
            receptor = root / "receptor.pdbqt"
            receptor.write_text("fixture")
            crystal = root / "crystal.pdb"
            crystal.write_text("fixture")
            box = root / "box.conf"
            box.write_text("center_x=0\ncenter_y=0\ncenter_z=0\nsize_x=20\nsize_y=20\nsize_z=20\n")
            output = root / "benchmark"
            arguments = ["--ligand", str(source), "--out", str(output), "--attempts", "4", "--keep", "3",
                         "--rmsd", "0.01", "--xtb", sys.executable, "--vina", sys.executable,
                         "--meeko", sys.executable, "--mk-export", sys.executable,
                         "--receptor-pdbqt", str(receptor), "--receptor-pdb", str(crystal),
                         "--crystal-ligand", str(crystal), "--box", str(box), "--dock-seeds", "10", "11"]
            commands = []

            def fake_run(command, folder, label, timeout):
                commands.append((label, command))
                if label == "compare":
                    comparison = folder / "comparison"
                    comparison.mkdir()
                    # Better experimental RMSD must NOT break score ties or win
                    # over the stronger-scoring pose in the primary metric.
                    (comparison / "pose_comparison.csv").write_text(
                        "model,affinity_kcal_per_mol,crystal_rmsd_angstrom,within_threshold\n"
                        "1,-9,4.0,no\n2,-8,1.0,yes\n")
                return "mock version"

            def fake_xtb(molecule, folder, *args):
                if folder.name != "input_001":
                    raise ValueError("fixture exclusion")
                return benchmark.minimize_mmff(molecule)

            with mock.patch.object(benchmark, "run", side_effect=fake_run), \
                    mock.patch.object(benchmark, "minimize_xtb", side_effect=fake_xtb):
                benchmark.main(arguments)
            result = json.loads((output / "summary.json").read_text())
            self.assertEqual(result["docked_conformers_per_arm"], 1)
            self.assertGreater(result["arms"]["vacuum_pruned"]["retained_count"], 1)
            for arm in result["arms"].values():
                self.assertEqual(len(arm["docked_input_ids"]), 1)
                self.assertEqual([item["seed"] for item in arm["redocking"]], [10, 11])
                self.assertFalse(arm["redocking"][0]["top_score_recovered_2A"])
                self.assertTrue(arm["redocking"][0]["any_pose_recovered_2A"])
            docking = [command for label, command in commands if label == "vina"]
            self.assertEqual(len(docking), 4)
            for command in docking:
                self.assertEqual(command[command.index("--cpu") + 1], "1")
                self.assertEqual(command[command.index("--exhaustiveness") + 1], "8")
                self.assertEqual(command[command.index("--receptor") + 1], str(receptor.resolve()))

    def test_xtb_rejects_inverted_stereocenter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, pool = benchmark.independent_pool(self.source(root, "F[C@](Cl)(Br)I"), 1, 42)
            inverted = Chem.Mol(pool[0])
            for index in range(inverted.GetNumAtoms()):
                position = inverted.GetConformer().GetAtomPosition(index)
                inverted.GetConformer().SetAtomPosition(index, (-position.x, position.y, position.z))
            xyz = root / "xtbopt.xyz"
            Chem.MolToXYZFile(inverted, str(xyz))
            with self.assertRaisesRegex(ValueError, "stereocenter"):
                benchmark.parse_xtb(pool[0], xyz, "GEOMETRY OPTIMIZATION CONVERGED\nTOTAL ENERGY -1.0 Eh")

    def test_external_command_failure_retains_log_and_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = [sys.executable, "-c", "print('failure fixture'); raise SystemExit(3)"]
            with self.assertRaisesRegex(RuntimeError, "exit 3"):
                benchmark.run(command, root, "probe", 10)
            self.assertEqual(json.loads((root / "probe.command.json").read_text()), command)
            self.assertIn("failure fixture", (root / "probe.log").read_text())

    def test_larger_flexible_indinavir_mmff_smoke(self):
        source = ROOT / "examples/tutorials/02_ligand_free_cavity/inputs/indinavir_pubchem_5362440.sdf"
        _, pool = benchmark.independent_pool(source, 4, 42)
        self.assertGreaterEqual(pool[0].GetNumHeavyAtoms(), 40)
        records = []
        for index, molecule in enumerate(pool):
            optimized, energy = benchmark.minimize_mmff(molecule)
            records.append({"input_id": index, "molecule": optimized, "energy_kcal_mol": energy})
        retained = benchmark.prune(records, 0.75, 3)
        self.assertGreaterEqual(len(retained), 1)
        for index, first in enumerate(retained):
            for second in retained[index + 1:]:
                self.assertGreaterEqual(benchmark.aligned_rmsd(first["molecule"], second["molecule"]), 0.75)


if __name__ == "__main__":
    unittest.main()
