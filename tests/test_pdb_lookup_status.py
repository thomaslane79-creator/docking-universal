from types import SimpleNamespace
import unittest

from docking_universal.services.pdb_lookup_status import lookup_coverage, lookup_notice, lookup_status_for_state


class PdbLookupStatusTests(unittest.TestCase):
    def test_no_history_is_not_claimed_as_a_search(self):
        self.assertEqual(lookup_notice({}), ('', False))
        self.assertEqual(lookup_status_for_state(SimpleNamespace(workflow_data={})), {})

    def test_local_only_setup_is_distinct_from_unavailable(self):
        record = lookup_status_for_state(SimpleNamespace(workflow_data={
            'study_setup': {'pdb_pocket_evidence': 'off'}}))
        text, warning = lookup_notice(record)
        self.assertIn('Local-only evidence', text)
        self.assertIn('search is off', text)
        self.assertFalse(warning)
        text, warning = lookup_notice({'mode': 'related-structures', 'status': 'unavailable'})
        self.assertTrue(warning)
        self.assertIn('internet required', text)
        self.assertIn('does not mean no supporting evidence', text)

    def test_incomplete_downloads_do_not_become_no_evidence(self):
        coverage = lookup_coverage({'candidate_entries': ['1ABC', '2ABC'], 'evidence': [],
            'skipped': [{'entry': '1ABC', 'reason': 'no qualifying alignment'},
                        {'entry': '2ABC', 'reason': 'download failed: timed out'}]})
        self.assertEqual(coverage['failed_entries'], ['2ABC'])
        self.assertEqual(coverage['failed_entry_count'], 1)
        text, warning = lookup_notice({'status': 'completed', 'coverage': coverage})
        self.assertTrue(warning)
        self.assertIn('incomplete', text)
        self.assertNotIn('No qualifying', text)

    def test_successful_no_match_query_remains_distinct(self):
        text, warning = lookup_notice({'status': 'completed', 'coverage': lookup_coverage({})})
        self.assertFalse(warning)
        self.assertIn('search completed', text)
        self.assertIn('No qualifying', text)
        self.assertEqual(lookup_notice({'status': 'completed', 'coverage': {'observation_count': 5}}), ('', False))
