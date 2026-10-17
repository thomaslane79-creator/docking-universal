import unittest
from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.gui.ligand_library_panel import LigandLibraryPanel


class LigandLibraryPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_selection_is_explicit_and_independent_of_inspection(self):
        panel = LigandLibraryPanel()
        self.assertIsNone(panel.selection())
        panel.set_library({'fingerprint': 'abc', 'records': [
            {'record_id': str(i), 'name': f'Compound {i}', 'source': '/tmp/library.sdf',
             'source_record': i, 'formula': 'C2H6O', 'formal_charge': 0,
             'valid': i != 3, 'error': 'Invalid chemistry' if i == 3 else ''}
            for i in range(1, 4)]})
        self.assertEqual(panel.selection()['record_ids'], [])
        self.assertIn('Input structure and charge as supplied', panel.preview_basis.text())
        self.assertIn('not adjusted to the protocol pH', panel.preview_basis.text())
        inspected = []
        panel.previewRequested.connect(inspected.append)
        panel.table.setCurrentCell(1, 1)
        self.assertEqual(inspected[-1], '2')
        self.assertEqual(panel.selection()['record_ids'], [])
        panel.table.item(1, 0).setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertEqual(panel.selection()['record_ids'], ['2'])
        panel.set_all(True)
        self.assertEqual(panel.selection()['record_ids'], ['1', '2'])
        self.assertIn('1 invalid record', panel.summary.text())
        panel.set_all(False)
        self.assertEqual(panel.selection()['record_ids'], [])
        panel.clear()
        self.assertIsNone(panel.selection())
        panel.close()

    def test_tabular_suggestions_need_approval_and_edits_clear_selection(self):
        panel = LigandLibraryPanel()
        draft = {'fingerprint': 'draft', 'records': [], 'mapping_approved': False,
                 'table': {'columns': [{'index': i, 'label': label} for i, label in enumerate(('ID', 'SMILES', 'Other'))],
                           'sheets': ['Compounds', 'Other sheet'], 'sheet': 'Compounds',
                           'source_sha256': 'sourcehash', 'suggested_smiles_column': 1,
                           'suggested_name_column': 0}}
        panel.set_library(draft)
        self.assertEqual(panel.smiles_column.currentData(), 1)
        self.assertEqual(panel.name_column.currentData(), 0)
        self.assertEqual(panel.smiles_column.count(), 4)
        self.assertEqual(panel.name_column.count(), 4)
        self.assertTrue(panel.review.isHidden())
        self.assertEqual(panel.selection()['record_ids'], [])
        approvals = []
        panel.columnsApprovalRequested.connect(approvals.append)
        panel.approve_columns.click()
        self.assertEqual(approvals, [{'source_sha256': 'sourcehash', 'sheet': 'Compounds',
                                     'smiles_column': 1, 'name_column': 0}])
        # Clicking asks the host to approve/read; it never approves locally.
        self.assertFalse(panel.library['mapping_approved'])
        approved = {**draft, 'mapping_approved': True, 'fingerprint': 'approved',
                    'records': self._library(2)['records'], 'column_mapping': approvals[0]}
        panel.set_library(approved)
        panel.set_all(True)
        self.assertEqual(panel.selection()['record_ids'], ['0', '1'])
        self.assertIn('column_mapping', panel.selection())
        panel.smiles_column.setCurrentIndex(panel.smiles_column.findData(2))
        self.assertEqual(panel.selection()['record_ids'], [])
        self.assertNotIn('column_mapping', panel.selection())
        self.assertTrue(panel.review.isHidden())
        self.assertTrue(panel.approve_columns.isEnabled())
        self.assertIn('approval required', panel.summary.text())
        sheets = []
        panel.sheetRequested.connect(sheets.append)
        panel.sheet_combo.setCurrentText('Other sheet')
        self.assertEqual(sheets, ['Other sheet'])
        panel.clear()
        self.assertTrue(panel.mapping_box.isHidden())
        panel.close()

    def _library(self, count):
        return {'fingerprint': 'large', 'records': [
            {'record_id': str(i), 'name': f'Compound {i}', 'source': '/tmp/large.sdf',
             'source_record': i + 1, 'formula': 'C2H6O', 'formal_charge': 0,
             'valid': i != 72, 'error': 'Invalid chemistry' if i == 72 else ''}
            for i in range(count)]}

    def test_pagination_retains_global_selection_and_does_not_emit_selection_on_page_changes(self):
        panel = LigandLibraryPanel()
        panel.set_library(self._library(123))
        self.assertEqual(panel.table.rowCount(), 50)
        self.assertEqual(panel.page_total.text(), 'of 3')
        panel.table.item(3, 0).setCheckState(QtCore.Qt.CheckState.Checked)
        changed = []
        panel.selectionChanged.connect(lambda: changed.append(True))
        panel.next_button.click()
        self.assertEqual(changed, [])
        self.assertEqual(panel.table.verticalHeaderItem(0).text(), '51')
        panel.table.item(1, 0).setCheckState(QtCore.Qt.CheckState.Checked)
        panel.next_button.click()
        self.assertEqual(panel.table.rowCount(), 23)
        panel.table.item(22, 0).setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertEqual(panel.selection()['record_ids'], ['3', '51', '122'])
        panel.page_number.setValue(1)
        self.assertEqual(panel.table.item(3, 0).checkState(), QtCore.Qt.CheckState.Checked)
        panel.page_size.setCurrentIndex(0)
        self.assertEqual(panel.table.rowCount(), 25)
        self.assertEqual(panel.selection()['record_ids'], ['3', '51', '122'])
        panel.set_all(True)
        self.assertEqual(len(panel.selection()['record_ids']), 122)
        panel.set_page(2)
        self.assertEqual(panel.table.item(22, 0).flags(), QtCore.Qt.ItemFlag.NoItemFlags)
        panel.set_all(False)
        self.assertEqual(panel.selection()['record_ids'], [])
        panel.close()

    def test_ten_thousand_records_create_only_one_page_of_widgets(self):
        panel = LigandLibraryPanel()
        panel.set_library(self._library(10000))
        self.assertEqual(panel.table.rowCount(), 50)
        self.assertEqual(panel.page_number.maximum(), 200)
        panel.set_page(199)
        self.assertEqual(panel.table.rowCount(), 50)
        self.assertEqual(panel.table.verticalHeaderItem(49).text(), '10000')
        self.assertFalse(panel.next_button.isEnabled())
        panel.close()

    def test_preview_text_and_different_image_sizes_do_not_change_layout_hints(self):
        from docking_universal.gui.qt import QtGui
        from PyQt6.QtTest import QTest
        panel = LigandLibraryPanel()
        panel.set_library(self._library(60))
        panel.resize(1000, 500)
        panel.show()
        QTest.qWait(30)
        original = (panel.preview.sizeHint(), panel.preview.minimumSizeHint(), panel.size())
        for content in ('Loading…', 'Error ' * 500, QtGui.QPixmap(100, 1500), QtGui.QPixmap(1600, 100)):
            if isinstance(content, str):
                panel.preview.setText(content)
            else:
                panel.preview.setPixmap(content)
            QTest.qWait(20)
            self.assertEqual((panel.preview.sizeHint(), panel.preview.minimumSizeHint(), panel.size()), original)
        panel.table.horizontalScrollBar().setValue(90)
        before = panel.table.horizontalScrollBar().value()
        index = panel.table.model().index(1, 1)
        self.assertTrue(panel.table.visualRect(index).intersects(panel.table.viewport().rect()))
        panel.table.scrollTo(index)
        self.assertEqual(panel.table.horizontalScrollBar().value(), before)
        panel.close()
