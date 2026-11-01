"""Exercise actual ReportLab page breaks for warnings and references."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pagination_pdf', ROOT / 'libexec/docking-universal-pdf-report.py')
REPORT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(REPORT)


class ReportPaginationTests(unittest.TestCase):
    def setUp(self):
        try:
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import SimpleDocTemplate
        except ImportError:
            self.skipTest('ReportLab unavailable in this runtime')
        self.styles = getSampleStyleSheet()
        self.styles.add(ParagraphStyle('ReferenceDU', fontSize=8, leading=10))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.events = []
        events = self.events

        class ObservedDocument(SimpleDocTemplate):
            def afterFlowable(self, item):
                if hasattr(item, 'getPlainText'):
                    events.append((self.page, item.getPlainText()))

        self.doc = ObservedDocument(str(Path(self.tmp.name) / 'test.pdf'),
                                    pagesize=(400, 500), leftMargin=30, rightMargin=30,
                                    topMargin=30, bottomMargin=30)

    def build_near_boundary(self, section):
        from reportlab.platypus import Paragraph, Spacer
        paragraphs = section[0]._content
        block_height = sum(p.wrap(self.doc.width - 12, self.doc.height)[1] +
                           p.getSpaceBefore() + p.getSpaceAfter() for p in paragraphs)
        lead = Paragraph('Earlier content.', self.styles['BodyText'])
        self.doc.build([lead, Spacer(1, self.doc.height - block_height / 2 - 32), *section])

    def test_review_warning_moves_whole_to_next_page(self):
        warning = {'severity': 'high', 'summary':
                   'User-approved deposited alternate locations and exact sugar exclusions. ' * 9}
        section = REPORT.user_approved_removal_report_note(
            {'receptor_modification_warning': warning}, Path(self.tmp.name), self.styles)
        self.build_near_boundary(section)
        notes = [(page, text) for page, text in self.events if text != 'Earlier content.']
        self.assertEqual(len(notes), 1, 'Warning was split into separate paragraph fragments')
        self.assertEqual(notes[0][0], 2)
        self.assertIn(warning['summary'].strip(), notes[0][1])
        self.assertIn('Review the retained change inventory', notes[0][1])

    def test_page_sized_bibliography_stays_with_its_heading(self):
        references = [{'citation': f'Reference {n}. Scientific method.',
                       'url': f'https://example.org/{n}'} for n in range(1, 14)]
        self.build_near_boundary(REPORT.scientific_reference_section(references, self.styles))
        notes = [(page, text) for page, text in self.events if text != 'Earlier content.']
        self.assertEqual(len(notes), 14)
        self.assertEqual({page for page, text in notes}, {2})
        self.assertEqual(notes[0][1], 'Scientific and software references')
        self.assertIn('13. Reference 13.', notes[-1][1])

    def test_bibliography_longer_than_one_page_can_still_split(self):
        references = [{'citation': f'Reference {n}. Scientific method.',
                       'url': f'https://example.org/{n}'} for n in range(1, 90)]
        self.doc.build(REPORT.scientific_reference_section(references, self.styles))
        self.assertGreater(len({page for page, text in self.events}), 1)
        self.assertIn('89. Reference 89.', self.events[-1][1])


if __name__ == '__main__':
    unittest.main()
