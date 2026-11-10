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
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

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
            self.assertEqual([p[:2] for p in plot.points], [('P1', 11.8), ('B1', None), ('P2', 3.2)])
            # Verify actual rendered ring pixels, including the unscored point.
            pixmap = plot.grab().toImage()
            for point in plot.positions()[:2]:
                x, y = int(point.x()), int(point.y())
                self.assertTrue(any(pixmap.pixelColor(x+dx, y+dy).name() == '#009b50'
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
                self.assertIn('molecule inspector', panel.render_2d_button.toolTip())
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
            self.assertIn('3 related-PDB', plot.evidence_sources['P1'])
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

    def test_successful_model_override_keeps_its_warning_when_a_box_is_reopened(self):
        panel = PocketEvidencePanel()
        panel.set_candidate({'id': 'B1', 'evidence': {
            'receptor_preparation_review': {'warning': 'Old failed preparation'},
            'receptor_model_review': {'status': 'prepared_with_reviewed_model_changes',
                'warning': 'User-approved receptor changes: NAG A:1 excluded.',
                'residues': [{'residue': 'NAG', 'chain': 'A', 'number': '1',
                              'minimum_distance_to_box_angstrom': 13.44, 'inside_box': False}]}}})
        self.assertIn('NAG A:1 excluded', panel.preparation_issues.toPlainText())
        self.assertIn('13.44 Å', panel.preparation_issues.toPlainText())
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
        self.assertIn("border:1px solid #009b50", panel.evidence_summary.styleSheet())
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
                             pos=QtCore.QPoint(int(center.x()), plot.height() - 50))
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
                             [("P1", 2.49), ("P2", 1.8), ("P3", None), ("P4", 1.11)])

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
