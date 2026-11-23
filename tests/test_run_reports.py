import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfReader
from reportlab.pdfgen import canvas

from docking_universal.services.run_reports import (
    available_run_reports, build_merged_report, combine_run_sections, export_report, require_matching_methods,
)
from docking_universal.models import ArtifactRecord
from docking_universal.state import StudyState


class RunReportsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.runs = [self.make_run('run1'), self.make_run('run2')]

    def tearDown(self):
        self.temporary.cleanup()

    def make_run(self, name):
        root = self.root / name
        (root / 'inputs' / 'locked_protocol').mkdir(parents=True)
        (root / 'inputs' / 'locked_protocol' / 'protocol.json').write_text('{"method": "same"}')
        (root / 'report').mkdir()
        (root / 'compounds' / 'same').mkdir(parents=True)
        manifest = {'configured_engine': 'vina', 'configured_engine_version': '1',
                    'configured_docking_parameters': {'seeds': [1]}, 'configured_locked_inputs': {'receptor_sha256': 'abc'},
                    'scientific_software': {'vina': '1'}, 'analysis': 'representatives',
                    'representatives': 3, 'cluster_rmsd_angstrom': 1.5, 'protocol_type': 'control-validated'}
        (root / 'study_manifest.json').write_text(json.dumps(manifest))
        (root / 'report' / 'study_summary.json').write_text(json.dumps({**manifest, 'compounds': [{'compound_id': 'same', 'compound_name': name}]}))
        (root / 'inputs' / 'compound_library_inventory.json').write_text(json.dumps({'compounds': [{'compound_id': 'same', 'compound_name': name}]}))
        report = root / 'report' / 'run.pdf'
        pdf = canvas.Canvas(str(report)); pdf.drawString(100, 700, name); pdf.save()
        return root

    def test_run_list_groups_reports_and_uses_corrected_copy(self):
        state = StudyState('s', 's', 'screening')
        for i, root in enumerate(self.runs):
            state.artifacts.append(ArtifactRecord(str(i), 'screening_report', str(root / 'report' / 'run.pdf')))
        records = available_run_reports(state)
        self.assertEqual([item['root'] for item in records], [root.resolve() for root in self.runs])
        self.assertEqual(records[0]['names'], ['run1'])

    def test_separate_sections_preserve_both_originals(self):
        reports = [root / 'report' / 'run.pdf' for root in self.runs]
        before = [p.read_bytes() for p in reports]
        output = self.root / 'sections.pdf'
        combine_run_sections(reports, output)
        self.assertEqual(len(PdfReader(output).pages), 4)
        self.assertEqual([p.read_bytes() for p in reports], before)
        with self.assertRaisesRegex(ValueError, 'cannot be overwritten'):
            combine_run_sections(reports, reports[0])

    def test_pdf_export_preserves_source_and_passes_quality(self):
        source = self.runs[0] / 'report' / 'run.pdf'
        original = source.read_bytes()
        output = self.root / 'quality.pdf'
        def generate(command, **kwargs):
            quality = command[command.index('--pdf-quality') + 1]
            self.assertEqual(quality, 'high-resolution')
            self.assertNotEqual(Path(command[-1]).parent, source.parent)
            pdf = canvas.Canvas(command[-1]); pdf.drawString(100, 700, quality); pdf.save()
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        with patch('docking_universal.services.run_reports.subprocess.run', side_effect=generate):
            export_report(source, output, 'python', 'report.py', 'high-resolution')
        self.assertIn('high-resolution', PdfReader(output).pages[0].extract_text())
        self.assertEqual(source.read_bytes(), original)

    def test_full_merge_rejects_any_method_difference_or_unknown(self):
        self.assertTrue(require_matching_methods(self.runs))
        path = self.runs[1] / 'study_manifest.json'
        manifest = json.loads(path.read_text()); manifest['cluster_rmsd_angstrom'] = 2.0
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'do not have exactly matching'):
            require_matching_methods(self.runs)
        del manifest['scientific_software']; path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'Cannot verify'):
            require_matching_methods(self.runs)

    def test_selector_offers_all_modes_and_disables_incompatible_merge(self):
        from docking_universal.gui.qt import QtCore, QtWidgets
        from docking_universal.gui.run_report_selector import RunReportSelector
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        runs = [{'root': root.resolve(), 'report': root / 'report' / 'run.pdf', 'names': [root.name]} for root in self.runs]
        dialog = RunReportSelector(runs, self.runs[0].resolve())
        self.assertEqual([dialog.mode.itemData(i) for i in range(dialog.mode.count())], ['individual', 'sections', 'merged'])
        self.assertEqual(dialog.quality.currentData(), 'saved')
        dialog.runs.item(1).setCheckState(QtCore.Qt.CheckState.Checked)
        dialog.mode.setCurrentIndex(dialog.mode.findData('merged'))
        self.assertEqual(dialog.quality.currentData(), 'compressed')
        self.assertFalse(dialog.quality.model().item(0).isEnabled())
        self.assertTrue(dialog.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).isEnabled())
        path = self.runs[1] / 'study_manifest.json'
        manifest = json.loads(path.read_text()); manifest['configured_engine_version'] = 'different'
        path.write_text(json.dumps(manifest))
        dialog._update()
        self.assertFalse(dialog.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).isEnabled())
        self.assertIn('do not have exactly matching', dialog.status.text())
        dialog.mode.setCurrentIndex(dialog.mode.findData('sections'))
        self.assertTrue(dialog.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).isEnabled())
        dialog.close()

    def test_full_merge_separates_duplicate_ids_and_keeps_source_runs_unchanged(self):
        # Reverse alphabetical order relative to run order.
        for root, name in zip(self.runs, ('Zinc', 'alpha')):
            for path in (root / 'report' / 'study_summary.json', root / 'inputs' / 'compound_library_inventory.json'):
                data = json.loads(path.read_text())
                data['compounds'][0]['compound_name'] = name
                path.write_text(json.dumps(data))
        original = [(root / 'report' / 'study_summary.json').read_bytes() for root in self.runs]
        reports = [root / 'report' / 'run.pdf' for root in self.runs]
        output = self.root / 'merged.pdf'
        def generate(command, **kwargs):
            stage = Path(command[2]); summary = json.loads((stage / 'report' / 'study_summary.json').read_text())
            self.assertEqual([row['compound_id'] for row in summary['compounds']], ['run002_same', 'run001_same'])
            self.assertIn('alpha (run 2: run2)', summary['compounds'][0]['compound_name'])
            self.assertIn('Zinc (run 1: run1)', summary['compounds'][1]['compound_name'])
            pdf = canvas.Canvas(command[-1]); pdf.drawString(100, 700, 'merged results'); pdf.save()
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        with patch('docking_universal.services.run_reports.subprocess.run', side_effect=generate):
            build_merged_report(self.runs, reports, output, 'python', 'report.py')
        self.assertEqual(len(PdfReader(output).pages), 2)
        self.assertEqual([(root / 'report' / 'study_summary.json').read_bytes() for root in self.runs], original)
