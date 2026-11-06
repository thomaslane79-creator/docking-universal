import os
import struct
import hashlib
import subprocess
import tarfile
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docking_universal.p2rank_runtime import java_invocation, run_p2rank, prefix_java, write_argument_file


@unittest.skipIf(os.name == 'nt', 'Bash installer and Unix worker discovery')
class P2RankInstallPathTests(unittest.TestCase):
    def test_upstream_underscore_archive_installs_at_the_runtime_hyphen_path(self):
        """Execute the actual installer section with a local archive/checksum."""
        repo = Path(__file__).resolve().parents[1]
        script = (repo / 'install.sh').read_text()
        section = script[script.index('p2rank_parent='):script.index(
            "printf '\\nInstalling checksum-verified P2Rank 2.6-alpha")]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upstream = root / 'upstream/p2rank_2.5.1'
            (upstream / 'bin').mkdir(parents=True)
            (upstream / 'prank').write_text('#!/bin/sh\nexit 0\n')
            (upstream / 'bin/p2rank.jar').write_bytes(b'fixture jar')
            archive = root / 'release.tar.gz'
            with tarfile.open(archive, 'w:gz') as handle:
                handle.add(upstream, arcname='p2rank_2.5.1')
            section = section.replace(
                'd243f2d9036ac053fefb9407b5fe1c85f4fe077c519fd975ac585e995feab274',
                hashlib.sha256(archive.read_bytes()).hexdigest())
            header = '''set -eu
scientific_prefix="$FIXTURE_PREFIX"
run_with_retry() { shift; "$@"; }
curl() {
  while [ "$#" -gt 0 ]; do
    if [ "$1" = --output ]; then cp "$FIXTURE_ARCHIVE" "$2"; return; fi
    shift
  done
  return 1
}
'''
            environment = {**os.environ, 'FIXTURE_PREFIX': str(root / 'scientific prefix'),
                           'FIXTURE_ARCHIVE': str(archive)}
            subprocess.run(['bash', '-c', header + section], env=environment, check=True, capture_output=True)
            target = root / 'scientific prefix/share/docking-universal/p2rank-2.5.1'
            self.assertTrue(os.access(target / 'prank', os.X_OK))
            self.assertEqual((target / 'bin/p2rank.jar').read_bytes(), b'fixture jar')
            self.assertFalse(target.with_name('p2rank_2.5.1').exists())
            archive.unlink()  # A repeat install must reuse the complete asset.
            subprocess.run(['bash', '-c', header + section], env=environment, check=True, capture_output=True)

    def test_worker_finds_scientific_p2rank_when_parent_conda_label_is_gui(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = root / 'scientific prefix'
            (prefix / 'bin').mkdir(parents=True)
            python = prefix / 'bin/python'
            python.touch()
            launcher = prefix / 'share/docking-universal/p2rank-2.5.1/prank'
            launcher.parent.mkdir(parents=True)
            launcher.write_text('#!/bin/sh\nprintf "P2Rank 2.5.1\\n"\n')
            launcher.chmod(0o755)
            environment = {**os.environ, 'CONDA_PREFIX': str(root / 'gui prefix'),
                'DOCKING_UNIVERSAL_PYTHON': str(python), 'DOCKING_UNIVERSAL_POCKET_ENGINE': 'p2rank',
                'DOCKING_UNIVERSAL_PREP_BACKEND': 'meeko', 'DOCKING_UNIVERSAL_PREP_RECEPTOR': str(launcher)}
            environment.pop('DOCKING_UNIVERSAL_P2RANK', None)
            environment.pop('DOCKING_UNIVERSAL_REFERENCE_SITE_ONLY', None)
            environment.pop('DOCKING_UNIVERSAL_PARAMETERIZATION_ONLY', None)
            script = 'source "$1"; load_prepare_runtime_defaults; resolve_prepare_runtime_tools; printf "%s\\n" "$P2RANK_BIN"'
            result = subprocess.run(['bash', '-eu', '-c', script, 'fixture',
                str(repo / 'libexec/docking-universal-prepare.d/runtime.sh')],
                env=environment, check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout.strip(), str(launcher))
            environment['DOCKING_UNIVERSAL_P2RANK'] = str(root / 'explicit-missing-launcher')
            rejected = subprocess.run(['bash', '-eu', '-c', script, 'fixture',
                str(repo / 'libexec/docking-universal-prepare.d/runtime.sh')],
                env=environment, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn('P2Rank launcher not found', rejected.stderr)


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
