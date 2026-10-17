import os
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
                self.assertIn(qualification, panel.warning.text())

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
        self.assertEqual(panel.warning.height(), panel.warning.fontMetrics().lineSpacing() * 4 + 16)

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
