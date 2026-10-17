"""Isolated native screening-help layout check; no host, study or docking job."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'libexec'))
from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.gui.workflow_panels import ScreeningSetupPanel
from PyQt6.QtTest import QTest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QtWidgets.QApplication([])
    window = QtWidgets.QWidget()
    window.setWindowTitle('Isolated screening settings guidance — no docking')
    layout = QtWidgets.QVBoxLayout(window)
    layout.addWidget(QtWidgets.QLabel('5. Screen ligands'))
    panel = ScreeningSetupPanel()
    panel.ligands.setText('/example/library.sdf')
    panel.output.setText('/example/screening-results')
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(panel)
    layout.addWidget(scroll)
    results = {'checks': []}

    def check(name, passed):
        results['checks'].append({'name': name, 'passed': bool(passed)})
        if not passed:
            raise AssertionError(name)

    try:
        for width, height in ((960, 760), (1100, 800), (1440, 900)):
            window.resize(width, height)
            window.show()
            QTest.qWait(150)
            check(f'{width}: no horizontal scrolling', scroll.horizontalScrollBar().maximum() == 0)
            for key, note in panel.inline_explanations.items():
                needed = note.fontMetrics().boundingRect(note.contentsRect(),
                    QtCore.Qt.TextFlag.TextWordWrap, note.text()).height()
                check(f'{width}: {key} text not clipped', needed <= note.height() + 4)
                if key not in ('approval', 'stop_on_error'):
                    field = getattr(panel, key)
                    check(f'{width}: {key} help beside control',
                          note.mapTo(panel, QtCore.QPoint()).x() > field.mapTo(panel, QtCore.QPoint()).x())
            scroll.ensureWidgetVisible(panel.run_button)
            QTest.qWait(50)
            check(f'{width}: launch action reachable', scroll.viewport().rect().contains(
                panel.run_button.mapTo(scroll.viewport(), panel.run_button.rect().center())))
            window.grab().save(str(args.output / f'screening-{width}.png'))
            for mode, expected in (('automatic', 0), ('custom', 12), ('default', None)):
                panel.cpu.setCurrentIndex(panel.cpu.findData(mode))
                panel.cpu_count.setValue(12)
                QTest.qWait(30)
                check(f'{width}: {mode} CPU value', panel.cpu_override() == expected)
                check(f'{width}: {mode} CPU count visibility',
                      panel.cpu_count.isHidden() == (mode != 'custom'))
                check(f'{width}: {mode} no horizontal scrolling', scroll.horizontalScrollBar().maximum() == 0)
            panel.cpu.setCurrentIndex(panel.cpu.findData('custom'))
            scroll.ensureWidgetVisible(panel.cpu_count)
            QTest.qWait(30)
            check(f'{width}: custom count reachable', scroll.viewport().rect().contains(
                panel.cpu_count.mapTo(scroll.viewport(), panel.cpu_count.rect().center())))
            window.grab().save(str(args.output / f'screening-custom-{width}.png'))
            panel.cpu.setCurrentIndex(panel.cpu.findData('default'))
            scroll.verticalScrollBar().setValue(0)
        check('default cutoff remains 1.5 Å', panel.cluster_rmsd.value() == 1.5)
        panel.cluster_rmsd.setValue(2)
        check('custom 2 Å still accepted', panel.cluster_rmsd.value() == 2)
        check('representative count remains three', panel.representatives.value() == 3)
        check('no automatic authorization', not panel.approval.isChecked())
        check('molecule preview hints unchanged', panel.library_panel.preview.sizeHint() == QtCore.QSize(300, 240))
    except Exception as exc:
        results['error'] = str(exc)
    finally:
        window.close()
        (args.output / 'verification.json').write_text(json.dumps(results, indent=2))
    return 1 if results.get('error') else 0


if __name__ == '__main__':
    raise SystemExit(main())
