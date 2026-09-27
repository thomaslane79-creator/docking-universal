import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path

from docking_universal.application import StudyController
from docking_universal.host import CommandDispatcher
from docking_universal.models import ArtifactRecord
from docking_universal.state import JsonStudyStore
from docking_universal.viewer.messages import Command
from docking_universal_bundle import create_bundle


class ScreeningWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = JsonStudyStore(self.root / "runs")
        self.controller = StudyController(self.store)
        self.controller.create_study("screen", "Screen study")
        receptor = self.root / "receptor.pdbqt"
        receptor_pdb = self.root / "receptor.pdb"
        box = self.root / "box.conf"
        receptor.write_text("RECEPTOR\n")
        receptor_pdb.write_text("ATOM\n")
        box.write_text(
            "center_x = 1\ncenter_y = 2\ncenter_z = 3\n"
            "size_x = 20\nsize_y = 20\nsize_z = 20\n"
        )
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        protocol = self.root / "protocol.json"
        protocol.write_text(json.dumps({
            "schema_name": "docking-universal-protocol", "schema_version": 1,
            "protocol_type": "site-guided-exploratory",
            "screening_authority": "user-confirmed-exploratory-use",
            "exploratory_screening_allowed": True,
            "target": "Target", "engine": "vina",
            "parameters": {
                "conformers_per_state": 2, "seeds": [101, 102],
                "macrocycle_treatment": "flexible_meeko",
            },
            "locked_inputs": {
                "receptor": str(receptor), "receptor_sha256": digest(receptor),
                "receptor_pdb": str(receptor_pdb),
                "box": str(box), "box_sha256": digest(box),
                "boxes": [{"site_number": 1, "box": str(box), "box_sha256": digest(box)}],
            },
            "receptor_preparation": {},
        }))
        self.bundle = create_bundle(protocol, self.root, self.root / "target.duprotocol")
        state = self.store.load("screen")
        state.artifacts.append(ArtifactRecord(
            "bundle", "protocol_bundle", str(self.bundle), digest(self.bundle),
        ))
        self.store.save(state)
        self.ligands = self.root / "ligands.sdf"
        self.ligands.write_text("ligand\n$$$$\n")
        executable_dir = self.root / "bin"
        executable_dir.mkdir()
        self.preparation = executable_dir / "docking-universal-prepare"
        self.preparation.write_text("#!/bin/sh\nexit 0\n")
        self.preparation.chmod(0o755)
        screen = executable_dir / "docking-universal-run.py"
        screen.write_text(
            "#!/usr/bin/env python3\n"
            "import json,sys\nfrom pathlib import Path\n"
            "args=sys.argv[1:]; out=Path(args[args.index('--out')+1]); "
            "(out/'report').mkdir(parents=True); (out/'compounds/ligand').mkdir(parents=True); "
            "(out/'study_manifest.json').write_text('{}\\n'); "
            "(out/'report/study_summary.json').write_text('{}\\n'); "
            "(out/'report/screen.pdf').write_bytes(b'%PDF-1.4\\n%%EOF\\n'); "
            "(out/'compounds/ligand/screen_manifest.json').write_text('{}\\n'); "
            "(out/'compounds/ligand/all_scores.csv').write_text('affinity\\n-7.0\\n')\n"
        )
        screen.chmod(0o755)
        pose_worker = executable_dir / "docking-universal-pose-interactions.py"
        pose_worker.write_text(
            "#!/usr/bin/env python3\n"
            "import argparse,json\nfrom pathlib import Path\n"
            "p=argparse.ArgumentParser(); p.add_argument('--cache',type=Path); p.add_argument('--pose-id',type=int); "
            "p.add_argument('--cluster-id',type=int); p.add_argument('--score'); p.add_argument('--renderer-policy'); a=p.parse_args(); "
            "(a.cache/'plip').mkdir(parents=True,exist_ok=True); "
            "(a.cache/'plip/report.xml').write_text('<report />\\n'); "
            "(a.cache/'interaction_diagram.png').write_bytes(b'png'); "
            "(a.cache/'interaction_manifest.json').write_text(json.dumps({'pose_id':a.pose_id,'cluster_id':a.cluster_id,'renderer_policy':a.renderer_policy,'network_used':False}))\n"
        )
        pose_worker.chmod(0o755)
        self.dispatcher = CommandDispatcher(self.controller, "session", self.preparation)

    def tearDown(self):
        self.dispatcher.shutdown()
        self.temporary.cleanup()

    def wait_for(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.store.load("screen")
            if predicate(state):
                return state
            time.sleep(0.02)
        self.fail("Timed out waiting for screening workflow")

    def test_plan_and_tracked_screening_register_outputs_in_the_same_study(self):
        plan_response = self.dispatcher.dispatch(Command(
            "screen", "session", "plan", "screening_plan",
            {"ligand_source": str(self.ligands)},
        ))
        self.assertEqual(plan_response.status, "applied")
        plan = plan_response.result["plan"]
        self.assertEqual(plan["total_docking_jobs"], 4)
        self.assertTrue(plan["exploratory_authorization_required"])

        unauthorized = self.dispatcher.dispatch(Command(
            "screen", "session", "unauthorized", "start_screening",
            {"ligand_source": str(self.ligands), "output_directory": str(self.root / "screen-out")},
            plan_response.revision,
        ))
        self.assertEqual(unauthorized.status, "rejected")

        started = self.dispatcher.dispatch(Command(
            "screen", "session", "screen-once", "start_screening",
            {
                "ligand_source": str(self.ligands),
                "output_directory": str(self.root / "screen-out"),
                "analysis": "representatives", "representatives": 3,
                "cluster_rmsd": 2.0, "exploratory_use_approved": True,
            },
            plan_response.revision,
        ))
        self.assertEqual(started.status, "applied")
        state = self.wait_for(lambda item: any(
            artifact.kind == "screening_report" for artifact in item.artifacts
        ))
        kinds = {artifact.kind for artifact in state.artifacts}
        self.assertTrue({
            "protocol_bundle", "screening_study_manifest", "screening_report",
            "screening_summary", "screening_compound_manifest", "screening_scores",
        } <= kinds)
        self.assertEqual(state.workflow_data["latest_screening_status"], "completed")
        self.assertEqual(state.jobs[-1].stage, "screening")
        self.assertEqual(state.jobs[-1].status.value, "completed")

    def test_exact_pose_request_runs_serialized_worker_and_registers_result(self):
        from rdkit import Chem
        from rdkit.Chem import AllChem

        analysis = self.root / "screen-out/compounds/ligand/pose_analysis"
        analysis.mkdir(parents=True)
        molecule = Chem.AddHs(Chem.MolFromSmiles("CCO"))
        AllChem.EmbedMolecule(molecule, randomSeed=5)
        writer = Chem.SDWriter(str(analysis / "all_poses.sdf"))
        writer.write(molecule)
        writer.close()
        (analysis / "receptor.pdb").write_text(
            "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C\nEND\n"
        )
        (analysis / "pose_inventory.csv").write_text(
            "pose_id,cluster_id,selected_cluster,seed,conformer,model,energy_kcal_per_mol,source\n"
            "1,3,no,101,state_1,2,-7.4,retained.pdbqt\n"
        )
        revision = self.store.load("screen").revision
        response = self.dispatcher.dispatch(Command(
            "screen", "session", "pose-1", "start_pose_interaction",
            {"analysis_root": str(analysis), "pose_id": 1}, revision,
        ))
        self.assertEqual(response.status, "applied")
        state = self.wait_for(lambda item: any(
            artifact.kind == "pose_interaction_diagram" for artifact in item.artifacts
        ))
        artifact = next(item for item in state.artifacts if item.kind == "pose_interaction_diagram")
        self.assertEqual(artifact.metadata["pose_id"], 1)
        self.assertEqual(artifact.metadata["renderer_policy"], "approved-poseedit-local-v1")
        self.assertEqual(state.jobs[-1].stage, "pose_interaction")


if __name__ == "__main__":
    unittest.main()
