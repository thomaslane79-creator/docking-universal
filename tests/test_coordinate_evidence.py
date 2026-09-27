import tempfile
import unittest
from pathlib import Path

from docking_universal.services.coordinate_evidence import (
    evidence_lines, evidence_summary, read_coordinate_evidence,
)
from tests.test_structure_input import MMCIF


class CoordinateEvidenceTests(unittest.TestCase):
    def test_readable_summary_preserves_assembly_ligand_and_occupancy(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "entry.cif"
            source.write_text(MMCIF)
            record = read_coordinate_evidence(source)
            self.assertIsNotNone(record)
            summary = evidence_summary(record)
            self.assertEqual(summary["assemblies"][0]["oligomeric_details"], "monomeric")
            self.assertEqual(summary["ligands"][0]["occupancy_range"], [1.0, 1.0])
            text = "\n".join(evidence_lines(record))
            self.assertIn("monomeric", text)
            self.assertIn("LIG B:401 (occupancy 1)", text)
            self.assertIn("no assembly is selected automatically", text)
            details = "\n".join(evidence_lines(record, detailed=True))
            self.assertIn("B-factor 20", details)
            self.assertIn("not a binding-affinity measurement", details)


if __name__ == "__main__":
    unittest.main()
