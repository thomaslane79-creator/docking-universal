#!/usr/bin/env python3
"""Regression tests for report reuse of retained scientific artifacts."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FIGURES = load("docking_universal_report_figures", "libexec/docking-universal-report-figures.py")
REPORT = load("docking_universal_pdf_report", "libexec/docking-universal-pdf-report.py")


class RetainedReportArtifactTests(unittest.TestCase):
    def test_screen_report_can_reconstruct_the_locked_protocol_pocket(self):
        cavity = REPORT.inherited_protocol_cavity_record({
            "pocket_detection": {"engine": "p2rank"},
            "docking_regions": [{
                "box_label": "P1", "box_name": "target_pocket1.conf",
                "geometry": {"center_x": 1, "center_y": 2, "center_z": 3,
                             "size_x": 26, "size_y": 28, "size_z": 30},
            }],
        })
        self.assertEqual(cavity["pocket_engine_name"], "P2Rank")
        self.assertEqual(cavity["selected_file"], "P1")
        self.assertEqual(cavity["box_dimensions"], [26, 28, 30])

    def test_conformational_evidence_is_loaded_from_a_portable_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            retained = root / "evidence" / "structural_ensemble" / "conformational_evidence.json"
            retained.parent.mkdir(parents=True)
            retained.write_text(json.dumps({
                "rigid_docking_site_assessment": {"status": "conformationally_incompatible"},
            }))
            protocol_path = root / "protocol.json"
            protocol_path.write_text("{}")
            protocol = {"pdb_pocket_evidence": {"structural_ensemble": {
                "conformational_evidence": "structural_ensemble/conformational_evidence.json",
            }}}
            evidence = REPORT.protocol_conformational_evidence(protocol, protocol_path)
            self.assertEqual(
                evidence["rigid_docking_site_assessment"]["status"],
                "conformationally_incompatible",
            )

    def test_poseedit_runtime_is_retained_with_its_local_software_references(self):
        provenance = {
            "study": "/unused",
            "methods": {"interaction_diagram": "approved-poseedit-local-v1"},
            "software": [
                {"software": "Docking Universal PoseEdit-style renderer", "version": "1.0.0"},
                {"software": "Playwright", "version": "1.63.0"},
                {"software": "Node.js", "version": "22.0.0"},
            ],
            "references": [
                {"citation": "PoseEdit. Center for Bioinformatics, University of Hamburg."},
                {"citation": "Microsoft. Playwright documentation."},
                {"citation": "OpenJS Foundation. Node.js documentation."},
            ],
            "receptor_preparation": {},
        }
        retained = REPORT.retain_used_report_methods(provenance, None, False)
        self.assertEqual(
            {item["software"] for item in retained["software"]},
            {"Docking Universal PoseEdit-style renderer", "Playwright", "Node.js"},
        )
        self.assertEqual(len(retained["references"]), 3)

    def test_pocket_caption_does_not_expose_plotting_implementation_language(self):
        source = (ROOT / "libexec/docking-universal-pdf-report.py").read_text()
        self.assertNotIn("Up to ten highest-ranked", source)
        self.assertNotIn("L# marks a ligand-defined box", source)
        self.assertNotIn("scores from different detector families are not directly comparable", source)
        self.assertNotIn("Related-structure ligand locations were compared with fpocket candidates", source)
        self.assertNotIn("The fpocket search status was not recorded", source)
        self.assertNotIn("supporting fpocket surface", source)

    def test_retained_plip_calls_prefer_approved_renderer_without_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(FIGURES, "render_poseedit_plip2d", return_value=True) as approved,
                patch.object(FIGURES, "render_sdf_plip2d") as legacy,
                patch.object(FIGURES.subprocess, "run") as run,
            ):
                rendered = FIGURES.render_plip2d(
                    root / "interactions",
                    root / "ligand.sdf",
                    root / "diagram.png",
                    root / "plip_to_2d.py",
                    ligand_id="LIG:A:1",
                )
        self.assertTrue(rendered)
        approved.assert_called_once()
        legacy.assert_not_called()
        run.assert_not_called()

    def test_unavailable_approved_renderer_uses_existing_sdf_compatibility_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(FIGURES, "render_poseedit_plip2d", return_value=False),
                patch.object(FIGURES, "render_sdf_plip2d", return_value=True) as compatibility,
            ):
                self.assertTrue(FIGURES.render_plip2d(
                    root / "interactions", root / "ligand.sdf", root / "diagram.png", None,
                ))
        compatibility.assert_called_once()

    def test_native_renderer_uses_protein_side_coordinates_for_layout(self):
        from rdkit import Chem
        from rdkit.Chem import AllChem

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            interactions = root / "interactions"
            interactions.mkdir()
            molecule = Chem.AddHs(Chem.MolFromSmiles("CCO"))
            self.assertGreaterEqual(AllChem.EmbedMolecule(molecule, randomSeed=9), 0)
            writer = Chem.SDWriter(str(root / "ligand.sdf"))
            writer.write(molecule)
            writer.close()
            conf = molecule.GetConformer()
            p1 = conf.GetAtomPosition(0)
            p2 = conf.GetAtomPosition(1)
            (interactions / "report.xml").write_text(f"""<?xml version='1.0'?>
<report><bindingsite><identifiers><hetid>LIG</hetid><chain>A</chain><position>1</position></identifiers>
<interactions><hydrogen_bonds><hydrogen_bond><restype>Asp</restype><resnr>42</resnr><reschain>A</reschain>
<ligcoo><x>{p1.x}</x><y>{p1.y}</y><z>{p1.z}</z></ligcoo>
<protcoo><x>4.0</x><y>1.0</y><z>0.0</z></protcoo><dist_d-a>2.8</dist_d-a><don_angle>120</don_angle></hydrogen_bond>
<hydrogen_bond><restype>Tyr</restype><resnr>77</resnr><reschain>A</reschain>
<ligcoo><x>{p2.x}</x><y>{p2.y}</y><z>{p2.z}</z></ligcoo>
<protcoo><x>4.0</x><y>-1.0</y><z>0.3</z></protcoo><dist_d-a>3.0</dist_d-a><don_angle>115</don_angle></hydrogen_bond>
</hydrogen_bonds></interactions></bindingsite></report>""")
            output = root / "diagram.png"
            self.assertTrue(FIGURES.render_sdf_plip2d(interactions, root / "ligand.sdf", output, ligand_id="LIG:A:1"))
            manifest = json.loads(output.with_suffix(".manifest.json").read_text())
            self.assertTrue(manifest["layout_projection_used"])
            self.assertTrue(output.is_file())

    def test_existing_control_clusters_are_reused_without_reclustering(self):
        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory)
            analysis = control / "report" / "control_pose_analysis"
            analysis.mkdir(parents=True)
            (analysis / "cluster_summary.csv").write_text("energy_rank,cluster_id\n1,1\n")
            with patch.object(FIGURES.subprocess, "run") as run:
                selected = FIGURES.ensure_control_clusters(control, control / "protocol.json")
        self.assertEqual(selected, analysis)
        run.assert_not_called()

    def test_only_nonempty_cluster_results_mark_a_study_as_docked(self):
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory)
            analysis = study / "compounds" / "ligand" / "pose_analysis"
            analysis.mkdir(parents=True)
            clusters = analysis / "cluster_summary.csv"
            self.assertFalse(REPORT.has_retained_docking_results(study))
            clusters.write_text("")
            self.assertFalse(REPORT.has_retained_docking_results(study))
            clusters.write_text("energy_rank,cluster_id\n1,1\n")
            self.assertTrue(REPORT.has_retained_docking_results(study))


if __name__ == "__main__":
    unittest.main()
