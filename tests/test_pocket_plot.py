import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docking_universal.gui.pocket_plot import PocketScorePlot
from docking_universal.gui.qt import QtCore, QtWidgets
from PyQt6.QtTest import QTest


class PocketPlotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_retained_scores_map_by_identity_not_row_order(self):
        with tempfile.TemporaryDirectory() as directory:
            cavity = Path(directory) / "cavity"
            cavity.mkdir()
            (cavity / "pocket_selection_diagnostics.tsv").write_text(
                "pocket_file\tscore\n"
                "pocket2_atm.pdb\t1.8\n"
                "pocket1_atm.pdb\t2.49\n"
            )
            plot = PocketScorePlot()
            plot.set_study(SimpleNamespace(workflow_data={
                "preparation_root": directory,
                "pocket_candidates": [
                    {"id": "P1", "evidence": {"detector": "p2rank"}},
                    {"id": "P2", "evidence": {"detector": "p2rank"}},
                    {"id": "L1", "evidence": {}},
                ],
            }))
            self.assertEqual([(p[0], p[1]) for p in plot.points], [("P1", 2.49), ("P2", 1.8)])
            self.assertEqual(plot.detector, "P2Rank")
            selected = []
            plot.candidateActivated.connect(selected.append)
            plot.resize(320, 220)
            plot.show()
            self.app.processEvents()
            center = plot.positions()[1]
            QTest.mouseClick(plot, QtCore.Qt.MouseButton.LeftButton, pos=center.toPoint())
            QTest.mouseClick(plot, QtCore.Qt.MouseButton.LeftButton,
                             pos=QtCore.QPoint(int(center.x()), plot.height() - 30))
            self.assertEqual(selected, ["P2", "P2"])
            plot.close()

    def test_unscored_and_nonfinite_candidates_are_not_misrepresented(self):
        plot = PocketScorePlot()
        plot.set_study(SimpleNamespace(workflow_data={"pocket_candidates": [
            {"id": "L1", "evidence": {}},
            {"id": "P2", "evidence": {"score": float("nan")}},
        ]}))
        self.assertEqual(plot.points, [])
        self.assertTrue(plot.isHidden())

    def test_retained_box_number_is_not_original_detector_rank(self):
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
                             [("P1", 2.49), ("P2", 1.8), ("P3", 1.11)])
