import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "docking_universal_process", ROOT / "libexec" / "docking_universal_process.py"
)
PROCESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROCESS)


class ProcessRunnerTests(unittest.TestCase):
    def test_run_checked_normalizes_paths_and_forwards_context(self):
        with patch.object(PROCESS.subprocess, "run") as called:
            PROCESS.run_checked([Path("tool"), Path("input file")], cwd=Path("work"), env={"A": "B"})
        called.assert_called_once_with(
            ["tool", "input file"], cwd=Path("work"), env={"A": "B"}, check=True
        )


if __name__ == "__main__":
    unittest.main()
