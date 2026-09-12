import tempfile
import unittest
from pathlib import Path

from docking_universal.protocol_finalization import (
    FinalizationSettings,
    ProtocolRecordInputs,
    ProtocolFinalizationRequest,
    build_protocol_record,
    build_site_guided_report_manifest,
    publish_final_outputs,
    selected_region_records,
)


class ProtocolFinalizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.preparation = self.root / "target_receptor_prep"
        receptor = self.preparation / "receptor"
        receptor.mkdir(parents=True)
        self.source = self.root / "target.pdb"
        self.receptor_pdb = receptor / "target.pdb"
        self.receptor_pdbqt = receptor / "target.pdbqt"
        for path in (self.source, self.receptor_pdb, self.receptor_pdbqt):
            path.write_text("ATOM\n")

    def tearDown(self):
        self.temporary.cleanup()

    def box(self, number):
        path = self.preparation / "cavity" / f"target_pocket{number}.conf"
        path.parent.mkdir(exist_ok=True)
        path.write_text(
            f"center_x = {number}\ncenter_y = 2\ncenter_z = 3\n"
            "size_x = 20\nsize_y = 22\nsize_z = 24\n"
        )
        return path

    def test_region_records_preserve_cli_schema_order_and_labels(self):
        boxes = [self.box(2), self.box(1)]
        records = selected_region_records(boxes, [
            {"label": "P1", "path": boxes[1]}, {"label": "P2", "path": boxes[0]},
        ])
        self.assertEqual([item["box_label"] for item in records], ["P2", "P1"])
        self.assertEqual([item["site_number"] for item in records], [1, 2])
        self.assertEqual(records[0]["geometry"]["center_x"], "2")
        self.assertEqual(records[0]["definition_origin"], "user-selected labeled candidate")

    def test_settings_match_stable_protocol_parameter_shape(self):
        values = FinalizationSettings(
            engine="vina", ph=6.8, conformers=4, seed_count=3, base_seed=90,
            exhaustiveness=32, num_modes=12, energy_range=6,
        ).protocol_parameters()
        self.assertEqual(values["seeds"], [90, 91, 92])
        self.assertEqual(values["macrocycle_treatment"], "flexible_meeko")
        self.assertEqual(values["conformers_per_state"], 4)

    def test_request_rejects_changed_approved_box(self):
        box = self.box(1)
        regions = selected_region_records([box], [{"label": "P1", "path": box}])
        request = ProtocolFinalizationRequest(
            "study", "target", self.preparation, self.source,
            self.receptor_pdb, self.receptor_pdbqt, tuple(regions),
            FinalizationSettings(), "approval-1", 4, self.root / "final", True,
        )
        request.validate()
        box.write_text(box.read_text() + "# changed\n")
        with self.assertRaisesRegex(ValueError, "changed or is missing"):
            request.validate()

    def test_request_requires_separate_exploratory_use_approval(self):
        box = self.box(1)
        regions = selected_region_records([box], [{"label": "P1", "path": box}])
        request = ProtocolFinalizationRequest(
            "study", "target", self.preparation, self.source,
            self.receptor_pdb, self.receptor_pdbqt, tuple(regions),
            FinalizationSettings(), "approval-1", 4, self.root / "final", False,
        )
        with self.assertRaisesRegex(ValueError, "explicit approval"):
            request.validate()

    def test_output_publication_requires_and_hashes_all_three_artifacts(self):
        protocol_path = self.root / "final" / "protocol.json"
        report = self.root / "final" / "report.pdf"
        bundle = self.root / "final" / "protocol.duprotocol"
        report.parent.mkdir()
        report.write_bytes(b"PDF")

        def bundle_writer(written_protocol, _root, destination):
            self.assertEqual(written_protocol, protocol_path)
            destination.write_bytes(b"BUNDLE")
            return destination

        outputs = publish_final_outputs(
            protocol_path, {"schema_name": "docking-universal-protocol"},
            report, bundle, self.root, bundle_writer,
        )
        self.assertTrue(outputs.protocol.is_file())
        self.assertEqual(set(outputs.sha256), {"protocol", "report", "bundle"})

    def test_shared_builders_preserve_protocol_and_report_contracts(self):
        box = self.box(1)
        regions = selected_region_records([box], [{"label": "P1", "path": box}])
        protocol = build_protocol_record(ProtocolRecordInputs(
            protocol_type="site-guided-exploratory", target="target",
            site_anchor="target_pocket1", evidence_basis="reviewed P1",
            created_utc="2026-09-12T12:00:00+00:00", engine="vina",
            software={"docking_universal": "test"}, region_definition="fpocket",
            fpocket_selection="reviewed", pocket_evidence={"status": "completed"},
            selected_residues=[], engine_selection={"selected_engine": "vina"},
            parameters=FinalizationSettings().protocol_parameters(),
            receptor_pdbqt=self.receptor_pdbqt, receptor_pdb=self.receptor_pdb,
            regions=regions, selectable_boxes=[{"label": "P1"}],
            docking_box=regions[0]["geometry"], receptor_preparation={},
            receptor_preparation_summary="Strict Meeko succeeded",
            cavity_score_threshold_used=0.1, pocket_review_scene="review.pml",
            bundle_file_name="target.duprotocol",
        ))
        self.assertEqual(protocol["schema_status"], "stable_v1")
        self.assertEqual(protocol["locked_inputs"]["boxes"], regions)
        self.assertFalse(protocol["unknown_docking_allowed"])
        manifest = build_site_guided_report_manifest(
            protocol, self.source, "1.0", {"engine_version": "recorded when screening runs"},
        )
        self.assertEqual(manifest["selected_docking_regions"], regions)
        self.assertEqual(manifest["configured_docking_parameters"], protocol["parameters"])
        self.assertEqual(manifest["protocol_validation_status"],
                         "Site-guided exploratory protocol; not evaluated by bound-ligand control")


if __name__ == "__main__":
    unittest.main()
