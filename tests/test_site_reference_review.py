"""Synthetic reference-choice boundaries and portable warning acceptance."""
import copy
import json
from pathlib import Path
import unittest

from docking_universal.services.site_reference_review import stage, normalize, seal, digest, attach
from docking_universal.services.receptor_model_history import normalize_preparation
from docking_universal.services.protocol_import import inspect_protocol_bundle
from docking_universal_bundle import create_bundle, extract_bundle
from docking_universal_box_candidates import config_geometry
from docking_universal.state import RevisionConflictError
import tests.test_site_first_workflow as fixtures
import tests.test_receptor_model_history as report_helpers


class SiteReferenceTests(unittest.TestCase):
    wait = fixtures.SiteFirstWorkflowTests.wait
    explore = fixtures.SiteFirstWorkflowTests.explore
    approve = fixtures.SiteFirstWorkflowTests.approve

    def setUp(self):
        fixtures.SiteFirstWorkflowTests.setUp(self)
        self.explore()
        state = self.store.load('test')
        candidate = state.workflow_data['pocket_candidates'][0]
        self.box = Path(next(a.path for a in state.artifacts if a.id == candidate['box_artifact_id']))
        self.ccd = self.root / 'BEN.cif'
        self.ccd.write_text('data_BEN\n_chem_comp.id BEN\nloop_\n_chem_comp_atom.atom_id\n_chem_comp_atom.type_symbol\nC1 C\nC2 C\nC3 C\n')
        self.library = self.root / 'library.smi'; self.library.write_text('CCC fixture\n')
        self.authority = self.root / 'authority.json'
        self.authority.write_text(json.dumps({'approved_cases': ['fixture']}))
        pin = lambda p: {'path': str(p), 'sha256': digest(p.read_bytes())}
        self.receipt = dict(case_id='fixture', approved=True, source=pin(self.source),
            screening_input=pin(self.library), ccd=pin(self.ccd), authority=pin(self.authority),
            identity=dict(resname='BEN', chain_id='A', residue_number='100', insertion_code='', altloc=''),
            geometry=config_geometry(self.box), screening_smiles='CCC',
            deposited_heavy_atoms=1, complete_ccd_heavy_atoms=3, missing_atom_names=['C2', 'C3'],
            actor='fixture reviewer', rationale='Explicit incomplete-anchor interpretation')
        self.receipt_path = self.root / 'review.json'

    def apply(self, receipt=None, *, revision=None):
        self.receipt_path.write_text(json.dumps(receipt or self.receipt))
        return stage(self.controller, 'test', {'receipt': str(self.receipt_path),
            'reviewed_sha256': digest(self.receipt_path.read_bytes())},
            expected_revision=self.store.load('test').revision if revision is None else revision,
            request_id='fixture-reference-review')

    def test_exact_stage_changes_no_coordinates_box_jobs_or_site_approval(self):
        inputs = {p: p.read_bytes() for p in (self.source, self.box, self.ccd, self.library)}
        before = self.store.load('test')
        result = self.apply()
        after = self.store.load('test')
        self.assertEqual(before.jobs, after.jobs)
        self.assertEqual(after.selected_pocket_ids, [])
        self.assertEqual(before.approvals, after.approvals)
        self.assertEqual(inputs, {p: p.read_bytes() for p in inputs})
        self.assertIn('1/3 heavy atoms', result['warning'])
        self.assertIn('not a pose-recovery control', result['warning'])
        self.assertFalse(after.pending_decisions[0].options[0].automation_eligible)
        self.assertIn(result['warning'], after.pending_decisions[0].consequences)
        self.assertNotIn('receptor_modification_warning', normalize_preparation({'site_reference_review': result}))

    def test_stale_revision_or_receipt_rejected_without_mutation(self):
        state = self.store.load('test')
        with self.assertRaises(RevisionConflictError):
            self.apply(revision=state.revision-1)
        self.receipt_path.write_text(json.dumps(self.receipt))
        with self.assertRaisesRegex(ValueError, 'receipt changed'):
            stage(self.controller, 'test', {'receipt': str(self.receipt_path), 'reviewed_sha256': '0'*64},
                  expected_revision=state.revision, request_id='bad')
        self.assertEqual(self.store.load('test').revision, state.revision)

    def test_unapproved_or_wrong_case_authority_stays_unapproved(self):
        changed = dict(self.receipt, approved=False)
        with self.assertRaisesRegex(ValueError, 'Explicit'):
            self.apply(changed)
        changed = dict(self.receipt, case_id='another-case')
        with self.assertRaisesRegex(ValueError, 'exact case'):
            self.apply(changed)
        self.assertNotIn('reviewed_site_reference', self.store.load('test').workflow_data)

    def test_modified_source_library_ccd_or_authority_stops_review(self):
        for key in ('source', 'screening_input', 'ccd', 'authority'):
            changed = copy.deepcopy(self.receipt); changed[key]['sha256'] = 'f'*64
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'input changed'):
                self.apply(changed)

    def test_changed_box_identity_or_inventory_rejected(self):
        for field in ('geometry', 'identity', 'missing_atom_names'):
            changed = copy.deepcopy(self.receipt)
            if field == 'geometry': changed[field]['center_x'] += 1
            elif field == 'identity': changed[field]['chain_id'] = 'B'
            else: changed[field] = ['C8', 'C9']
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.apply(changed)

    def test_stage_must_precede_ordinary_box_decision_no_replacement(self):
        self.apply()
        with self.assertRaisesRegex(ValueError, 'already retained'):
            self.apply()
        self.approve(self.store.load('test'))
        with self.assertRaisesRegex(ValueError, 'before box approval'):
            self.apply()

    def attached(self):
        record = self.apply()
        state = self.approve(self.store.load('test'))
        self.receptor = self.root / 'receptor.pdbqt'; self.receptor.write_text('ATOM\n')
        receptor_hash = digest(self.receptor.read_bytes())
        regions = [dict(box=str(self.box), box_sha256=digest(self.box.read_bytes()),
                        geometry=config_geometry(self.box), box_label='B1', site_source='input_bound_ligand')]
        preparation = attach({}, state, receptor_hash, regions)
        return state, receptor_hash, regions, preparation

    def test_finalization_refuses_new_site_or_changed_source(self):
        state, receptor_hash, regions, preparation = self.attached()
        changed = copy.deepcopy(regions); changed[0]['box_sha256'] = 'f'*64
        with self.assertRaisesRegex(ValueError, 'site changed'):
            attach({}, state, receptor_hash, changed)
        self.source.write_text(self.source.read_text() + 'REMARK changed\n')
        with self.assertRaisesRegex(ValueError, 'Source reference changed'):
            attach({}, state, receptor_hash, regions)
        self.assertNotIn('receptor_modification_warning', preparation)

    def test_inline_tampering_or_receptor_transfer_and_control_waivers_rejected(self):
        _, receptor_hash, _, preparation = self.attached()
        record = preparation['site_reference_review']
        with self.assertRaisesRegex(ValueError, 'different prepared receptor'):
            normalize(record, '0'*64)
        changed = copy.deepcopy(record); changed['review']['actor'] = 'different'
        with self.assertRaisesRegex(ValueError, 'changed after'):
            normalize(changed)
        changed = copy.deepcopy(record); changed['review']['control_authority'] = True
        changed['review_sha256'] = seal(changed['review'])
        with self.assertRaisesRegex(ValueError, 'cannot authorize'):
            normalize(changed)
        record['warning'] = 'It is safe and validated.'
        self.assertNotIn('safe and validated', normalize(record, receptor_hash)['warning'])

    def test_bundle_and_report_keep_warning_without_original_reference_files(self):
        _, receptor_hash, regions, preparation = self.attached()
        protocol = dict(schema_name='docking-universal-protocol', schema_version=1, engine='vina',
            protocol_type='site-guided-exploratory', exploratory_screening_allowed=True,
            screening_authority='user-confirmed-exploratory-use',
            parameters={'conformers_per_state': 1, 'seeds': [11]},
            locked_inputs={'receptor': str(self.receptor), 'receptor_sha256': receptor_hash,
                           'box': str(self.box), 'box_sha256': digest(self.box.read_bytes()), 'boxes': regions},
            docking_regions=regions, receptor_preparation=preparation)
        path = self.root / 'protocol.json'; path.write_text(json.dumps(protocol))
        bundle = self.root / 'review.duprotocol'; create_bundle(path, self.root, bundle)
        for p in (self.source, self.box, self.ccd, self.library, self.authority, self.receipt_path, self.receptor):
            p.unlink()  # Synthetic fixtures only, proving standalone portability.
        preview = inspect_protocol_bundle(bundle)
        self.assertIn('1/3 heavy atoms', preview['site_reference_warning'])
        self.assertIsNone(preview['receptor_modification_warning'])
        extracted = extract_bundle(bundle)
        portable = json.loads(extracted.read_text())['receptor_preparation']
        (self.root / 'report').mkdir()
        (self.root / 'report/study_summary.json').write_text(json.dumps({'protocol_receptor_preparation': portable}))
        report = report_helpers.REPORT.receptor_preparation_record(self.root)
        from reportlab.lib.styles import getSampleStyleSheet
        note = report_helpers.REPORT.user_approved_removal_report_note(report, self.root, getSampleStyleSheet())
        text = report_helpers.note_text(note)
        self.assertIn('1/3 heavy atoms', text)
        self.assertIn('No reference atoms were filled in', text)
        self.assertNotIn('User-approved receptor component removal', text)


if __name__ == '__main__':
    unittest.main()
