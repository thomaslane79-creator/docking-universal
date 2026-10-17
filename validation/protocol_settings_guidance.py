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
    def check(name, condition):
        result['checks'].append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)
    try:
        for width, height in ((960, 760), (1280, 800), (1440, 900)):
            window.resize(width, height)
            window.show()
            QTest.qWait(100)
            window.grab().save(str(args.output / f'finalize-{width}.png'))
            check(f'{width}: no forced horizontal scroll', scroll.horizontalScrollBar().maximum() == 0)
            for key, explanation in panel.inline_explanations.items():
                bounds = explanation.contentsRect()
                needed = explanation.fontMetrics().boundingRect(bounds, QtCore.Qt.TextFlag.TextWordWrap,
                                                               explanation.text()).height()
                result.setdefault('text_geometry', []).append({'width': width, 'key': key,
                    'actual': [bounds.width(), bounds.height()], 'needed_height': needed})
                check(f'{width}: {key} explanation is fully laid out', needed <= bounds.height() + 4)
                if key != 'approval':
                    check(f'{width}: {key} explanation is beside its control',
                          explanation.mapTo(panel, QtCore.QPoint(0, 0)).x() >
                          getattr(panel, key).mapTo(panel, QtCore.QPoint(0, 0)).x())
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
            center = panel.finalize_button.mapTo(scroll.viewport(), panel.finalize_button.rect().center())
            check(f'{width}: finalize action is reachable', panel.finalize_button.isVisibleTo(window)
                  and scroll.viewport().rect().contains(center))
            scroll.verticalScrollBar().setValue(0)
            window.grab().save(str(args.output / f'finalize-{width}.png'))
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
