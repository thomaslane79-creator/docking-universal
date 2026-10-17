"""Isolated assessment policy; never launches a scientific job."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

VALIDATION = Path(__file__).resolve().parents[1] / "validation"
sys.path.insert(0, str(VALIDATION))
spec = importlib.util.spec_from_file_location("gpu_panel_test", VALIDATION / "autodock_gpu_control_panel.py")
panel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(panel)


class ControlPanelTests(unittest.TestCase):
    def test_reuse_never_accepts_failed_scientific_job(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = {"status": "failed", "error": "Native GPU job crashed"}
            panel.save(root / "summary.json", state)
            with self.assertRaisesRegex(ValueError, "Only the recorded"):
                panel.completed_parser_failure(root, [], Path("unused-engine"))
            state.update(error="Expected Apple GPU execution/completion not confirmed",
                         engine_sha256="engine", search_arms=panel.ARMS, seeds_with_repeat=panel.SEEDS,
                         processes=[{"status": "completed", "returncode": 0}, {"status": "failed", "returncode": 1}])
            panel.save(root / "summary.json", state)
            with patch.object(panel, "digest", return_value="engine"):
                with self.assertRaisesRegex(ValueError, "completed successful"):
                    panel.completed_parser_failure(root, [], Path("unused-engine"))

    def test_reuse_never_accepts_changed_engine(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            panel.save(root / "summary.json", {"status": "failed",
                "error": "Expected Apple GPU execution/completion not confirmed", "engine_sha256": "original"})
            with patch.object(panel, "digest", return_value="changed"):
                with self.assertRaisesRegex(ValueError, "provenance differs"):
                    panel.completed_parser_failure(root, [], Path("unused-engine"))

    def test_device_log_accepts_alignment_spaces_not_other_device_or_failure(self):
        self.assertTrue(panel.gpu_log_valid('OpenCL device:                          Apple M2 Max\nAll jobs ran without errors.\n'))
        self.assertFalse(panel.gpu_log_valid('OpenCL device: Other GPU\nAll jobs ran without errors.\n'))
        self.assertFalse(panel.gpu_log_valid('OpenCL device: Apple M2 Max\n'))

    def test_macrocycle_and_unknown_types_fail_before_search(self):
        for types in (["C", "CG0", "G0"], ["C", "unknown"]):
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                panel.validate_types(types)
        panel.validate_types(["C", "A", "OA", "SA", "F", "HD"])

    def test_declared_arms_differ_only_in_stopping_controls(self):
        default = panel.command("engine", "maps", "heuristic_autostop", 41001)
        fixed = panel.command("engine", "maps", "fixed_12m_no_autostop", 41001)
        for cmd in [default, fixed]:
            self.assertEqual(cmd[cmd.index("--nrun") + 1], "20")
            self.assertEqual(cmd[cmd.index("--lsit") + 1], "300")
            self.assertEqual(cmd[cmd.index("--seed") + 1], "41001")
            self.assertEqual(cmd[cmd.index("--output-cluster-poses") + 1], "0")
        self.assertEqual(default[default.index("--autostop") + 1], "1")
        self.assertEqual(fixed[fixed.index("--autostop") + 1], "0")
        self.assertIn("--nev", fixed)
        self.assertIn("--heurmax", default)
        with self.assertRaises(ValueError):
            panel.command("engine", "maps", "silent_fallback", 1)

    def test_xml_preserves_engine_order_on_rounded_energy_tie(self):
        # Run 2 wins at upstream's unrounded precision; run 1 prints the same
        # energy. Do not sort run IDs or use the crystal RMSD to break this tie.
        xml = '<autodock_gpu><run_requested>2</run_requested><runs>'
        for number in [2, 1]:
            xml += (f'<run id="{number}"><free_NRG_binding>-5.00</free_NRG_binding>'
                    '<final_intermol_NRG>-6</final_intermol_NRG><internal_ligand_NRG>99</internal_ligand_NRG>'
                    '<torsonial_free_NRG>1</torsonial_free_NRG></run>')
        xml += '</runs></autodock_gpu>'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.xml"
            path.write_text(xml)
            self.assertEqual([r["run"] for r in panel.xml_ranking(path, 2)], [2, 1])
            path.write_text(xml.replace('<free_NRG_binding>-5.00', '<free_NRG_binding>-4.00'))
            with self.assertRaisesRegex(ValueError, "formula"):
                panel.xml_ranking(path, 2)

    def test_population_search_is_not_the_binding_energy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "final_population_run1.txt").write_text(
                ' 1 | gene | 4.0 | -10.0 | -6.000 / -6.123 / -0.123 | 99.0 |\n')
            row = panel.winner_search_energies(root, 1)[1]
            self.assertEqual(row["gpu_total_search_kcal_mol"], -6.123)
            self.assertEqual(row["cpu_total_report_kcal_mol"], -6.)


if __name__ == "__main__":
    unittest.main()
