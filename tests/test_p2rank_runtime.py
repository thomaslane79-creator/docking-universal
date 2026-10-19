import os
import struct
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docking_universal.p2rank_runtime import java_invocation, run_p2rank, prefix_java, write_argument_file


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

    def test_prefix_java_never_falls_back_to_an_unrelated_path_runtime(self):
        with patch.dict(os.environ, {"PATH": str(self.root)}):
            with self.assertRaises(FileNotFoundError):
                prefix_java(self.root)
        expected = self.root / "Library/lib/jvm/bin/java.exe"
        expected.parent.mkdir(parents=True)
        expected.touch()
        self.assertEqual(prefix_java(self.root), expected.resolve())

    def test_unicode_transport_is_lossless_and_uses_original_classpath(self):
        root = self.root.parent / "ascii-p2rank"
        (root / "bin/lib").mkdir(parents=True)
        (root / "bin/p2rank.jar").touch()
        bridge = root / "docking-universal-launcher"
        bridge.mkdir(); (bridge / "NativeArguments.class").touch()
        java = root / "java.exe"; java.touch()
        arguments = ["predict", "-f", str(self.root / "蛋白 Ω & input.pdb"), "-o", "a b"]
        command, environment = java_invocation(root, java, arguments, windows=True)
        self.assertEqual(command[-2], "NativeArguments")
        self.assertEqual(command[3].split(os.pathsep)[1:], [str(root / "bin/p2rank.jar"), str(root / "bin/lib/*")])
        with Path(command[-1]).open("rb") as stream:
            self.assertEqual(stream.read(4), b"DUJ1")
            count, = struct.unpack(">I", stream.read(4))
            values = []
            for _ in range(count):
                size, = struct.unpack(">I", stream.read(4))
                values.append(stream.read(size).decode("utf-8"))
            self.assertEqual(values, arguments)
            self.assertEqual(stream.read(), b"")
        self.assertEqual(environment["INSTALL_DIR"], str(root))
        with self.assertRaises(ValueError):
            write_argument_file(bridge / "arguments", ["x"] * 129)
