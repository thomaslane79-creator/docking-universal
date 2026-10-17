"""Native, read-only check that a completed screen retains its duration."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'libexec'))
from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.gui.desktop import StudyWindow
from docking_universal.state import JsonStudyStore
from PyQt6.QtTest import QTest


class ReadOnlyStore(JsonStudyStore):
    def save(self, *args, **kwargs):
        raise AssertionError('Validation must not save the user study')
    def update(self, *args, **kwargs):
        raise AssertionError('Validation must not change the user study')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root', type=Path, required=True)
    parser.add_argument('--study-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QtWidgets.QApplication([])
    store = ReadOnlyStore(args.state_root)
    before = hashlib.sha256(store.path_for(args.study_id).read_bytes()).hexdigest()
    result = {'checks': []}
    def check(name, value):
        result['checks'].append({'name': name, 'passed': bool(value)})
        if not value: raise AssertionError(name)
    with tempfile.TemporaryDirectory() as folder:
        settings = QtCore.QSettings(str(Path(folder) / 'ui.ini'), QtCore.QSettings.Format.IniFormat)
        for width in (1100, 1440):
            window = StudyWindow(store, args.study_id, settings=settings)
            try:
                window.resize(width, 900)
                window.show()
                window._activate_workflow_target('locked_protocol_screening_dock')
                QTest.qWait(100)
                label = window.screening_setup_panel.elapsed
                check(f'{width}: completed duration retained', 'Total run time 12:09' in label.text())
                check(f'{width}: label visible', label.isVisibleTo(window))
                check(f'{width}: no moving activity bar after completion', not window.running_indicator.isVisibleTo(window))
                window.grab().save(str(args.output / f'duration-{width}.png'))
            finally:
                window.close()
    check('user state unchanged', hashlib.sha256(store.path_for(args.study_id).read_bytes()).hexdigest() == before)
    (args.output / 'verification.json').write_text(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
