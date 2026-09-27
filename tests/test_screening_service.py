import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from docking_universal.services.screening import (
    build_receptor_region_matrix, build_screening_plan, discover_screening_artifacts,
)
from docking_universal.services.pose_interactions import (
    build_pose_interaction_plan, materialize_pose_interaction_inputs, pose_cache_directory,
    read_pose_inventory, validate_pose_interaction_outputs,
)
from docking_universal.services.interaction_projection import (
    InteractionAnchor, ProjectedAnchor, optimize_anchor_layout, project_and_optimize,
)
from docking_universal.services.residue_context import read_receptor_atoms, resolve_contact


class ScreeningServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.protocol = self.root / "protocol.json"
        self.protocol.write_text(json.dumps({
            "schema_name": "docking-universal-protocol", "schema_version": 1,
            "protocol_type": "site-guided-exploratory",
            "screening_authority": "user-confirmed-exploratory-use",
            "exploratory_screening_allowed": True,
            "target": "Target", "engine": "vina",
            "parameters": {"conformers_per_state": 3, "seeds": [11, 12]},
            "locked_inputs": {"box": "one.conf", "boxes": [
                {"box": "one.conf"}, {"box": "two.conf"},
            ]},
        }))

    def tearDown(self):
        self.temporary.cleanup()

    def test_workload_is_compounds_times_conformers_times_seeds_times_sites(self):
        ligands = self.root / "ligands.sdf"
        ligands.write_text("first\n$$$$\nsecond\n$$$$\n")
        digest = hashlib.sha256(self.protocol.read_bytes()).hexdigest()
        plan = build_screening_plan(
            self.protocol, ligands, expected_protocol_sha256=digest,
        )
        self.assertEqual(plan.compound_count, 2)
        self.assertEqual(plan.jobs_per_compound, 12)
        self.assertEqual(plan.total_docking_jobs, 24)
        self.assertTrue(plan.exploratory_authorization_required)

    def test_affected_box_adds_matched_jobs_for_the_second_receptor_state(self):
        record = json.loads(self.protocol.read_text())
        record["locked_inputs"]["boxes"] = [
            {"box": "one.conf", "box_label": "P1"},
            {"box": "two.conf", "box_label": "P2"},
        ]
        record["receptor_state_sensitivity"] = {
            "affected_boxes": ["P1"],
            "primary_review_state": "HIE",
            "variants": {
                "HIE": {"receptor_pdbqt": "HIE.pdbqt"},
                "HID": {"receptor_pdbqt": "HID.pdbqt"},
            },
        }
        self.protocol.write_text(json.dumps(record))
        ligands = self.root / "ligands.sdf"
        ligands.write_text("first\n$$$$\nsecond\n$$$$\n")

        plan = build_screening_plan(self.protocol, ligands)

        self.assertEqual(plan.baseline_docking_jobs, 24)
        self.assertEqual(plan.additional_sensitivity_jobs, 12)
        self.assertEqual(plan.total_docking_jobs, 36)
        self.assertEqual(plan.affected_docking_site_count, 1)
        self.assertEqual(plan.receptor_state_variant_count, 2)
        self.assertEqual(
            [(item["box_label"], item["receptor_state"]) for item in plan.receptor_region_tasks],
            [("P1", "HIE"), ("P1", "HID"), ("P2", "HIE")],
        )

    def test_unaffected_boxes_are_not_duplicated_in_receptor_region_matrix(self):
        record = json.loads(self.protocol.read_text())
        record["locked_inputs"]["boxes"] = [
            {"box": "one.conf", "box_label": "P1"},
            {"box": "two.conf", "box_label": "P2"},
        ]
        record["receptor_state_sensitivity"] = {
            "affected_boxes": ["P1"], "primary_review_state": "HIE",
            "variants": {
                "HIE": {"receptor_pdbqt": "HIE.pdbqt"},
                "HID": {"receptor_pdbqt": "HID.pdbqt"},
            },
        }

        matrix = build_receptor_region_matrix(record)

        self.assertEqual(sum(item["box_label"] == "P1" for item in matrix), 2)
        self.assertEqual(sum(item["box_label"] == "P2" for item in matrix), 1)
        self.assertFalse(next(item for item in matrix if item["box_label"] == "P2")["sensitivity_comparison"])

    def test_changed_protocol_and_empty_ligand_sources_are_rejected(self):
        ligands = self.root / "empty.sdf"
        ligands.write_text("")
        with self.assertRaisesRegex(ValueError, "changed after finalization"):
            build_screening_plan(
                self.protocol, ligands, expected_protocol_sha256="0" * 64,
            )
        with self.assertRaisesRegex(ValueError, "no apparent SDF"):
            build_screening_plan(self.protocol, ligands)

    def test_partial_and_complete_screening_outputs_are_discoverable(self):
        output = self.root / "screen"
        (output / "report").mkdir(parents=True)
        (output / "compounds/ligand/pose_analysis").mkdir(parents=True)
        interactions = output / "compounds/ligand/pose_analysis/cluster_001/interactions"
        interactions.mkdir(parents=True)
        (output / "study_manifest.json").write_text("{}\n")
        (output / "report/study_summary.json").write_text("{}\n")
        (output / "report/ligand_panels_AB.png").write_bytes(b"figure")
        (output / "compounds/ligand/all_scores.csv").write_text("affinity\n-7\n")
        (output / "compounds/ligand/pose_analysis/representative_browser.pse").write_bytes(b"pse")
        (interactions / "representative_plip2d.png").write_bytes(b"png")
        (interactions / "report.xml").write_text("<report />\n")
        kinds = {artifact.kind for artifact in discover_screening_artifacts(output)}
        self.assertTrue({
            "screening_study_manifest", "screening_summary", "screening_scores",
            "screening_pose_session", "screening_interaction_diagram",
            "screening_interaction_record", "screening_report_figure",
        } <= kinds)

    def test_exact_pose_inputs_are_materialized_in_a_content_checked_cache(self):
        from rdkit import Chem
        from rdkit.Chem import AllChem

        analysis = self.root / "analysis"
        analysis.mkdir()
        molecule = Chem.AddHs(Chem.MolFromSmiles("CCO"))
        AllChem.EmbedMolecule(molecule, randomSeed=7)
        writer = Chem.SDWriter(str(analysis / "all_poses.sdf"))
        writer.write(molecule)
        writer.close()
        (analysis / "receptor.pdb").write_text(
            "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C\nEND\n"
        )
        (analysis / "pose_inventory.csv").write_text(
            "pose_id,cluster_id,selected_cluster,seed,conformer,model,energy_kcal_per_mol,source\n"
            "1,4,no,101,ligand_state_1,2,-7.3,retained.pdbqt\n"
        )
        records = read_pose_inventory(analysis)
        self.assertEqual(records[0].cluster_id, 4)
        record, cache = materialize_pose_interaction_inputs(analysis, 1)
        self.assertEqual(record.energy_kcal_per_mol, -7.3)
        self.assertEqual(cache, pose_cache_directory(analysis, 1))
        self.assertTrue((cache / "pose.sdf").is_file())
        self.assertIn("HETATM", (cache / "complex.pdb").read_text())
        before = (cache / "input_manifest.json").read_bytes()
        materialize_pose_interaction_inputs(analysis, 1)
        self.assertEqual((cache / "input_manifest.json").read_bytes(), before)

    def test_pose_interaction_plan_requires_approved_local_provenance(self):
        from rdkit import Chem
        from rdkit.Chem import AllChem

        analysis = self.root / "analysis-plan"
        analysis.mkdir()
        molecule = Chem.AddHs(Chem.MolFromSmiles("CCO"))
        AllChem.EmbedMolecule(molecule, randomSeed=9)
        writer = Chem.SDWriter(str(analysis / "all_poses.sdf"))
        writer.write(molecule)
        writer.close()
        (analysis / "receptor.pdb").write_text(
            "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C\nEND\n"
        )
        (analysis / "pose_inventory.csv").write_text(
            "pose_id,cluster_id,selected_cluster,seed,conformer,model,energy_kcal_per_mol,source\n"
            "1,4,no,101,state_1,2,-7.3,retained.pdbqt\n"
        )
        plan = build_pose_interaction_plan(analysis, 1, worker_command=("worker",))
        self.assertFalse(plan.cached)
        self.assertIn("approved-poseedit-local-v1", plan.command)
        (plan.cache / "plip").mkdir()
        plan.diagram.write_bytes(b"png")
        plan.evidence.write_text("<report />\n")
        plan.manifest.write_text(json.dumps({
            "pose_id": 1, "cluster_id": 4,
            "renderer_policy": "approved-poseedit-local-v1", "network_used": False,
        }))
        self.assertEqual(validate_pose_interaction_outputs(plan)["pose_id"], 1)
        plan.manifest.write_text(json.dumps({
            "pose_id": 1, "cluster_id": 4,
            "renderer_policy": "approved-poseedit-local-v1", "network_used": True,
        }))
        with self.assertRaisesRegex(ValueError, "network_used"):
            validate_pose_interaction_outputs(plan)

    def test_local_projection_preserves_pose_direction_and_spreads_contacts(self):
        ligand = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
        anchors = [
            InteractionAnchor("A", "Asp42", (2.0, 0.0, 0.2)),
            InteractionAnchor("B", "Tyr77", (2.0, 0.1, 0.2)),
            InteractionAnchor("C", "Phe91", (-1.0, 1.0, 0.4)),
        ]
        projected = project_and_optimize(ligand, anchors, min_separation=1.0)
        self.assertEqual([item.identifier for item in projected], ["A", "B", "C"])
        self.assertTrue(all(all(abs(value) < 20 for value in item.xy) for item in projected))
        distance = np.linalg.norm(
            np.asarray(projected[0].xy) - np.asarray(projected[1].xy)
        )
        self.assertGreaterEqual(distance, 0.9)
        self.assertNotEqual(projected[0].source_xyz, projected[1].source_xyz)

    def test_projection_rejects_degenerate_or_invalid_geometry(self):
        with self.assertRaises(ValueError):
            project_and_optimize([(0, 0, 0), (1, 0, 0)], [
                InteractionAnchor("A", "A", (2, 0, 0)),
            ])
        with self.assertRaises(ValueError):
            optimize_anchor_layout([
                ProjectedAnchor("A", "A", (0.0, 0.0), (0.0, 0.0, 0.0)),
            ], min_separation=0)

    def test_plip_contact_resolves_full_sidechain_or_mainchain_context(self):
        receptor = self.root / "receptor.pdb"
        receptor.write_text(
            "ATOM      1  N   ASP A  42       0.000   0.000   0.000  1.00 20.00           N\n"
            "ATOM      2  CA  ASP A  42       1.000   0.000   0.000  1.00 20.00           C\n"
            "ATOM      3  C   ASP A  42       2.000   0.000   0.000  1.00 20.00           C\n"
            "ATOM      4  O   ASP A  42       3.000   0.000   0.000  1.00 20.00           O\n"
            "ATOM      5  CB  ASP A  42       1.000   1.000   0.000  1.00 20.00           C\n"
            "ATOM      6  OD1 ASP A  42       1.000   2.000   0.000  1.00 20.00           O\n"
            "ATOM      7  CG  ASP A  42       2.000   1.000   0.000  1.00 20.00           C\n"
        )
        atoms = read_receptor_atoms(receptor)
        sidechain = resolve_contact(
            atoms, residue_name="ASP", residue_number="42", chain="A",
            contact_xyz=(1.0, 2.0, 0.0),
        )
        backbone = resolve_contact(
            atoms, residue_name="ASP", residue_number="42", chain="A",
            contact_xyz=(3.0, 0.0, 0.0),
        )
        self.assertEqual(sidechain.context_kind, "side_chain")
        self.assertEqual(sidechain.interacting_atom, "OD1")
        self.assertEqual(len(sidechain.atoms), 7)
        self.assertEqual(backbone.context_kind, "main_chain")
        self.assertEqual(backbone.interacting_atom, "O")


if __name__ == "__main__":
    unittest.main()
