"""Native warning first-paint/scroll/resize validation; no scientific job runs."""
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libexec"))
from docking_universal.gui.qt import QtCore, QtGui, QtWidgets
from docking_universal.gui.pocket_evidence import PocketEvidencePanel
from docking_universal.gui.pocket_plot import PocketScorePlot
from PyQt6.QtTest import QTest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QtWidgets.QApplication([])
    app.setFont(QtGui.QFont("Arial", 16))
    window = QtWidgets.QWidget()
    window.setWindowTitle("Isolated evidence warning paint validation")
    layout = QtWidgets.QVBoxLayout(window)
    panel = PocketEvidencePanel()
    panel.set_viewer_presentation(embedded=True)
    layout.addWidget(panel)
    candidate = {"id": "P1", "evidence": {
        "detector": "p2rank", "score": 2.49,
        "experimental_ligand_evidence": {"observation_count": 17, "pdb_entry_count": 15,
            "evidence_class_counts": {"exact_sequence_match": 4, "close_structural_homolog": 13}},
        "conformational_site_evidence": {"status": "conformationally_incompatible",
            "occluding_residues": [{"name": "ASP", "number": "30", "chain": "A"}],
            "box_decision_warning": "UI fixture: possible obstruction; not a calculated finding."},
    }}
    panel.set_candidate(candidate)
    graph = PocketScorePlot()
    graph.set_study(SimpleNamespace(workflow_data={"pocket_candidates": [candidate,
        {"id": "P2", "evidence": {"score": 1.8}},
        {"id": "P4", "evidence": {"score": 1.11}}]}))
    graph.selected = "P1"
    graph.resize(650, 270)
    window.resize(430, 650)
    result = {"checks": []}

    def check(name, condition):
        result["checks"].append({"name": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)

    def exercise():
        try:
            panel.guide_button.setFocus()
            QTest.qWait(150)
            first = panel.warning.grab().toImage()
            first.save(str(args.output / "warning-before-scroll.png"))
            graph.grab().save(str(args.output / "obstruction-graph.png"))
            window.grab().save(str(args.output / "evidence-panel.png"))
            check("ligand evidence header is visible", panel.evidence_title.isVisible())
            check("green ring accompanies ligand evidence", not panel.evidence_symbol.pixmap().isNull())
            check("warning repeats graph key", panel.warning.text().startswith("!  Possible ligand obstruction: ASP30A"))
            gutter = panel.warning.verticalScrollBar()
            can_scroll = gutter.maximum() > 0
            original_height = panel.warning.height()
            gutter.setValue(gutter.maximum())
            QTest.qWait(100)
            check("long warning scrolls or concise warning fits", gutter.value() > 0 if can_scroll else gutter.value() == 0)
            gutter.setValue(0)
            QTest.qWait(150)
            second = panel.warning.grab().toImage()
            second.save(str(args.output / "warning-after-scroll.png"))
            check("initial paint matches repaint after scrolling", first == second)
            for width in (360, 650, 430):
                window.resize(width, 650)
                QTest.qWait(100)
                check(f"width {width}: text viewport has stable height", panel.warning.height() == original_height)
                check(f"width {width}: scrollbar gutter stays reserved",
                      panel.warning.verticalScrollBarPolicy() == QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
                graph.resize(width, 270)
                graph.grab().save(str(args.output / f"obstruction-graph-{width}.png"))
            long_warning = dict(candidate["evidence"]["conformational_site_evidence"])
            long_warning["occluding_residues"] = [
                {"name": "ASP", "number": str(number), "chain": "A"} for number in range(30, 50)
            ]  # Layout fixture only; not a calculated residue list.
            panel.warning.set_conformation_text(long_warning)
            QTest.qWait(100)
            check("long residue list scrolls without growing warning", gutter.maximum() > 0
                  and panel.warning.height() == original_height)
            panel.warning.set_conformation_text(candidate["evidence"]["conformational_site_evidence"])
            panel.warning.selectAll()
            check("warning stays selectable", "ASP30A" in panel.warning.textCursor().selectedText())
            result["status"] = "passed"
        except Exception as exc:
            import traceback
            result.update(status="failed", error=str(exc), traceback=traceback.format_exc())
        finally:
            (args.output / "verification.json").write_text(json.dumps(result, indent=2))
            window.close()
            app.exit(0 if result["status"] == "passed" else 1)

    window.show()
    QtCore.QTimer.singleShot(350, exercise)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
