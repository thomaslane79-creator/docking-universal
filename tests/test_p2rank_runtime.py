import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docking_universal.p2rank_runtime import java_invocation, run_p2rank


class P2RankRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve() / "P2Rank Ω with spaces"
        (self.root / "bin/lib").mkdir(parents=True)
        (self.root / "bin/p2rank.jar").write_bytes(b"fixture only")
        self.java = self.root / "java.exe"
        self.java.write_bytes(b"fixture only")

    def tearDown(self):
        self.temporary.cleanup()

    def test_matches_upstream_application_without_batch_argument_expansion(self):
        receptor = str(self.root / "receptor & input.pdb")
        command, environment = java_invocation(self.root, self.java, ["predict", "-f", receptor], environment={"KEEP": "yes"})
        self.assertEqual(command[1:3], ("-Xmx2048m", "-cp"))
        self.assertEqual(command[-1], receptor)
        self.assertEqual(command[3], str(self.root / "bin/p2rank.jar") + os.pathsep + str(self.root / "bin/lib/*"))
        self.assertEqual(environment, {"KEEP": "yes", "INSTALL_DIR": str(self.root)})
        with patch("docking_universal.p2rank_runtime.subprocess.run") as run:
            run_p2rank(self.root, self.java, ["predict", "-f", receptor])
            self.assertFalse(run.call_args.kwargs["shell"])
            self.assertNotIn("cmd.exe", run.call_args.args[0])
            self.assertNotIn("prank.bat", run.call_args.args[0])

    def test_missing_explicit_runtime_is_not_replaced(self):
        with self.assertRaisesRegex(FileNotFoundError, "Java"):
            java_invocation(self.root, self.root / "missing-java.exe", ["-v"])
        (self.root / "bin/p2rank.jar").unlink()
        with self.assertRaisesRegex(FileNotFoundError, "incomplete"):
            java_invocation(self.root, self.java, ["-v"])
