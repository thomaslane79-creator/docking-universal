from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import docking_universal_ligands as ligands

HOST_PATH = type(Path())


class NativeLigandCommandTests(unittest.TestCase):
    def test_native_default_uses_installed_module_not_entrypoint_association(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.sdf"; source.touch()
            options = ligands.LigandOptions(source)
            with patch.object(ligands.os, "name", "nt"), patch.object(ligands, "Path", HOST_PATH), \
                 patch.object(ligands.importlib.util, "find_spec", return_value=object()), \
                 patch.object(ligands.shutil, "which", return_value=sys.executable), \
                 patch.object(ligands, "_executable", return_value=True):
                ligands.validate_and_resolve(options, {"PATH": "fixture"})
            self.assertEqual(options.backend, "meeko")
            self.assertEqual(options.prepare_ligand, Path(sys.executable))
            self.assertTrue(options.native_meeko_module)

    def test_explicit_meeko_executable_remains_authoritative(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.sdf"; source.touch()
            custom = Path(temporary) / "mk_prepare_ligand.py.exe"; custom.touch()
            options = ligands.LigandOptions(source, prepare_ligand=custom)
            with patch.object(ligands.os, "name", "nt"), patch.object(ligands, "Path", HOST_PATH), \
                 patch.object(ligands.shutil, "which", return_value=sys.executable), \
                 patch.object(ligands, "_executable", return_value=True):
                ligands.validate_and_resolve(options, {"PATH": "fixture"})
            self.assertEqual(options.prepare_ligand, custom)
            self.assertEqual(options.backend, "meeko")
            self.assertFalse(options.native_meeko_module)


if __name__ == "__main__":
    unittest.main()
