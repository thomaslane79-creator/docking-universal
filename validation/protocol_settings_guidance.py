"""Isolated native layout check; does not open or change a scientific study."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'libexec'))
from docking_universal.gui.qt import QtCore, QtGui, QtWidgets
from docking_universal.gui.workflow_panels import ProtocolFinalizationPanel
from PyQt6.QtTest import QTest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QtWidgets.QApplication([])
    window = QtWidgets.QWidget()
    window.setWindowTitle('Isolated protocol-guidance validation')
    layout = QtWidgets.QVBoxLayout(window)
    heading = QtWidgets.QLabel('4. Finalize protocol')
    layout.addWidget(heading)
    panel = ProtocolFinalizationPanel()
    panel.output_directory.setText('/example/2R8N-protocol')
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(panel)
    layout.addWidget(scroll)
    result = {'checks': []}
    # Exercise presentation even when this isolated process has no GPU runtime
    # configured. No host/worker exists, so this cannot enable scientific use.
    result['experimental_engine_display_fixture'] = panel.engine.findData('adgpu') < 0
    if result['experimental_engine_display_fixture']:
        panel.engine.addItem('AutoDock-GPU (layout fixture)', 'adgpu')
    def check(name, condition):
        result['checks'].append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)
    try:
        for engine in ('vina', 'qvinaw', 'adgpu'):
            panel.engine.setCurrentIndex(panel.engine.findData(engine))
            for width, height in ((960, 760), (1280, 800), (1440, 900)):
                window.resize(width, height)
                window.show()
                QTest.qWait(100)
                prefix = f'{engine}/{width}'
                check(f'{prefix}: no forced horizontal scroll', scroll.horizontalScrollBar().maximum() == 0)
                for key in ('exhaustiveness', 'modes', 'energy_range', 'ad4_runs', 'ad4_heuristic_cap'):
                    expected = (key.startswith('ad4_')) == (engine == 'adgpu')
                    check(f'{prefix}: {key} visibility matches engine',
                          panel.inline_explanations[key].isVisibleTo(window) == expected)
                for key, explanation in panel.inline_explanations.items():
                    # Hidden controls have no meaningful layout geometry.
                    if not explanation.isVisibleTo(window):
                        continue
                    bounds = explanation.contentsRect()
                    needed = explanation.fontMetrics().boundingRect(bounds, QtCore.Qt.TextFlag.TextWordWrap,
                                                                   explanation.text()).height()
                    result.setdefault('text_geometry', []).append({'engine': engine, 'width': width, 'key': key,
                        'actual': [bounds.width(), bounds.height()], 'needed_height': needed})
                    check(f'{prefix}: {key} explanation is fully laid out', needed <= bounds.height() + 4)
                    if key != 'approval':
                        check(f'{prefix}: {key} explanation is beside its control',
                              explanation.mapTo(panel, QtCore.QPoint(0, 0)).x() >
                              getattr(panel, key).mapTo(panel, QtCore.QPoint(0, 0)).x())
                scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
                center = panel.finalize_button.mapTo(scroll.viewport(), panel.finalize_button.rect().center())
                check(f'{prefix}: finalize action is reachable', panel.finalize_button.isVisibleTo(window)
                      and scroll.viewport().rect().contains(center))
                scroll.verticalScrollBar().setValue(0)
                window.grab().save(str(args.output / f'finalize-{engine}-{width}.png'))
        panel.engine.setCurrentIndex(panel.engine.findData('vina'))
        panel.help_buttons['energy_range'].click()
        QTest.qWait(100)
        check('guide is modeless', not panel._settings_guide.isModal())
        check('field help scrolls to the relevant topic', panel._guide_text.verticalScrollBar().value() > 0)
        panel._settings_guide.grab().save(str(args.output / 'settings-guide.png'))
        panel._settings_guide.close()
        check('reading help does not approve the protocol', not panel.approval.isChecked())
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        window.close()
        (args.output / 'verification.json').write_text(json.dumps(result, indent=2))
    return 1 if result.get('error') else 0


if __name__ == '__main__':
    raise SystemExit(main())
