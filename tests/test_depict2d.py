#!/usr/bin/env python3
"""Regression tests for deterministic 2D depiction backend selection."""

import builtins
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "docking_universal_depict2d", ROOT / "libexec" / "docking-universal-depict2d.py"
)
DEPICT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEPICT)


class DepictionBackendTests(unittest.TestCase):
    def run_main(self, source, import_rdkit):
        original_import = builtins.__import__

        def controlled_import(name, *args, **kwargs):
            if name == "rdkit":
                if not import_rdkit:
                    raise ImportError("RDKit intentionally unavailable")
                return object()
            return original_import(name, *args, **kwargs)

        output = source.parent / "output"
        argv = ["docking-universal-depict2d.py", str(source), "--out-dir", str(output)]
        with (
            patch.object(sys, "argv", argv),
            patch("builtins.__import__", side_effect=controlled_import),
            patch.object(DEPICT, "draw_with_rdkit") as rdkit_draw,
            patch.object(DEPICT, "draw_with_obabel") as obabel_draw,
        ):
            DEPICT.main()
        return rdkit_draw, obabel_draw

    def test_rdkit_is_preferred_when_importable(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "ligand.sdf"
            source.write_text("ligand\n$$$$\n")
            rdkit_draw, obabel_draw = self.run_main(source, import_rdkit=True)
        rdkit_draw.assert_called_once()
        obabel_draw.assert_not_called()

    def test_open_babel_is_used_only_when_rdkit_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "ligand.sdf"
            source.write_text("ligand\n$$$$\n")
            rdkit_draw, obabel_draw = self.run_main(source, import_rdkit=False)
        rdkit_draw.assert_not_called()
        obabel_draw.assert_called_once()


if __name__ == "__main__":
    unittest.main()
