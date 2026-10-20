import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docking_universal.pocket_metadata import annotate_regions, region_prediction
from docking_universal.reporting import compound_overview_rows

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name,ROOT/path)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


REPORT = load('synchronized_pdf','libexec/docking-universal-pdf-report.py')
RUN = load('synchronized_run','libexec/docking-universal-run.py')


class ReportSynchronizationTests(unittest.TestCase):
    def test_ligand_only_report_records_no_detector_without_inventing_fpocket(self):
        with tempfile.TemporaryDirectory() as directory:
            protocol = {'pocket_detection': {'engine': 'none'}}
            provenance = REPORT.reproducibility_record(protocol, Path(directory), None)
            definition = next(row for row in provenance['software']
                              if row['role'] == 'Docking-region definition')
            self.assertEqual(definition['software'], 'Exact input-ligand site')
            self.assertEqual(definition['version'], 'Pocket prediction not requested')
            self.assertFalse(any(row['role'] == 'Ligand-free cavity detection'
                                 for row in provenance['software']))
            self.assertIn('Not requested', provenance['methods']['cavity_detection'])
            used = REPORT.retain_used_report_methods(provenance, None, has_docking=True)
            self.assertIn(definition, used['software'])
            self.assertFalse(any('Fpocket:' in row['citation'] or 'P2Rank:' in row['citation']
                                 for row in used['references']))

    def test_retained_cavity_methods_use_the_recorded_predictor_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cavity = root / 'preparation/target_receptor_prep/cavity'
            cavity.mkdir(parents=True)
            self.fixture(cavity)
            provenance = REPORT.reproducibility_record(
                {'pocket_detection': {'engine': 'p2rank'}, 'software': {'p2rank': '2.5.1'}}, root, None)
            self.assertIn('P2Rank pocket detection', provenance['methods']['cavity_detection'])

    def test_unrecognized_detector_is_reported_without_legacy_detector_substitution(self):
        with tempfile.TemporaryDirectory() as directory:
            provenance = REPORT.reproducibility_record(
                {'pocket_detection': {'engine': 'custom-detector'}}, Path(directory), None)
            detector = next(row for row in provenance['software']
                            if row['role'] == 'Ligand-free cavity detection')
            self.assertEqual(detector['software'], 'custom-detector')
            self.assertEqual(detector['version'], 'not recorded')

    def test_missing_legacy_detector_record_preserves_historical_fpocket_default(self):
        with tempfile.TemporaryDirectory() as directory:
            provenance = REPORT.reproducibility_record(
                {'software': {'fpocket': 'legacy-version'}}, Path(directory), None)
            detector = next(row for row in provenance['software']
                            if row['role'] == 'Ligand-free cavity detection')
            self.assertEqual(detector['software'], 'fpocket')
            self.assertEqual(detector['version'], 'legacy-version')

    def test_reused_detector_version_comes_from_locked_protocol_not_screening_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'report').mkdir()
            (root / 'report/study_summary.json').write_text(json.dumps({
                'scientific_software': {'p2rank': 'not recorded', 'rdkit': 'current-screen-version'}}))
            protocol = {'pocket_detection': {'engine': 'p2rank'},
                        'software': {'p2rank': '2.5.1', 'rdkit': 'old-preparation-version'}}
            provenance = REPORT.reproducibility_record(protocol, root, None)
            versions = {row['software']: row['version'] for row in provenance['software']}
            self.assertEqual(versions['P2Rank'], '2.5.1')
            self.assertEqual(versions['RDKit'], 'current-screen-version')

    def fixture(self, root, number=1):
        box=root/f'target_pocket{number}.conf';box.write_text('center_x = 1\n')
        table=root/'pocket_selection_diagnostics.tsv'
        table.write_text('rank_order\tpocket_file\tscore\tprobability\tpocket_engine\n'
            '1\tpocket1_atm.pdb\t2.49\t0.069\tp2rank\n'
            '4\tpocket4_atm.pdb\t1.11\t0.008\tp2rank\n')
        return {'box':str(box),'box_name':box.name,'box_label':f'P{number}',
                'box_sha256':hashlib.sha256(box.read_bytes()).hexdigest(),'geometry':{}}

    def test_selected_score_not_top_score_and_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);region=self.fixture(root,4)
            self.assertEqual(region_prediction(region,detector='p2rank')['score'],1.11)
            Path(region['box']).write_text('changed')
            self.assertEqual(region_prediction(region,detector='p2rank'),{})

    def test_preparation_only_report_resolves_locked_box_without_run_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cavity=root/'preparation/target_receptor_prep/cavity'
            cavity.mkdir(parents=True);region=self.fixture(cavity,4)
            self.fixture(cavity,1)
            report=root/'report';report.mkdir()
            summary={'configured_locked_inputs':{'box':region['box']},
                     'selected_docking_regions':[region]}
            path=report/'study_summary.json';path.write_text(json.dumps(summary))
            record=REPORT.discover_cavity_record(root)
            self.assertEqual(record['config'],'target_pocket4.conf')
            self.assertEqual(record['selected']['score'],'1.11')
            summary['report_purpose']='pocket-review';path.write_text(json.dumps(summary))
            record=REPORT.discover_cavity_record(root)
            self.assertEqual(record['selected']['score'],'2.49')

    def test_ligand_defined_report_never_borrows_first_prediction(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cavity=root/'preparation/target_receptor_prep/cavity'
            cavity.mkdir(parents=True);region=self.fixture(cavity)
            region.update(box=str(cavity/'target_evidence_L1.conf'),box_label='L1')
            report=root/'report';report.mkdir()
            (report/'study_summary.json').write_text(json.dumps({
                'selected_docking_regions':[region]}))
            record=REPORT.discover_cavity_record(root)
            self.assertEqual(record['selected']['rank_score'],'Not applicable (ligand-defined region)')

    def test_input_bound_ligand_region_never_inherits_a_prediction_score(self):
        region = {'box_label':'B1', 'box_name':'target_bound_ligand.conf', 'box':'missing.conf',
                  'site_source':'input_bound_ligand', 'geometry':{}}
        self.assertEqual(region_prediction(region, detector='p2rank'), {})
        record = REPORT.inherited_protocol_cavity_record({'pocket_detection':{'engine':'p2rank'},
                                                         'docking_regions':[region]})
        self.assertEqual(record['selected']['rank_score'], 'Not applicable (ligand-defined region)')

    def test_portable_protocol_preserves_detector_without_local_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);report=root/'report';report.mkdir()
            (report/'study_summary.json').write_text(json.dumps({
                'docking_universal_version':'0.7.0',
                'scientific_software':{'p2rank':'2.5.1','python':'3.9.23'}}))
            protocol={'pocket_detection':{'engine':'p2rank'}}
            provenance=REPORT.reproducibility_record(protocol,root,None)
            detector=next(item for item in provenance['software']
                          if item['role']=='Ligand-free cavity detection')
            self.assertEqual(detector['software'],'P2Rank')
            self.assertEqual(detector['version'],'2.5.1')

    def test_prediction_is_portable_and_does_not_mutate_approved_regions(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);region=self.fixture(root)
            annotated=annotate_regions([region],detector='p2rank')[0]
            self.assertNotIn('pocket_prediction',region)
            Path(region['box']).unlink()
            (root/'pocket_selection_diagnostics.tsv').unlink()
            self.assertEqual(region_prediction(annotated,detector='p2rank')['score'],2.49)
            self.assertEqual(region_prediction(annotated,detector='p2rank')['probability'],.069)
            self.assertEqual(region_prediction(annotated,detector='fpocket'),{})

    def test_fpocket_output_order_is_not_the_source_pocket_number(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);region=self.fixture(root)
            (root/'pocket_selection_diagnostics.tsv').write_text(
                'rank_order\tpocket_file\tscore\tpocket_engine\n1\tpocket5_atm.pdb\t0.8\tfpocket\n')
            result=region_prediction(region,detector='fpocket')
            self.assertEqual(result['pocket_file'],'pocket5_atm.pdb')
            self.assertEqual(result['score'],.8)

    def test_non_finite_scores_are_not_reported_as_measurements(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);region=self.fixture(root)
            table=root/'pocket_selection_diagnostics.tsv'
            table.write_text(table.read_text().replace('2.49','nan'))
            self.assertEqual(region_prediction(region,detector='p2rank'),{})

    def test_consolidated_and_ligand_boxes_do_not_acquire_prediction_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);region=self.fixture(root)
            for name,label in [('target_consolidated_P1-P2.conf','P1/P2'),('target_evidence_L1.conf','L1')]:
                candidate={**region,'box_name':name,'box_label':label}
                self.assertEqual(region_prediction(candidate),{})

    def test_reused_legacy_protocol_recovers_only_verified_original_box(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);original=self.fixture(root)
            portable={**original,'box':'assets/target_pocket1.conf'}
            protocol={'pocket_detection':{'engine':'p2rank'},'docking_regions':[portable],
                      'selectable_docking_boxes':[original]}
            result=REPORT.inherited_protocol_cavity_record(protocol,root/'protocol.json')
            self.assertEqual(result['selected']['rank_score'],2.49)
            self.assertEqual(result['selected']['probability'],.069)
            Path(original['box']).unlink()
            result=REPORT.inherited_protocol_cavity_record(protocol,root/'protocol.json')
            self.assertEqual(result['selected']['rank_score'],'Not retained in this protocol')
            self.assertNotIn('protocol-selection report',str(result))

    def test_pdf_html_markdown_share_headers_and_keep_diagnostics_in_csv(self):
        for engine,score_name in [('vina','Vina'),('qvinaw','Vina'),('adgpu','AD4')]:
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);compound=root/'compounds/c';analysis=compound/'pose_analysis'
                analysis.mkdir(parents=True)
                (analysis/'cluster_summary.csv').write_text(
                    'energy_rank,cluster_id,best_energy_kcal_per_mol,pose_count,seed_support,selected\n'
                    '2,1,-5.98,9,1,yes\n1,3,-6.02,2,1,yes\n')
                (compound/'screen_manifest.json').write_text(json.dumps({'engine':engine}))
                manifest={'study_name':'Report test','study_status':'EXPLORATORY_NO_CONTROL',
                    'workflow':'screen','configured_engine':engine,'completion_status':'COMPLETED',
                    'configured_docking_parameters':{'ph':7.4,'conformers_per_state':1,'seeds':[1],
                        'ad4':{'lga_runs':20,'heuristic_cap':12000000}}}
                # No docking, visual regeneration or PDF authoring in this
                # lightweight text-table contract check.
                with patch.object(RUN.subprocess,'run',side_effect=FileNotFoundError('PDF disabled in unit fixture')):
                    RUN.write_reports(root,manifest,[{'compound_id':'c','compound_name':'Compound <1>'}])
                html=(root/'report/index.html').read_text();md=(root/'report/study_report.md').read_text()
                self.assertIn('Best docking score</th><th>Scoring function',html)
                self.assertIn(f'<td>-6.02 kcal/mol</td><td>{score_name}</td>',html)
                self.assertIn(f'-6.02 kcal/mol | {score_name}',md)
                self.assertIn('Compound &lt;1&gt;',html)
                self.assertNotIn('Representatives',md)
                self.assertNotIn('Seed support',md)
                self.assertNotIn('best_cluster_seed_support',html)
                with (root/'report/compound_summary.csv').open() as handle:
                    rows=list(csv.DictReader(handle))
                self.assertEqual(rows[0]['best_cluster_seed_support'],'1')
                self.assertEqual(rows[0]['selected_representatives'],'2')
                self.assertEqual(rows[0]['top_cluster_id'],'3')
                self.assertEqual(compound_overview_rows([{'name':'Compound','best_energy_kcal_per_mol':-6.02}],engine)[0][1:3],
                                 ['Best docking score','Scoring function'])


if __name__=='__main__':unittest.main()
