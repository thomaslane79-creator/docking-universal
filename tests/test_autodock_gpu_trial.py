"""Pilot safety, map bounds and inventory parsing; no real docking."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "validation/autodock_gpu_trial.py"
spec = importlib.util.spec_from_file_location("adgpu_trial_test", SCRIPT)
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class TrialTests(unittest.TestCase):
    def test_grid_covers_requested_region_and_preserves_center(self):
        geom = {"center_x": 28.930867, "center_y": -12.031978, "center_z": 0.036178,
                "size_x": 26, "size_y": 26.739, "size_z": 26}
        text, info = trial.grid_description(geom, ["C", "OA"], ["C", "HD"])
        self.assertEqual(info["grid_intervals"], [70, 72, 70])
        self.assertIn("gridcenter 28.930867 -12.031978 0.036178", text)
        for actual, wanted in zip(info["actual_size"], info["requested_size"]):
            self.assertGreaterEqual(actual, wanted)

    def test_xml_missing_run_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "out.xml"
            path.write_text('<autodock_gpu><run_requested>2</run_requested><runs>'
                            '<run id="1"><free_NRG_binding>-5</free_NRG_binding></run>'
                            '</runs></autodock_gpu>')
            with self.assertRaisesRegex(ValueError, "Missing"):
                trial.parse_xml(path, 2)

    def test_xml_duplicate_and_nonfinite_rejected(self):
        for energy, second in (("nan", "2"), ("-5", "1")):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "out.xml"
                path.write_text('<autodock_gpu><run_requested>2</run_requested><runs>'
                                f'<run id="1"><free_NRG_binding>{energy}</free_NRG_binding></run>'
                                f'<run id="{second}"><free_NRG_binding>-4</free_NRG_binding></run>'
                                '</runs></autodock_gpu>')
                with self.assertRaises(ValueError):
                    trial.parse_xml(path, 2)

    def test_guard_blocks_active_job_but_allows_waiting_decision(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root / "study/application_state.json"
            state.parent.mkdir()
            with patch.object(trial, "STATE_ROOT", root):
                state.write_text('{"jobs":[{"status":"waiting_for_decision"}]}')
                trial.check_idle()
                state.write_text('{"jobs":[{"status":"running"}]}')
                with self.assertRaises(RuntimeError):
                    trial.check_idle()

    def test_empty_state_guard_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(trial, "STATE_ROOT", Path(folder)):
            with self.assertRaises(RuntimeError):
                trial.check_idle()


if __name__ == "__main__":
    unittest.main()
