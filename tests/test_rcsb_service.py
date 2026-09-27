import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from docking_universal.services.rcsb import canonical_pdb_id, download_pdb_entry


class RcsbServiceTests(unittest.TestCase):
    def test_identifier_is_canonicalized_and_validated(self):
        self.assertEqual(canonical_pdb_id(" 2r8n "), "2R8N")
        for invalid in ("", "R8N", "ABCD", "2R8N5", "2R-N"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                canonical_pdb_id(invalid)

    def test_download_retains_coordinates_and_provenance(self):
        response = BytesIO(b"data_2R8N\n_atom_site.id 1\n")
        response.__enter__ = lambda value: value
        response.__exit__ = lambda *_args: None
        with tempfile.TemporaryDirectory() as temporary, \
                patch("docking_universal.services.rcsb.urlopen", return_value=response):
            result = download_pdb_entry("2r8n", Path(temporary))
            provenance = json.loads((Path(temporary) / "2R8N_provenance.json").read_text())
            self.assertEqual(result.name, "2R8N.cif")
            self.assertIn("_atom_site", result.read_text())
            self.assertEqual(provenance["pdb_id"], "2R8N")
            self.assertEqual(provenance["source"], "RCSB Protein Data Bank")
            self.assertEqual(provenance["coordinate_format"], "mmcif")

    def test_noncoordinate_response_is_rejected_without_partial_file(self):
        response = BytesIO(b"not coordinates")
        response.__enter__ = lambda value: value
        response.__exit__ = lambda *_args: None
        with tempfile.TemporaryDirectory() as temporary, \
                patch("docking_universal.services.rcsb.urlopen", return_value=response):
            with self.assertRaises(OSError):
                download_pdb_entry("2R8N", Path(temporary))
            self.assertFalse((Path(temporary) / "2R8N.cif").exists())


if __name__ == "__main__":
    unittest.main()
