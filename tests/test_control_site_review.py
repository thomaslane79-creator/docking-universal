"""Site-first controls must not skip lookup, review, or site-specific authority."""
import json
import os
from pathlib import Path
import tempfile
import time
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.error import URLError

from docking_universal.orchestration import ProtocolWorkflowRunner
from docking_universal.protocol_finalization import FinalizationSettings, request_from_study, sha256
from docking_universal.services.control_review import (
    NoControlSiteSelected, read_reviewed_control_inputs, reviewed_control_inputs,
)
from docking_universal.services.finalization import build_site_guided_protocol


class ControlSiteReviewTests(unittest.TestCase):
    def setUp(self):
        from tests.test_protocol_workflow import ProtocolWorkflowTests
        self.fixture = ProtocolWorkflowTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root, self.store, self.controller = self.fixture.root, self.fixture.store, self.fixture.controller
        self.fixture.input.write_text(self.fixture.input.read_text() +
            "HETATM    2  C1  LIG A 101       1.000   2.000   3.000  1.00 10.00           C\n")
        self.executable = self.fixture.executable()
        self.executable.write_text("\n".join(line for line in self.executable.read_text().splitlines()
                                                if "pdb_ligand_site_evidence.json" not in line) + "\n")
        (self.executable.parent / "docking-universal-run.py").write_text(
            "import sys,json,zipfile\nfrom pathlib import Path\n"
            "a=sys.argv[1:]; o=Path(a[a.index('--out')+1]); o.mkdir(parents=True)\n"
            "r=json.loads(Path(a[a.index('--reviewed-control-inputs')+1]).read_text()); assets=r['assets']\n"
            "p={'schema_name':'docking-universal-protocol','protocol_type':'control-validated',"
            "'unknown_docking_allowed':True,'control_status':'approved','engine':r['engine'],"
            "'locked_inputs':{'receptor_sha256':assets['receptor_pdbqt']['sha256'],'box_sha256':assets['box']['sha256']}}\n"
            "with zipfile.ZipFile(o/'control.duprotocol','w') as z:\n"
            " z.writestr('bundle_manifest.json',json.dumps({'protocol':'protocol.json'})); z.writestr('protocol.json',json.dumps(p))\n"
            "(o/'report').mkdir(); (o/'report/control.pdf').write_bytes(b'fixture')\n"
            "(o/'study_manifest.json').write_text(json.dumps({'fixture':True}))\n"
        )
        self.runner = ProtocolWorkflowRunner(self.controller, self.executable)
        self.addCleanup(self.runner.shutdown)
        self.payload = dict(input_structure=str(self.fixture.input), output_directory=str(self.root / "study"),
            ligand_resname="LIG", ligand_chain_id="A", ligand_residue_number="101",
            engine="vina", control_tier="quick", geostd_library=str(self.root))

    def wait(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = self.store.load("workflow")
            if predicate(state):
                return state
            time.sleep(.02)
        self.fail(str(self.store.load("workflow").workflow_data))

    def fake_lookup(self, source, boxes, output):
        from docking_universal_pocket_evidence import group_ligand_sites
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        ligand = output / "remote.pdb"
        ligand.write_text("".join(
            f"HETATM{i:5d}  C{i:<2} DRG Z 201    {40 + i:8.3f}{2:8.3f}{3:8.3f}  1.00 20.00           C\n"
            for i in range(1, 7)))
        evidence = {"status": "completed", "pocket_engine": "fpocket", "candidate_entries": ["9XYZ"],
                    "evidence": [{"entry": "9XYZ", "source_ligand_id": "9XYZ/DRG/Z/201", "ligand": "DRG",
                        "ligand_chain": "Z", "ligand_residue": "201", "evidence_class": "exact_sequence_match",
                        "aligned_ligand_pdb": ligand.name, "matched_cavity": None}], "skipped": []}
        evidence["ligand_site_groups"] = group_ligand_sites(evidence, output)
        (output / "pdb_ligand_site_evidence.json").write_text(json.dumps(evidence))
        return evidence

    def prepare(self, *, online=True, lookup=None):
        payload = dict(self.payload, pdb_pocket_evidence="related-structures" if online else "off")
        with patch("docking_universal_pocket_evidence.collect_pocket_evidence", side_effect=lookup or self.fake_lookup) as collect:
            response = self.runner.start_control_validation("workflow", payload, request_id="prepare",
                                                           expected_revision=self.store.load("workflow").revision)
            state = self.wait(lambda value: bool(value.pending_decisions))
            self.assertEqual(response["stage"], "preparation_and_pocket_detection")
        return state, collect

    def approve(self, labels):
        state = self.store.load("workflow")
        self.controller.resolve_decision("workflow", state.pending_decisions[0].id, labels,
            actor="test-user", rationale="Synthetic site-review regression", request_id="approve", expected_revision=state.revision)
        return self.store.load("workflow")

    def test_bound_control_looks_up_other_sites_and_pauses_before_search(self):
        state, lookup = self.prepare()
        self.assertEqual(state.workflow_data["study_setup"]["pathway"], "control")
        self.assertEqual(state.workflow_data["study_setup"]["site_mode"], "ligand")
        self.assertFalse(state.workflow_data["study_setup"]["predict_pockets_with_ligand"])
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(Path(lookup.call_args.args[0]).resolve(), self.fixture.input.resolve())
        self.assertEqual({row["label"] for row in state.workflow_data["pocket_candidates"]}, {"P1", "L1"})
        self.assertFalse(state.selected_pocket_ids)
        self.assertFalse(any(job.stage == "control_validation" for job in state.jobs))
        self.assertFalse((self.root / "study/control").exists())

    def test_offline_control_does_not_query_and_still_reviews_sites(self):
        state, lookup = self.prepare(online=False)
        lookup.assert_not_called()
        self.assertEqual(state.workflow_data["study_setup"]["pdb_pocket_evidence"], "off")
        self.assertTrue(state.pending_decisions)

    def test_control_can_predict_additional_pockets_even_with_lookup_off(self):
        self.payload["predict_pockets_with_ligand"] = True
        self.payload["pocket_engine"] = "p2rank"
        state, lookup = self.prepare(online=False)
        lookup.assert_not_called()
        self.assertTrue(state.workflow_data["study_setup"]["predict_pockets_with_ligand"])
        self.assertEqual(state.workflow_data["study_setup"]["pathway"], "control")
        self.assertEqual(state.workflow_data["study_setup"]["site_mode"], "ligand")
        self.assertEqual(state.workflow_data["study_setup"]["pocket_engine"], "p2rank")
        # Native detector fixture supplies P1; B1 remains an unscored exact-input site.
        self.assertIn("B1", [row["id"] for row in state.workflow_data["pocket_candidates"]])
        self.assertFalse(any(job.stage == "control_validation" for job in state.jobs))

    def test_downloaded_inputs_in_existing_study_folder_are_allowed(self):
        inputs = self.root / 'study/inputs'
        inputs.mkdir(parents=True)
        sentinel = inputs / 'downloaded.cif'
        sentinel.write_text('retained original input')
        self.prepare(online=False)
        self.assertEqual(sentinel.read_text(), 'retained original input')

    def test_existing_preparation_is_not_overwritten(self):
        existing = self.root / 'study/preparation'
        existing.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'already contains'):
            self.runner.start_control_validation('workflow', self.payload,
                request_id='prepare', expected_revision=self.store.load('workflow').revision)

    def test_failed_lookup_preserves_preparation_and_reports_unavailable(self):
        state, _ = self.prepare(lookup=URLError("connection unavailable"))
        self.assertEqual(state.workflow_data["pdb_pocket_evidence"]["status"], "unavailable")
        self.assertTrue(Path(state.workflow_data["preparation_root"]).is_dir())
        self.assertFalse(state.workflow_data.get("latest_control_status"))

    def test_control_cannot_start_before_site_approval(self):
        state, _ = self.prepare()
        from docking_universal.application import ActiveStageError
        with self.assertRaises((ValueError, ActiveStageError)):
            self.runner.start_control_validation("workflow", {}, request_id="control", expected_revision=state.revision)

    def test_multiple_selected_sites_do_not_share_control_authority(self):
        self.prepare()
        state = self.approve(["P1", "L1"])
        preview = reviewed_control_inputs(state)
        self.assertEqual(preview["tested_box_label"], "P1")
        self.assertEqual(preview["untested_box_labels"], ["L1"])
        prep_log = Path(state.workflow_data["preparation_root"]) / "run.log"
        before = sha256(prep_log)
        self.runner.start_control_validation("workflow", {}, request_id="control", expected_revision=state.revision)
        state = self.wait(lambda value: bool(value.workflow_data.get("latest_control_status")))
        self.assertEqual(state.workflow_data["latest_control_status"], "approved")
        self.assertFalse(any(item.kind == "protocol_bundle" for item in state.artifacts))
        self.assertTrue(any(item.kind == "control_protocol_bundle" for item in state.artifacts))
        self.assertFalse(state.workflow_data["control_site_review"]["all_selected_sites_validated"])
        self.assertEqual(state.scientific_authority.value, 'exploratory_no_control')
        self.assertEqual(before, sha256(prep_log))
        request = request_from_study(state, FinalizationSettings(), self.root / "final", exploratory_use_approved=True)
        record = build_site_guided_protocol(state, request, libexec=self.executable.parent)
        self.assertEqual(len(record["docking_regions"]), 2)
        self.assertEqual(record["protocol_type"], "site-guided-exploratory")
        self.assertFalse(record["unknown_docking_allowed"])
        self.assertEqual(record["related_site_control"]["untested_box_labels"], ["L1"])

    def test_one_selected_tested_site_can_receive_its_own_control_bundle(self):
        self.prepare()
        state = self.approve(["P1"])
        self.runner.start_control_validation("workflow", {}, request_id="control", expected_revision=state.revision)
        state = self.wait(lambda value: bool(value.workflow_data.get("latest_control_status")))
        self.assertTrue(any(item.kind == "protocol_bundle" for item in state.artifacts))
        self.assertTrue(state.workflow_data["control_site_review"]["all_selected_sites_validated"])
        self.assertEqual(state.scientific_authority.value, 'control_approved')

    def test_remote_site_only_cannot_test_the_other_experimental_ligand(self):
        self.prepare()
        state = self.approve(["L1"])
        with self.assertRaises(NoControlSiteSelected):
            reviewed_control_inputs(state)
        request = request_from_study(state, FinalizationSettings(), self.root / "final", exploratory_use_approved=True)
        self.assertEqual(request.regions[0]["box_label"], "L1")

    def test_selected_box_changes_are_rejected_before_control(self):
        self.prepare()
        state = self.approve(["P1", "L1"])
        contract = reviewed_control_inputs(state)
        Path(contract["assets"]["box"]["path"]).write_text("changed")
        with self.assertRaises(ValueError):
            reviewed_control_inputs(state)

    def test_native_boundary_rechecks_contract_and_retained_files(self):
        self.prepare()
        contract = reviewed_control_inputs(self.approve(["P1", "L1"]))
        path = self.root / "contract.json"
        path.write_text(json.dumps(contract))
        expected = sha256(path)
        read_reviewed_control_inputs(path, expected_sha256=expected)
        path.write_text(path.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "record changed"):
            read_reviewed_control_inputs(path, expected_sha256=expected)
        path.write_text(json.dumps(contract))
        Path(contract["assets"]["receptor_pdbqt"]["path"]).write_text("changed")
        with self.assertRaisesRegex(ValueError, "receptor_pdbqt"):
            read_reviewed_control_inputs(path)

    def test_native_control_uses_reviewed_inputs_without_repreparation_or_search(self):
        from rdkit import Chem
        from rdkit.Chem import AllChem
        molecule = Chem.AddHs(Chem.MolFromSmiles("C1CCCCCCCCCCC1"))
        AllChem.EmbedMolecule(molecule, randomSeed=73)
        molecule = Chem.RemoveHs(molecule)
        for index, atom in enumerate(molecule.GetAtoms(), 1):
            info = Chem.AtomPDBResidueInfo()
            info.SetName(f" C{index:<2}")
            info.SetResidueName("LIG")
            info.SetChainId("A")
            info.SetResidueNumber(101)
            info.SetIsHeteroAtom(True)
            atom.SetMonomerInfo(info)
        self.fixture.input.write_text("ATOM      1  CA  GLY A   1      -6.000   0.000   0.000  1.00 10.00           C\n"
                                      + Chem.MolToPDBBlock(molecule))
        template = self.root / "template.sdf"
        with Chem.SDWriter(str(template)) as writer:
            writer.write(molecule)
        self.prepare(online=False)
        contract = reviewed_control_inputs(self.approve(["P1"]))
        record = self.root / "reviewed.json"
        record.write_text(json.dumps(contract))
        native = Path(__file__).resolve().parents[1] / "libexec/docking-universal-control"
        spy_output = self.root / "native-calibration-args.json"
        spy = self.root / "spy-cli"
        spy.write_text(f"#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\n"
                       "assert sys.argv[1]=='calibrate', 'Preparation or another scientific stage was unexpectedly invoked'\n"
                       f"Path({str(spy_output)!r}).write_text(json.dumps(sys.argv[1:]))\n")
        spy.chmod(0o755)
        prep_log = Path(contract['preparation_root']) / 'run.log'
        before = sha256(prep_log)
        output = self.root / "native-control"
        process = subprocess.run(["bash", str(native), "--complex", str(self.fixture.input),
            "--ligand-id", "LIG:A:101", "--ligand-template", str(template),
            "--reviewed-inputs", str(record), "--reviewed-inputs-sha256", sha256(record),
            "--no-visuals", "--non-interactive", "--out", str(output)],
            env=dict(os.environ, DOCKING_UNIVERSAL_CLI=str(spy), DOCKING_UNIVERSAL_PYTHON=sys.executable,
                     DOCKING_UNIVERSAL_LOG_MODE="file"),
            capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr +
                         ((output / 'run.log').read_text() if (output / 'run.log').exists() else ''))
        command = json.loads(spy_output.read_text())
        self.assertEqual(command[command.index('--receptor-pdbqt') + 1], contract['assets']['receptor_pdbqt']['path'])
        self.assertEqual(command[command.index('--box') + 1], contract['assets']['box']['path'])
        self.assertFalse(list((output / '01_preparation').glob('*_receptor_prep')))
        self.assertEqual(before, sha256(prep_log))


if __name__ == "__main__":
    unittest.main()
