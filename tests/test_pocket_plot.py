import os
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docking_universal.gui.pocket_plot import PocketScorePlot
from docking_universal.gui.pocket_evidence import PocketEvidencePanel, conformation_summary
from docking_universal.gui.qt import QtCore, QtGui, QtWidgets
from PyQt6.QtTest import QTest


class PocketPlotTests(unittest.TestCase):
    def test_fragment_evidence_has_its_own_optional_display(self):
        from unittest.mock import patch
        observation = {'entry': '1ABC', 'ligand': 'FRG', 'evidence_class': 'same_protein',
                       'source_ligand_id': '1ABC/FRG/A/1'}
        candidate = {'id': 'P1', 'evidence': {'score': 1, 'experimental_ligand_evidence': {
            'observation_count': 1, 'observations': [observation]}}}
        panel = PocketEvidencePanel()
        plot = PocketScorePlot()
        self.addCleanup(panel.close)
        self.addCleanup(plot.close)
        state = SimpleNamespace(workflow_data={})
        with patch('docking_universal.services.molecule_inspection.ligand_display_role', return_value='fragment_screening'):
            panel.set_candidate(candidate)
            self.assertEqual(panel.table.rowCount(), 0)
            self.assertIn('(1)', panel.fragment_toggle.text())
            plot.set_study(state, [candidate])
            self.assertNotIn('P1', plot.experimental_sites)
            panel.fragment_toggle.setChecked(True)
            plot.include_fragment_screening = True
            plot.set_study(state, [candidate])
            self.assertEqual(panel.table.rowCount(), 1)
            self.assertIn('fragment', panel.table.item(0, 0).text())
            self.assertIn('P1', plot.experimental_sites)
    def test_outside_group_observations_are_not_in_box_evidence_table(self):
        panel = PocketEvidencePanel()
        self.addCleanup(panel.close)
        candidate = {'id': 'P5', 'evidence': {
            'experimental_ligand_evidence': {'observation_count': 1, 'observations': [
                {'entry': '5CYM', 'ligand': 'PYZ', 'aligned_ligand_pdb': '/tmp/inside.pdb'}]},
            'grouping_ligand_evidence': {'observations': [
                {'entry': '8FFX', 'ligand': 'XU9', 'aligned_ligand_pdb': '/tmp/outside.pdb',
                 'evidence_role': 'shared_grouping_ligand_outside_box'}]}}}
        panel.set_candidate(candidate)
        self.assertEqual(panel.table.rowCount(), 1)
        self.assertEqual(panel.table.item(0, 1).text(), '5CYM')
        self.assertNotIn('outside', panel.heading.text())
    def test_compact_graph_moves_the_entire_key_below_at_narrow_widths(self):
        plot = PocketScorePlot(top_count=5)
        self.addCleanup(plot.close)
        candidates = [{'id': f'P{i}', 'evidence': {'score': 10 - i}} for i in range(1, 6)]
        plot.set_study(SimpleNamespace(workflow_data={}), candidates)
        plot.resize(360, 400)
        plot.show()
        QtWidgets.QApplication.processEvents()
        self.assertEqual(plot.minimumWidth(), 0)
        self.assertTrue(plot._legend_below())
        self.assertGreaterEqual(plot.height(), 250 + 22 * 5)
        self.assertLessEqual(plot.positions()[-1].x() + 13, plot.width())
        plot.resize(700, 400)
        QtWidgets.QApplication.processEvents()
        self.assertFalse(plot._legend_below())
        self.assertEqual(plot.height(), 235)

    def test_other_input_ligands_are_optional_in_panel_and_graph(self):
        candidate = {'id': 'P5', 'evidence': {'score': 2, 'input_ligand_evidence': {
            'status': 'verified', 'observation_count': 0, 'observations': [],
            'additional_observations': [{'ligand': 'V06 A:609', 'evidence_class': 'input_structure',
                                         'source_ligand_id': 'input/V06/A/609'}]}}}
        panel = PocketEvidencePanel()
        self.addCleanup(panel.close)
        panel.set_candidate(candidate)
        self.assertEqual(panel.table.rowCount(), 0)
        panel.additional_input_toggle.setChecked(True)
        self.assertEqual(panel.table.rowCount(), 1)
        plot = PocketScorePlot()
        self.addCleanup(plot.close)
        state = SimpleNamespace(workflow_data={})
        plot.set_study(state, [candidate])
        self.assertNotIn('P5', plot.experimental_sites)
        plot.include_additional_input_ligands = True
        plot.set_study(state, [candidate])
        self.assertIn('P5', plot.experimental_sites)
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_colors_follow_pocket_identity_after_merge_and_reordering(self):
        from docking_universal.pocket_metadata import POCKET_COLORS
        from docking_universal.gui.study_viewer import candidate_pocket_color
        merged = {'id': 'B1', 'rank': 1, 'evidence': {'score': 35.82, 'site_group': {'members': [
            {'id': 'P11', 'pocket_prediction': {'score': 1.7}},
            {'id': 'P2', 'pocket_prediction': {'score': 35.82}},
            {'id': 'B1'}], 'member_ids': ['P2', 'P11', 'B1'], 'representative_id': 'B1'}}}
        candidates = [merged, {'id': 'P1', 'rank': 7, 'evidence': {'score': 48.48}},
                      {'id': 'B2', 'rank': 2, 'evidence': {}}]
        plot = PocketScorePlot(); plot.set_study(SimpleNamespace(workflow_data={}), candidates)
        colors = {identity: color for identity, _, color in plot.points}
        self.assertEqual(colors['P1'], POCKET_COLORS[0])
        self.assertEqual(colors['B1'], POCKET_COLORS[1])
        self.assertEqual(plot.display_labels['B1'], 'P2')
        self.assertEqual(colors['B2'], '#66727d')
        self.assertEqual(candidate_pocket_color(merged), 'du_report_pocket_2')
        self.assertEqual(candidate_pocket_color(candidates[2]), 'du_report_unscored')
        plot.close()

    def test_merged_ligand_ring_requires_verified_retained_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            ligand = Path(temporary) / 'ligand.pdb'; ligand.write_text('HETATM\n')
            group = {'representative_id': 'B1', 'member_ids': ['P2', 'B1'],
                     'members': [{'id': 'P2', 'pocket_prediction': {'score': 3}}, {'id': 'B1'}],
                     'ligands': [{'path': str(ligand), 'sha256': hashlib.sha256(ligand.read_bytes()).hexdigest(),
                                  'observation': {'source_ligand_id': 'input/ID8/B/602', 'ligand': 'ID8'}}]}
            candidate = {'id': 'B1', 'evidence': {'site_group': group}}
            plot = PocketScorePlot(); state = SimpleNamespace(workflow_data={})
            plot.set_study(state, [candidate]); self.assertEqual(plot.evidence_counts['B1'], 1)
            ligand.write_text('changed')
            plot.set_study(state, [candidate]); self.assertEqual(plot.evidence_counts['B1'], 0)
            plot.close()

    def test_local_ligand_marks_both_predicted_and_bound_sites_on_reopening(self):
        from docking_universal.services.pocket_review import candidate_with_input_ligand_evidence
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ligand = root / 'GNP.pdb'
            ligand.write_text('HETATM    1  C1  GNP A 200       0.000   0.000   0.000  1.00 20.00           C\n'
                              'HETATM    2  C2  GNP A 200       1.000   0.000   0.000  1.00 20.00           C\n')
            def artifact(identity, kind, path):
                return SimpleNamespace(id=identity, kind=kind, path=str(path),
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            assets = [artifact('input-bound-ligand', 'bound_ligand', ligand)]
            candidates = []
            for identity, center, score in [('P1', .54, 11.8), ('B1', 0., None), ('P2', 50., 3.2)]:
                box = root / (identity + '.conf')
                box.write_text(f'center_x = {center}\ncenter_y = 0\ncenter_z = 0\n'
                               'size_x = 26\nsize_y = 26\nsize_z = 26\n')
                assets.append(artifact(identity, 'docking_box', box))
                candidates.append({'id': identity, 'box_artifact_id': identity,
                    'evidence': {'score': score, 'experimental_ligand_evidence': {'observation_count': 0}}})
            state = SimpleNamespace(artifacts=assets, workflow_data={'pocket_candidates': candidates})
            before = copy.deepcopy(candidates)
            plot = PocketScorePlot(); plot.resize(500, 270); plot.set_study(state)
            self.assertEqual(plot.evidence_counts, {'P1': 1, 'B1': 1, 'P2': 0})
            self.assertEqual([p[:2] for p in plot.points], [('P1', 11.8), ('P2', 3.2), ('B1', None)])
            # Verify actual rendered ring pixels, including the unscored point.
            pixmap = plot.grab().toImage()
            for point in (plot.positions()[0], plot.positions()[2]):
                x, y = int(point.x()), int(point.y())
                self.assertTrue(any(pixmap.pixelColor(x+dx, y+dy).name() == '#009e43'
                    for dx in range(-15,16) for dy in range(-15,16)))
            panel = PocketEvidencePanel()
            for candidate in candidates[:2]:
                panel.set_candidate(candidate_with_input_ligand_evidence(state, candidate))
                self.assertIn('1 input ligand', panel.heading.text())
                self.assertIn('0 related observations', panel.heading.text())
                self.assertEqual(panel.table.item(0, 0).text(), 'input structure')
                self.assertEqual(panel.table.item(0, 2).text(), 'GNP A:200')
                panel.table.selectRow(0)
                self.assertFalse(panel.render_2d_button.isEnabled())
                self.assertIn('could not be verified', panel.render_2d_button.toolTip())
                from docking_universal.gui.desktop import StudyWindow
                summary, _ = StudyWindow._candidate_evidence_digest(candidate, candidate_with_input_ligand_evidence(state, candidate)['evidence'])
                self.assertIn('Input ligand: GNP A:200', summary)
                self.assertIn('Ligand edge:', summary)
            edge = root / 'edge.conf'
            edge.write_text('center_x = 0\ncenter_y = 0\ncenter_z = 0\n'
                            'size_x = 2.02\nsize_y = 26\nsize_z = 26\n')
            assets.append(artifact('edge', 'docking_box', edge))
            edge_candidate = {'id': 'P3', 'box_artifact_id': 'edge', 'evidence': {}}
            edge_evidence = candidate_with_input_ligand_evidence(state, edge_candidate)['evidence']
            summary, _ = StudyWindow._candidate_evidence_digest(edge_candidate, edge_evidence)
            self.assertIn('Ligand edge: 0.01 Å', summary)
            outside = root / 'outside.conf'
            outside.write_text(edge.read_text().replace('size_x = 2.02', 'size_x = 1.8'))
            assets.append(artifact('outside', 'docking_box', outside))
            outside_candidate = {'id': 'P4', 'box_artifact_id': 'outside', 'evidence': {}}
            outside_evidence = candidate_with_input_ligand_evidence(state, outside_candidate)['evidence']
            summary, _ = StudyWindow._candidate_evidence_digest(outside_candidate, outside_evidence)
            self.assertIn('Ligand extends 0.10 Å outside box', summary)
            self.assertEqual(candidates, before)
            # Related observations remain separate and still count.
            candidates[0]['evidence']['experimental_ligand_evidence']['observation_count'] = 3
            plot.set_study(state)
            self.assertEqual(plot.evidence_counts['P1'], 4)
            self.assertIn('3 possible related-PDB', plot.evidence_sources['P1'])
            ligand.write_text(ligand.read_text() + 'REMARK changed\n')
            plot.set_study(state)
            self.assertEqual(plot.evidence_counts['B1'], 0)
            self.assertEqual(plot.evidence_counts['P1'], 3)
            panel.close(); plot.close()

    def test_preparation_failures_follow_selected_box_not_a_global_clearance(self):
        panel = PocketEvidencePanel()
        panel.set_candidate({'id': 'B1', 'evidence': {'receptor_preparation_review': {
            'warning': 'Receptor preparation failed. No residues were omitted.',
            'residues': [{'residue': 'GLU', 'chain': 'A', 'number': '75',
                          'inside_box': False, 'minimum_distance_to_box_angstrom': 4.4}]}}})
        self.assertIn('GLU A:75', panel.preparation_issues.toPlainText())
        self.assertIn('4.40 Å from this box', panel.preparation_issues.toPlainText())
        height = panel.preparation_issues.height()
        panel.set_candidate({'id': 'B2', 'evidence': {'receptor_preparation_review': {
            'warning': 'Receptor preparation failed.',
            'residues': [{'residue': 'GLU', 'chain': 'A', 'number': '75',
                          'inside_box': True, 'minimum_distance_to_box_angstrom': 0}]}}})
        self.assertIn('inside this box', panel.preparation_issues.toPlainText())
        self.assertEqual(panel.preparation_issues.height(), height)
        panel.set_candidate({'id': 'P1', 'evidence': {}})
        self.assertTrue(panel.preparation_issues.isHidden())
        self.assertEqual(panel.preparation_issues.toPlainText(), '')

    def test_removed_cofactor_in_box_is_explicit_and_other_changes_are_not_called_removed(self):
        panel = PocketEvidencePanel()
        panel.set_candidate({'id': 'B1', 'evidence': {'receptor_model_review': {
            'warning': 'Reviewed receptor changes.',
            'residues': [
                {'residue': 'COH', 'chain': 'B', 'number': '603', 'removed': True,
                 'inside_box': True, 'minimum_distance_to_box_angstrom': 0},
                {'residue': 'HIS', 'chain': 'B', 'number': '10', 'removed': False,
                 'inside_box': False, 'minimum_distance_to_box_angstrom': 5}]}}})
        text = panel.preparation_issues.toPlainText()
        self.assertEqual(text, 'Removed from receptor: COH B:603 (inside this box). Docking excludes them.')
        self.assertIn('originally inside this docking box', panel._preparation_detail_text)
        self.assertIn('Docking will not include interactions with them', panel._preparation_detail_text)
        self.assertNotIn('Removed HIS', panel._preparation_detail_text)
        self.assertFalse(panel.preparation_details_button.isHidden())
        self.assertIn('#fff1e8', panel.preparation_issues.styleSheet())
        panel.set_candidate({'id': 'P1', 'evidence': {}})
        self.assertEqual(panel.preparation_issues.styleSheet(), '')

    def test_supporting_components_are_not_counted_as_ligand_evidence_but_remain_viewable(self):
        rows = [{'ligand': code, 'entry': '5ABC', 'evidence_class': 'same_protein',
                 'aligned_ligand_pdb': code + '.pdb'} for code in ('NAG', 'MAN', 'BOG', 'COH', 'ID8')]
        candidate = {'id': 'L1', 'evidence': {'experimental_ligand_evidence': {
            'observation_count': 5, 'observations': rows}}}
        plot = PocketScorePlot(top_count=0, include_experimental=False)
        plot.set_study(SimpleNamespace(workflow_data={'pocket_candidates': []}), candidates=[candidate])
        self.assertEqual(plot.evidence_counts['L1'], 1)
        self.assertEqual(plot.supporting_counts['L1'], 4)
        self.assertIn('L1', plot.experimental_sites)
        supporting_only = {'id': 'L2', 'evidence': {'experimental_ligand_evidence': {
            'observation_count': 4, 'observations': rows[:4]}}}
        plot.set_study(SimpleNamespace(workflow_data={'pocket_candidates': []}), candidates=[supporting_only])
        self.assertEqual(plot.evidence_counts['L2'], 0)
        self.assertNotIn('L2', plot.experimental_sites)
        panel = PocketEvidencePanel()
        panel.set_candidate(candidate)
        self.assertEqual(panel.table.rowCount(), 1)
        self.assertEqual(panel.table.item(0, 2).text(), 'ID8')
        self.assertIn('(4)', panel.supporting_toggle.text())
        panel.supporting_toggle.setChecked(True)
        self.assertEqual(panel.table.rowCount(), 5)
        self.assertEqual(panel.table.item(1, 0).text(), 'supporting component')
        panel.close()

    def test_legacy_cofactor_clashes_are_not_presented_as_ligand_obstruction(self):
        from docking_universal.services.molecule_inspection import possible_ligand_conformation
        original = {'status': 'conformationally_incompatible', 'box_decision_warning': 'Clash',
            'observations': [{'residue': {'name': 'HIS', 'chain': 'A', 'number': '10'},
                'ligands': [{'source_ligand_id': '5ABC/COH/A/602',
                             'consistent_with_side_chain_occlusion': True}]}]}
        projected = possible_ligand_conformation(original)
        self.assertEqual(projected['status'], 'not_evaluated')
        self.assertIsNone(projected['box_decision_warning'])
        self.assertEqual(original['status'], 'conformationally_incompatible')
        original['observations'][0]['ligands'].append({'source_ligand_id': '5ABC/ID8/A/1',
                                                       'consistent_with_side_chain_occlusion': True})
        self.assertEqual(possible_ligand_conformation(original)['status'], 'conformationally_incompatible')

    def test_removed_component_graph_marker_is_distinct_clickable_and_explained(self):
        plot = PocketScorePlot()
        candidate = {'id': 'B1', 'evidence': {'score': 3.2,
            'conformational_site_evidence': {'status': 'conformationally_incompatible',
                'occluding_residues': [{'name': 'ASP', 'number': '30', 'chain': 'A'}]},
            'receptor_model_review': {'residues': [
                {'residue': 'COH', 'chain': 'B', 'number': '603', 'removed': True, 'inside_box': True},
                {'residue': 'NAG', 'chain': 'A', 'number': '1', 'removed': True, 'inside_box': False}]}}}
        plot.set_study(SimpleNamespace(workflow_data={'pocket_candidates': []}), candidates=[candidate])
        plot.resize(500, 270)
        plot.show()
        self.app.processEvents()
        self.assertEqual(plot.removed_components, {'B1': ['COH B:603']})
        self.assertIn('B1', plot.conflicts)
        center = plot.positions()[0]
        removal = plot.removed_component_marker_rect(center).center().toPoint()
        obstruction = plot.obstruction_marker_rect(center).center().toPoint()
        self.assertNotEqual(removal, obstruction)
        self.assertEqual(removal.x(), obstruction.x())
        self.assertFalse(plot.removed_component_marker_rect(center).intersects(plot.obstruction_marker_rect(center)))
        selected = []
        plot.candidateActivated.connect(selected.append)
        QTest.mouseMove(plot, removal)
        self.assertIn('COH B:603', plot.toolTip())
        self.assertIn('Docking will not include interactions', plot.toolTip())
        QTest.mouseClick(plot, QtCore.Qt.MouseButton.LeftButton, pos=removal)
        QTest.mouseClick(plot, QtCore.Qt.MouseButton.LeftButton, pos=obstruction)
        self.assertEqual(selected, ['B1', 'B1'])
        plot.close()

    def test_successful_model_override_keeps_its_warning_when_a_box_is_reopened(self):
        panel = PocketEvidencePanel()
        panel.set_candidate({'id': 'B1', 'evidence': {
            'receptor_preparation_review': {'warning': 'Old failed preparation'},
            'receptor_model_review': {'status': 'prepared_with_reviewed_model_changes',
                'warning': 'User-approved receptor changes: NAG A:1 excluded.',
                'residues': [{'residue': 'NAG', 'chain': 'A', 'number': '1',
                              'minimum_distance_to_box_angstrom': 13.44, 'inside_box': False}]}}})
        self.assertIn('NAG A:1 excluded', panel._preparation_detail_text)
        self.assertIn('13.44 Å', panel._preparation_detail_text)
        self.assertNotIn('Old failed', panel.preparation_issues.toPlainText())
        self.assertFalse(panel.preparation_issues.isHidden())

    def test_obstruction_statuses_do_not_claim_absence_of_rotamer_changes(self):
        cases = [
            ({"status": "not_evaluated"}, "Ligand obstruction not evaluated", "No matched"),
            ({"status": "reviewed_no_geometric_incompatibility"},
             "No ligand obstruction found", "may still differ"),
            ({"status": "conformationally_incompatible", "occluding_residues": [
                {"name": "ASP", "number": "30", "chain": "A"}]},
             "Possible ligand obstruction: ASP30A", "not proof"),
        ]
        panel = PocketEvidencePanel()
        for evidence, expected, qualification in cases:
            with self.subTest(status=evidence["status"]):
                summary, explanation = conformation_summary(evidence)
                self.assertEqual(summary, expected)
                self.assertIn(qualification, explanation)
                panel.set_candidate({"id": "P1", "evidence": {
                    "conformational_site_evidence": evidence}})
                self.assertIn(expected, panel.warning.text())
                self.assertIn(qualification, panel.warning.toolTip())

    def test_ligand_evidence_header_explains_graph_symbol_in_shared_panel(self):
        panel = PocketEvidencePanel()
        self.assertEqual(panel.evidence_title.text(), "Ligand evidence")
        self.assertTrue(panel.evidence_title.font().bold())
        self.assertFalse(panel.evidence_symbol.pixmap().isNull())
        self.assertIn("green ring", panel.evidence_header.toolTip())
        self.assertIn("not newly docked poses", panel.evidence_header.toolTip())
        self.assertIn("border:1px solid #009e43", panel.evidence_summary.styleSheet())
        before = (panel.evidence_summary.height(), panel.heading.height())
        for candidate in ({"id": "P1", "evidence": {"experimental_ligand_evidence": {
                "observation_count": 17, "pdb_entry_count": 15}}}, {"id": "P2", "evidence": {}}):
            panel.set_candidate(candidate)
            self.assertEqual((panel.evidence_summary.height(), panel.heading.height()), before)
            self.assertEqual(panel.evidence_summary.layout().indexOf(panel.evidence_header) + 1,
                             panel.evidence_summary.layout().indexOf(panel.heading))
        self.assertEqual(panel.content_layout.indexOf(panel.evidence_summary) + 1,
                         panel.content_layout.indexOf(panel.table))
        self.assertLess(panel.content_layout.indexOf(panel.warning),
                        panel.content_layout.indexOf(panel.evidence_summary))
        self.assertEqual(panel.warning.height(), panel.warning.fontMetrics().lineSpacing() * 3 + 16)

    def test_retained_scores_map_by_identity_not_row_order(self):
        with tempfile.TemporaryDirectory() as directory:
            cavity = Path(directory) / "cavity"
            cavity.mkdir()
            (cavity / "pocket_selection_diagnostics.tsv").write_text(
                "pocket_file\tscore\n"
                "pocket2_atm.pdb\t1.8\n"
                "pocket1_atm.pdb\t2.49\n"
            )
            (cavity / "selected_pocket_records.txt").write_text(
                "2.49|frozen_pockets/pocket1_atm.pdb|0|0|0|2.49\n"
                "1.8|frozen_pockets/pocket2_atm.pdb|0|0|0|1.8\n"
                "1.11|frozen_pockets/pocket4_atm.pdb|0|0|0|1.11\n"
            )
            plot = PocketScorePlot()
            plot.set_study(SimpleNamespace(workflow_data={
                "preparation_root": directory,
                "pocket_candidates": [
                    {"id": "P1", "evidence": {"detector": "p2rank"}},
                    {"id": "P2", "evidence": {"detector": "p2rank"}},
                    {"id": "P4", "evidence": {"detector": "p2rank"}},
                ],
            }))
            self.assertEqual([(p[0], p[1]) for p in plot.points], [("P1", 2.49), ("P2", 1.8), ("P4", 1.11)])
            self.assertEqual(plot.detector, "P2Rank")
            self.assertEqual(plot.detector, "P2Rank")
            selected = []
            plot.candidateActivated.connect(selected.append)
            plot.resize(320, 220)
            plot.show()
            self.app.processEvents()
            center = plot.positions()[1]
            QTest.mouseClick(plot, QtCore.Qt.MouseButton.LeftButton, pos=center.toPoint())
            QTest.mouseClick(plot, QtCore.Qt.MouseButton.LeftButton,
                             pos=QtCore.QPoint(int(center.x()), 204))
            self.assertEqual(selected, ["P2", "P2"])
            plot.close()

    def test_warning_key_matches_emphasized_explanation_and_is_clickable(self):
        conformation = {"status": "conformationally_incompatible", "occluding_residues": [
            {"name": "ASP", "number": "30", "chain": "A"}]}
        panel = PocketEvidencePanel()
        panel.set_candidate({"id": "P1", "evidence": {"conformational_site_evidence": conformation}})
        self.assertTrue(panel.warning.text().startswith("!  Possible ligand obstruction: ASP30A\n"))
        first = panel.warning.document().firstBlock().begin().fragment().charFormat()
        self.assertEqual(first.fontWeight(), QtGui.QFont.Weight.Bold)
        self.assertGreater(first.fontPointSize(), panel.warning.font().pointSizeF())
        self.assertEqual(first.foreground().color().name(), "#a85b00")
        self.assertIn("border:1px solid #a85b00", panel.warning.styleSheet())
        panel.warning.set_conformation_text(conformation, compact=True)
        self.assertEqual(panel.warning.text(), "!  Possible ligand obstruction: ASP30A")
        self.assertIn("not proof of flexibility", panel.warning.toolTip())
        self.assertIn("not all protein or ligand rotamer changes", panel.warning.toolTip())
        plot = PocketScorePlot()
        plot.set_study(SimpleNamespace(workflow_data={"pocket_candidates": [
            {"id": "P1", "evidence": {"score": 2.49, "conformational_site_evidence": conformation}},
        ]}))
        selected = []
        plot.candidateActivated.connect(selected.append)
        center = plot.obstruction_marker_rect(plot.positions()[0]).center().toPoint()
        QTest.mouseClick(plot, QtCore.Qt.MouseButton.LeftButton, pos=center)
        self.assertEqual(selected, ["P1"])
        panel.set_candidate({"id": "P2", "evidence": {}})
        self.assertFalse(panel.warning.text().startswith("!"))
        self.assertNotEqual(panel.warning.document().firstBlock().begin().fragment().charFormat().fontWeight(),
                            QtGui.QFont.Weight.Bold)

    def test_unscored_and_nonfinite_candidates_are_not_misrepresented(self):
        plot = PocketScorePlot()
        plot.set_study(SimpleNamespace(workflow_data={"pocket_candidates": [
            {"id": "L1", "evidence": {}},
            {"id": "P2", "evidence": {"score": float("nan")}},
        ]}))
        self.assertEqual([(p[0], p[1]) for p in plot.points], [("L1", None), ("P2", None)])
        self.assertFalse(plot.isHidden())

    def test_grouped_predictions_use_highest_ranked_source_with_explicit_identity(self):
        plot = PocketScorePlot()
        group = {'representative_id': 'B1', 'member_ids': ['P2', 'P11', 'B1'], 'members': [
            {'id': 'P11', 'rank': 11, 'pocket_prediction': {'detector': 'p2rank', 'score': 1.7}},
            {'id': 'P2', 'rank': 2, 'pocket_prediction': {'detector': 'p2rank', 'score': 35.82}},
            {'id': 'B1', 'rank': 25}]}
        plot.set_study(SimpleNamespace(workflow_data={'pocket_candidates': [
            {'id': 'B1', 'evidence': {'site_group': group}}]}))
        self.assertEqual([(p[0], p[1]) for p in plot.points], [('B1', 35.82)])
        self.assertEqual(plot.score_sources, {'B1': 'P2'})
        self.assertIn('P11', plot.evidence_sources['B1'])

    def test_selected_input_ligand_marker_survives_grouping_and_full_graph(self):
        plot = PocketScorePlot(top_count=1)
        group = {'representative_id': 'B1', 'member_ids': ['P2', 'B1'], 'members': []}
        verified = {'status': 'verified', 'all_heavy_atoms_inside': True,
                    'observation_count': 1, 'observations': [
                        {'ligand': 'ID8 B:602', 'source': 'input_structure'}]}
        candidates = [
            {'id': 'P1', 'evidence': {'score': 50, 'experimental_ligand_evidence': {
                'observation_count': 1, 'observations': [{'ligand': 'ID8'}]}}},
            {'id': 'B1', 'evidence': {'score': 20, 'site_group': group,
                                      'input_ligand_evidence': verified}},
            {'id': 'P3', 'evidence': {'input_ligand_evidence': {
                'status': 'unverified', 'observation_count': 1}}},
        ]
        plot.set_study(SimpleNamespace(workflow_data={'pocket_candidates': candidates}), candidates=candidates)
        self.assertEqual(plot.input_ligand_sites, {'B1'})
        self.assertIn('B1', [point[0] for point in plot.points])
        full = PocketScorePlot()
        full.copy_presentation_from(plot)
        self.assertEqual(full.input_ligand_sites, {'B1'})
        self.assertFalse(full.grab().isNull())

    def test_score_order_precedes_unscored_evidence_without_changing_identity(self):
        plot = PocketScorePlot()
        candidates = [{'id': 'L1', 'evidence': {'kind': 'ligand_defined'}},
                      {'id': 'P9', 'evidence': {'detector': 'p2rank', 'score': 1.7}},
                      {'id': 'P2', 'evidence': {'detector': 'p2rank', 'score': 35.82}},
                      {'id': 'B1', 'evidence': {'kind': 'ligand_defined'}}]
        plot.set_study(SimpleNamespace(workflow_data={'pocket_candidates': candidates}))
        self.assertEqual([p[0] for p in plot.points], ['P2', 'P9', 'L1', 'B1'])
        self.assertEqual([row['id'] for row in candidates], ['L1', 'P9', 'P2', 'B1'])

    def test_compact_graph_keeps_top_five_all_ligand_evidence_and_selected_site(self):
        candidates = [{'id': f'P{i}', 'evidence': {'score': 11 - i}} for i in range(1, 11)]
        candidates[7]['evidence']['experimental_ligand_evidence'] = {'observation_count': 1}
        candidates[6]['evidence']['conformational_site_evidence'] = {'observation_count': 1}
        candidates.append({'id': 'B1', 'evidence': {'input_ligand_evidence': {'observation_count': 1}}})
        plot = PocketScorePlot(top_count=5)
        plot.set_study(SimpleNamespace(workflow_data={'pocket_candidates': candidates}))
        self.assertEqual([p[0] for p in plot.points], ['P1', 'P2', 'P3', 'P4', 'P5', 'P7', 'P8', 'B1'])
        self.assertEqual(len(plot.all_points), 11)
        plot.set_selected('P9')
        self.assertEqual([p[0] for p in plot.points], ['P1', 'P2', 'P3', 'P4', 'P5', 'P7', 'P8', 'P9', 'B1'])
        full = PocketScorePlot()
        full.copy_presentation_from(plot)
        self.assertEqual(len(full.points), 11)
        self.assertEqual(full.selected, 'P9')
        plot.set_selected(None)
        self.assertNotIn('P9', [p[0] for p in plot.points])

    def test_retained_box_number_preserves_original_detector_rank(self):
        with tempfile.TemporaryDirectory() as directory:
            cavity = Path(directory) / "cavity"
            cavity.mkdir()
            (cavity / "selected_pocket_records.txt").write_text(
                "2.49|pocket1_atm.pdb|0|0|0|2.49\n"
                "1.8|pocket2_atm.pdb|0|0|0|1.8\n"
                "1.11|pocket4_atm.pdb|0|0|0|1.11\n"
            )
            plot = PocketScorePlot()
            plot.set_study(SimpleNamespace(workflow_data={
                "preparation_root": directory,
                "pocket_candidates": [{"id": f"P{i}", "evidence": {}}
                                      for i in range(1, 5)],
            }))
            self.assertEqual([(p[0], p[1]) for p in plot.points],
                             [("P1", 2.49), ("P2", 1.8), ("P4", 1.11), ("P3", None)])

    def test_all_candidates_have_clickable_evidence_markers(self):
        plot = PocketScorePlot()
        plot.set_study(SimpleNamespace(workflow_data={"pocket_candidates": [
            {"id": f"P{i}", "evidence": {
                "score": 8 - i,
                "experimental_ligand_evidence": {"observation_count": 4 if i == 5 else 0},
                "conformational_site_evidence": {"box_decision_warning": "Conflict" if i == 5 else ""},
            }} for i in range(1, 8)
        ]}))
        self.assertEqual(len(plot.points), 7)
        self.assertEqual(plot.evidence_counts["P5"], 4)
        self.assertEqual(plot.conflicts, {"P5"})
        selected = []
        plot.candidateActivated.connect(selected.append)
        QTest.mouseClick(plot, QtCore.Qt.MouseButton.LeftButton, pos=plot.positions()[6].toPoint())
        self.assertEqual(selected, ["P7"])
