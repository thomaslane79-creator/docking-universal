#!/usr/bin/env python3
"""End-to-end regression tests for reusable protocol finalization.

These tests deliberately start after receptor preparation.  Finalization must
consume the approved retained artifacts; it must never run scientific
preparation a second time.
"""

import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from docking_universal.protocol_finalization import (
    FinalizationSettings,
    ProtocolFinalizationRequest,
    ProtocolRecordInputs,
    build_protocol_record,
    build_site_guided_report_manifest,
    publish_final_outputs,
    selected_region_records,
)
from docking_universal_bundle import create_bundle, extract_bundle, sha256
from docking_universal.services.finalization import finalize_site_guided_protocol


ROOT = Path(__file__).resolve().parents[1]
SCREEN = ROOT / "libexec" / "docking-universal-screen.py"
REPORT_SCRIPT = ROOT / "libexec" / "docking-universal-pdf-report.py"
LIGAND = ROOT / "examples" / "tutorials" / "01_bound_ligand" / "inputs" / "rilpivirine_pubchem.sdf"


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REPORT = load_script("docking_universal_pdf_report_integration", REPORT_SCRIPT)


class ProtocolFinalizationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.study = self.root / "study"
        self.preparation = self.study / "preparation" / "target_receptor_prep"
        self.receptor_dir = self.preparation / "receptor"
        self.cavity = self.preparation / "cavity"
        self.report_dir = self.study / "report"
        self.receptor_dir.mkdir(parents=True)
        self.cavity.mkdir(parents=True)
        self.report_dir.mkdir(parents=True)
        self.source = self.study / "target.pdb"
        self.receptor_pdb = self.receptor_dir / "target.pdb"
        self.receptor_pdbqt = self.receptor_dir / "target.pdbqt"
        pdb = "ATOM      1  CA  GLY A   1       0.000   0.000   0.000  1.00 10.00           C\nEND\n"
        self.source.write_text(pdb)
        self.receptor_pdb.write_text(pdb)
        self.receptor_pdbqt.write_text("ATOM      1  C   GLY A   1       0.000   0.000   0.000  0.00  C\n")
        self.boxes = [self._box(1, 1), self._box(2, 11)]
        self.regions = selected_region_records(self.boxes, [
            {"label": "P1", "path": self.boxes[0]},
            {"label": "P2", "path": self.boxes[1]},
        ])
        self.settings = FinalizationSettings(
            engine="vina", ph=7.4, conformers=3, seed_count=2,
            base_seed=41001, exhaustiveness=16, num_modes=15, energy_range=8,
        )
        self.protocol = self._protocol(self.regions)

    def tearDown(self):
        self.temporary.cleanup()

    def _box(self, number, center):
        path = self.cavity / f"target_pocket{number}.conf"
        path.write_text(
            f"center_x = {center}\ncenter_y = 2\ncenter_z = 3\n"
            "size_x = 20\nsize_y = 22\nsize_z = 24\n"
        )
        return path

    def _protocol(self, regions):
        return build_protocol_record(ProtocolRecordInputs(
            protocol_type="site-guided-exploratory",
            target="target",
            site_anchor="target_pocket1",
            evidence_basis="fpocket cavity analysis and user-reviewed docking boxes",
            created_utc="2026-09-12T12:00:00+00:00",
            engine="vina",
            software={"docking_universal": "0.7.0", "python": "3.9.23"},
            region_definition="fpocket",
            fpocket_selection="reviewed",
            pocket_evidence={"mode": "off", "status": "not_requested"},
            selected_residues=[],
            engine_selection={"selected_engine": "vina", "reason": "user selected"},
            parameters=self.settings.protocol_parameters(),
            receptor_pdbqt=self.receptor_pdbqt,
            receptor_pdb=self.receptor_pdb,
            regions=regions,
            selectable_boxes=[
                {"box_label": "P1", "box_name": self.boxes[0].name, "box": str(self.boxes[0])},
                {"box_label": "P2", "box_name": self.boxes[1].name, "box": str(self.boxes[1])},
            ],
            docking_box=regions[0]["geometry"],
            receptor_preparation={"user_approved_component_removal": False},
            receptor_preparation_summary="Strict Meeko receptor preparation succeeded",
            cavity_score_threshold_used=0.1,
            pocket_review_scene=None,
            bundle_file_name="target.duprotocol",
        ))

    def _manifest(self):
        return build_site_guided_report_manifest(
            self.protocol,
            self.source,
            "0.7.0",
            {
                "docking_universal": "0.7.0", "python": "3.9.23",
                "meeko": "0.7.1", "pdbfixer": "1.11", "fpocket": "4.2",
                "rdkit": "2023.09.6", "molscrub": "0.2.2",
                "openbabel": "3.1.1", "plip": "2.4.0",
                "engine_version": "recorded when screening runs",
            },
        )

    def _write_cavity_diagnostics(self):
        (self.cavity / "pocket_selection_diagnostics.tsv").write_text(
            "rank_order\tpocket_file\tdecision\tscore\n"
            "1\tpocket1_atm.pdb\tselected\t0.8\n"
            "2\tpocket2_atm.pdb\tselected\t0.7\n"
        )
        (self.cavity / "pocket_diagnostics.tsv").write_text(
            "pocket_file\talpha_sphere_count\tretained_atom_count\n"
            "pocket1_atm.pdb\t20\t12\n"
            "pocket2_atm.pdb\t18\t10\n"
        )

    def _write_real_report(self):
        self._write_cavity_diagnostics()
        (self.report_dir / "study_summary.json").write_text(
            json.dumps(self._manifest(), indent=2) + "\n"
        )
        output = self.report_dir / "target_site-guided-report.pdf"
        # Uncompressed page streams make the content assertion below independent
        # of optional PDF-reading packages while still using the real renderer.
        import reportlab.rl_config
        old_compression = reportlab.rl_config.pageCompression
        reportlab.rl_config.pageCompression = 0
        try:
            with patch.object(sys, "argv", [str(REPORT_SCRIPT), str(self.study), "--out", str(output)]):
                with redirect_stdout(io.StringIO()):
                    REPORT.main()
        finally:
            reportlab.rl_config.pageCompression = old_compression
        return output

    @staticmethod
    def _normalized_pdf_strings(path):
        data = path.read_bytes().decode("latin-1", errors="ignore")
        strings = re.findall(r"\(((?:\\.|[^\\)])*)\)\s*Tj", data)
        text = " ".join(strings)
        text = text.replace("\\(", "(").replace("\\)", ")").replace("\\n", " ")
        return " ".join(text.split())

    def test_complete_record_matches_the_pre_extraction_cli_contract(self):
        expected = {
            "schema_name": "docking-universal-protocol", "schema_version": 1,
            "schema_status": "stable_v1", "protocol_type": "site-guided-exploratory",
            "target": "target", "site_anchor": "target_pocket1",
            "evidence_basis": "fpocket cavity analysis and user-reviewed docking boxes",
            "screening_authority": "user-confirmed-exploratory-use",
            "created_utc": "2026-09-12T12:00:00+00:00", "control_status": "not_performed",
            "unknown_docking_allowed": False, "exploratory_screening_allowed": True,
            "engine": "vina", "software": {"docking_universal": "0.7.0", "python": "3.9.23"},
            "region_definition": "fpocket", "fpocket_selection": "reviewed",
            "pdb_pocket_evidence": {"mode": "off", "status": "not_requested"},
            "selected_residues": [],
            "engine_selection": {"selected_engine": "vina", "reason": "user selected"},
            "parameters": self.settings.protocol_parameters(),
            "locked_inputs": {
                "receptor": str(self.receptor_pdbqt), "receptor_sha256": sha256(self.receptor_pdbqt),
                "receptor_pdb": str(self.receptor_pdb), "box": self.regions[0]["box"],
                "box_sha256": sha256(self.boxes[0]), "boxes": self.regions,
            },
            "docking_regions": self.regions,
            "selectable_docking_boxes": [
                {"box_label": "P1", "box_name": self.boxes[0].name, "box": str(self.boxes[0])},
                {"box_label": "P2", "box_name": self.boxes[1].name, "box": str(self.boxes[1])},
            ],
            "docking_box": self.regions[0]["geometry"],
            "receptor_preparation": {"user_approved_component_removal": False},
            "receptor_preparation_summary": "Strict Meeko receptor preparation succeeded",
            "cavity_score_threshold_used": 0.1, "pocket_review_scene": None,
            "bundle_file_name": "target.duprotocol",
            "scientific_scope": {
                "purpose": "reusable exploratory site definition",
                "does_not_establish": [
                    "pose-recovery validation", "binding affinity accuracy", "biological activity",
                ],
            },
        }
        self.assertEqual(self.protocol, expected)

    def test_mmcif_protocol_is_written_before_report_generation(self):
        source_dir = self.preparation / "source"
        source_dir.mkdir()
        (source_dir / "structure.cif").write_text("data_TEST\n")
        (source_dir / "structure-input.json").write_text(json.dumps({
            "source_format": "mmcif",
            "assemblies": [{"id": "1", "oligomeric_details": "dimeric"}],
            "deposited_metadata": {},
        }))
        request = ProtocolFinalizationRequest(
            study_id="test", target="target", preparation_root=self.preparation,
            source_structure=self.source, receptor_pdb=self.receptor_pdb,
            receptor_pdbqt=self.receptor_pdbqt, regions=tuple(self.regions),
            settings=self.settings, approval_id="approved", evidence_revision=1,
            output_directory=self.study, exploratory_use_approved=True,
        )

        def run(command):
            if "docking-universal-pdf-report.py" in command[1]:
                protocol_path = self.study / "target_site-guided-exploratory_vina_protocol.json"
                retained = json.loads(protocol_path.read_text())
                self.assertEqual(retained["coordinate_source"]["evidence"]["assemblies"][0]["id"], "1")
                Path(command[command.index("--out") + 1]).write_bytes(b"%PDF-1.4\n%%EOF\n")

        def bundle_writer(_protocol, _root, output):
            output.write_bytes(b"bundle")
            return output

        with patch("docking_universal.services.finalization.build_site_guided_protocol", return_value=self.protocol):
            outputs = finalize_site_guided_protocol(
                object(), request, libexec=ROOT / "libexec",
                command_runner=run, bundle_writer=bundle_writer,
            )
        self.assertTrue(outputs.report.is_file())

    def test_finalization_uses_retained_preparation_without_running_it_again(self):
        report = self.report_dir / "report.pdf"
        report.write_bytes(b"%PDF-1.4\n%%EOF\n")
        protocol_path = self.study / "target_protocol.json"
        # Publication is deliberately process-free: no preparation executable,
        # scientific engine, or report process may be launched at this boundary.
        with patch.object(subprocess, "run", side_effect=AssertionError("unexpected process")):
            outputs = publish_final_outputs(
                protocol_path, self.protocol, report, self.study / "target.duprotocol",
                self.study, create_bundle,
            )
        self.assertEqual(sha256(self.receptor_pdbqt), self.protocol["locked_inputs"]["receptor_sha256"])
        self.assertTrue(outputs.bundle.is_file())

    def test_missing_report_stops_before_bundle_publication(self):
        bundle_writer_calls = []

        def bundle_writer(*args):
            bundle_writer_calls.append(args)
            return self.study / "unexpected.duprotocol"

        with self.assertRaisesRegex(FileNotFoundError, "report was not created"):
            publish_final_outputs(
                self.study / "target_protocol.json", self.protocol,
                self.report_dir / "missing.pdf", self.study / "target.duprotocol",
                self.study, bundle_writer,
            )
        self.assertEqual(bundle_writer_calls, [])
        self.assertEqual(list(self.study.glob("*.duprotocol")), [])

    def test_real_report_and_bundle_are_valid_final_artifacts(self):
        report = self._write_real_report()
        outputs = publish_final_outputs(
            self.study / "target_protocol.json", self.protocol, report,
            self.study / "target.duprotocol", self.study, create_bundle,
        )
        pdf = outputs.report.read_bytes()
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", pdf[-1024:])
        extracted = extract_bundle(outputs.bundle)
        self.assertEqual(json.loads(extracted.read_text())["schema_status"], "stable_v1")
        with zipfile.ZipFile(outputs.bundle) as archive:
            names = set(archive.namelist())
        self.assertIn("bundle_manifest.json", names)
        self.assertTrue(any(name.endswith("protocol.json") for name in names))

    def test_bundle_retains_both_receptor_state_sensitivity_variants(self):
        hie = self.receptor_dir / "target-HIE.pdbqt"
        hid = self.receptor_dir / "target-HID.pdbqt"
        hie.write_text("RECEPTOR HIE\n")
        hid.write_text("RECEPTOR HID\n")
        protocol = json.loads(json.dumps(self.protocol))
        protocol["receptor_state_sensitivity"] = {
            "status": "prepared_for_box_review",
            "affected_boxes": ["P1"],
            "variants": {
                "HIE": {
                    "receptor_pdbqt": str(hie),
                    "receptor_pdbqt_sha256": sha256(hie),
                },
                "HID": {
                    "receptor_pdbqt": str(hid),
                    "receptor_pdbqt_sha256": sha256(hid),
                },
            },
        }
        report = self.report_dir / "sensitivity.pdf"
        report.write_bytes(b"%PDF-1.4\n%%EOF\n")

        outputs = publish_final_outputs(
            self.study / "sensitivity_protocol.json", protocol, report,
            self.study / "sensitivity.duprotocol", self.study, create_bundle,
        )
        extracted = extract_bundle(outputs.bundle)
        bundled = json.loads(extracted.read_text())
        variants = bundled["receptor_state_sensitivity"]["variants"]
        for state_name in ("HIE", "HID"):
            relative = variants[state_name]["receptor_pdbqt"]
            retained = extracted.parent / relative
            self.assertTrue(retained.is_file())
            self.assertEqual(sha256(retained), variants[state_name]["receptor_pdbqt_sha256"])

    def test_generated_bundle_passes_the_real_screening_checker(self):
        report = self.report_dir / "report.pdf"
        report.write_bytes(b"%PDF-1.4\n%%EOF\n")
        outputs = publish_final_outputs(
            self.study / "target_protocol.json", self.protocol, report,
            self.study / "target.duprotocol", self.study, create_bundle,
        )
        completed = subprocess.run([
            sys.executable, str(SCREEN), "--protocol", str(outputs.bundle),
            "--ligand", str(LIGAND), "--out", str(self.root / "screen"),
            "--check-only", "--non-interactive", "--accept-exploratory-protocol",
        ], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Input check: PASS", completed.stdout)
        self.assertIn("Docking sites: 2", completed.stdout)

    def test_multisite_bundle_round_trip_preserves_order_geometry_and_hashes(self):
        report = self.report_dir / "report.pdf"
        report.write_bytes(b"%PDF-1.4\n%%EOF\n")
        outputs = publish_final_outputs(
            self.study / "target_protocol.json", self.protocol, report,
            self.study / "target.duprotocol", self.study, create_bundle,
        )
        extracted = extract_bundle(outputs.bundle)
        record = json.loads(extracted.read_text())
        regions = record["locked_inputs"]["boxes"]
        self.assertEqual([item["box_label"] for item in regions], ["P1", "P2"])
        self.assertEqual([item["geometry"]["center_x"] for item in regions], ["1", "11"])
        for region in regions:
            retained = extracted.parent / region["box"]
            self.assertTrue(retained.is_file())
            self.assertEqual(sha256(retained), region["box_sha256"])

    def test_failed_bundle_is_retryable_and_never_mutates_approved_inputs(self):
        report = self.report_dir / "report.pdf"
        report.write_bytes(b"%PDF-1.4\n%%EOF\n")
        before = {path: sha256(path) for path in [self.receptor_pdb, self.receptor_pdbqt, *self.boxes]}
        calls = []

        def fail_bundle(*args):
            calls.append(args)
            raise RuntimeError("simulated bundle interruption")

        with self.assertRaisesRegex(RuntimeError, "simulated bundle interruption"):
            publish_final_outputs(
                self.study / "target_protocol.json", self.protocol, report,
                self.study / "target.duprotocol", self.study, fail_bundle,
            )
        self.assertTrue(report.is_file())
        self.assertEqual(len(calls), 1)
        self.assertEqual(before, {path: sha256(path) for path in before})

        outputs = publish_final_outputs(
            self.study / "target_protocol.json", self.protocol, report,
            self.study / "target.duprotocol", self.study, create_bundle,
        )
        self.assertTrue(outputs.bundle.is_file())
        self.assertEqual(before, {path: sha256(path) for path in before})
        self.assertEqual(
            [path.resolve() for path in sorted(self.study.glob("*.duprotocol"))],
            [outputs.bundle.resolve()],
        )

    def test_stale_or_changed_approved_artifacts_block_finalization(self):
        request = ProtocolFinalizationRequest(
            "study", "target", self.preparation, self.source,
            self.receptor_pdb, self.receptor_pdbqt, tuple(self.regions),
            self.settings, "approval-1", 4, self.study, True,
            source_structure_sha256=sha256(self.source),
            receptor_pdb_sha256=sha256(self.receptor_pdb),
            receptor_pdbqt_sha256=sha256(self.receptor_pdbqt),
        )
        request.validate()
        self.receptor_pdbqt.write_text(self.receptor_pdbqt.read_text() + "REMARK changed\n")
        with self.assertRaisesRegex(ValueError, "changed or is missing"):
            request.validate()

    def test_report_contract_preserves_headings_warnings_and_figure_inventory(self):
        report = self._write_real_report()
        text = self._normalized_pdf_strings(report)
        for expected in (
            "Reusable Exploratory Protocol Report",
            "Configured docking protocol",
            "Exploratory pocket configuration",
            "not evaluated by bound-ligand control",
            "Reproducibility, software, and references",
        ):
            self.assertIn(expected, text)
        self.assertNotIn("Ligand docking results", text)
        figure_manifest = json.loads((self.report_dir / "report_figure_manifest.json").read_text())
        self.assertEqual(figure_manifest["schema_name"], "docking-universal-report-figures")
        figure_paths = [Path(value) for value in figure_manifest["outputs"]]
        self.assertEqual(
            [path.name for path in figure_paths],
            [
                "cavity_panel_A_selection.png",
                "cavity_panel_B_structure.png",
                "cavity_selected_box.png",
                "cavity_panels_AB.png",
            ],
        )
        self.assertTrue(all(path.is_file() and path.stat().st_size > 0 for path in figure_paths))
        summary = json.loads((self.report_dir / "study_summary.json").read_text())
        self.assertEqual(summary["selected_docking_regions"], self.regions)
        self.assertEqual(summary["configured_docking_parameters"], self.settings.protocol_parameters())


if __name__ == "__main__":
    unittest.main()
