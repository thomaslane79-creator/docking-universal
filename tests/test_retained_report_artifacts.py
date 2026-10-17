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
    def test_scoring_function_is_immediately_after_the_best_result_not_in_protocol_options(self):
        result={'name':'Ligand','status':'COMPLETED','best_energy_kcal_per_mol':'-6.02',
                'top_cluster':'3','top_cluster_population':'2','cluster_count':3}
        for engine, name in (('adgpu','AD4'),('vina','Vina'),('qvinaw','Vina')):
            rows = REPORT.single_compound_summary_rows(result,engine)
            best = rows.index(['Best retained docking score','-6.02 kcal/mol'])
            self.assertEqual(rows[best+1],['Scoring function',name])
            self.assertNotIn('Scoring function',str(REPORT.protocol_summary_rows(engine,{},{})))
        self.assertEqual(REPORT.scoring_function_label(None),'Not recorded')
        self.assertEqual(REPORT.scoring_function_label('unrecorded'),'Not recorded')

    def test_protocol_summary_contains_only_user_selectable_options(self):
        configured = {'ph':7.4, 'charge_model':'gasteiger', 'forcefield':'mmff94',
            'conformers_per_state':3, 'seeds':[11,22,33,44,55], 'ensemble_seed':11,
            'ad4':{'lga_runs':20,'heuristic_cap':12000000,'autostop':True,
                   'population':150,'generations':42000,'local_iterations':300},
            'private_future_setting':'DO_NOT_DUMP'}
        rows = REPORT.protocol_summary_rows('adgpu',{},configured)
        text = str(rows)
        self.assertEqual(len(rows),8)
        self.assertEqual([row[0] for row in rows[1:]], ['Docking program','Ligand preparation pH',
            'Starting shapes per chemical state','Independent repeats per shape','Starting random seed',
            'Genetic runs per repeat','Heuristic evaluation cap'])
        self.assertIn(['Independent repeats per shape',5],rows)
        for internal in ('Protocol basis','forcefield','gasteiger','Saved poses','autostop','grid','Population','42000','Local iterations','Input limits','DO_NOT_DUMP'):
            self.assertNotIn(internal,text)
        self.assertEqual(configured['ad4']['population'],150)

    def test_vina_protocol_summary_preserves_actual_effort_and_output_settings(self):
        rows = REPORT.protocol_summary_rows('vina',{'exhaustiveness':'32'},
            {'exhaustiveness':16,'num_modes':15,'energy_range_kcal_per_mol':8,'seeds':[1,2]})
        self.assertIn(['Exhaustiveness','32'],rows)
        self.assertIn(['Modes per job',15],rows)
        self.assertIn(['Energy range','8 kcal/mol'],rows)
        self.assertNotIn('Genetic runs',str(rows))

    def test_unobserved_future_engine_version_is_not_a_claimed_version_difference(self):
        comparison = REPORT.compare_scientific_versions({'engine_version':'recorded when screening runs'},
            {'engine_version':'AutoDock-GPU v1.6'}, 'AutoDock-GPU')
        self.assertEqual(next(row['status'] for row in comparison['entries'] if row['software']=='AutoDock-GPU'),'NOT VERIFIED')

    def test_approved_layout_retries_supported_spacing_without_changing_contacts(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);interactions=root/'interactions';interactions.mkdir()
            (interactions/'report.xml').write_text('<report/>')
            (interactions/'complex_protonated.pdb').write_text('RECEPTOR')
            ligand=root/'ligand.sdf';ligand.write_text('LIGAND')
            output=interactions/'diagram.png';calls=[]
            runtime={'status':'available','components':{'node':{'path':'node'},'chrome':{'path':'chrome'}}}
            def render(command, **kwargs):
                calls.append(command)
                if len(calls)==1:
                    return SimpleNamespace(returncode=1,stdout='',stderr='collision-free unambiguous layout')
                output.write_bytes(b'checked-image')
                output.with_suffix('.manifest.json').write_text(json.dumps({'renderer_policy':'approved-poseedit-local-v1'}))
                return SimpleNamespace(returncode=0,stdout='',stderr='')
            with patch('docking_universal.runtime_inventory.discover_poseedit_runtime',return_value=runtime), patch.object(FIGURES.subprocess,'run',side_effect=render):
                self.assertTrue(FIGURES.render_poseedit_plip2d(interactions,ligand,output))
            self.assertEqual(len(calls),2)
            self.assertEqual(calls[1][-2:],['--ligand-spacing','20'])
            self.assertEqual((interactions/'report.xml').read_text(),'<report/>')
            self.assertTrue((interactions/'plip2d.approved-spacing-15.log').is_file())

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

    def test_new_control_clusters_use_one_point_five_angstrom_not_recovery_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory)
            receptor = control / "receptor.pdb"
            receptor.write_text("ATOM\n")
            protocol = control / "protocol.json"
            protocol.write_text(json.dumps({"locked_inputs": {"receptor": str(receptor.with_suffix('.pdbqt'))},
                                            "acceptance": {"threshold_angstrom": 2.0}}))
            with patch.object(FIGURES.subprocess, "run") as run:
                run.return_value.returncode = 0
                FIGURES.ensure_control_clusters(control, protocol)
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--cluster-rmsd") + 1], "1.5")

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
