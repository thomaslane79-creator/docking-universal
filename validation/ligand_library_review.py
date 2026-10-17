"""Native ligand-selection acceptance with the real host, but no docking jobs."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'libexec'))


def fixtures(directory):
    from rdkit import Chem
    directory.mkdir(parents=True)
    with Chem.SDWriter(str(directory / 'library.sdf')) as writer:
        for name, smiles in [('Acetaminophen', 'CC(=O)NC1=CC=C(O)C=C1'),
                             ('Caffeine', 'Cn1c(=O)c2c(ncn2C)n(C)c1=O')]:
            molecule = Chem.MolFromSmiles(smiles)
            molecule.SetProp('_Name', name)
            writer.write(molecule)
    with (directory / 'library.sdf').open('a') as stream:
        stream.write('Broken record\nnot a molecule\n\n\n$$$$\n')
    molecule = Chem.MolFromSmiles('C[C@H](O)C(=O)[O-]')
    molecule.SetProp('_Name', 'Chiral lactate')
    Chem.MolToMolFile(molecule, str(directory / 'lactate.MOL'), forceV3000=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--protocol', type=Path)
    parser.add_argument('--scientific-python', default='/opt/anaconda3/envs/docking-universal/bin/python')
    parser.add_argument('--generate-fixtures', type=Path)
    parser.add_argument('--library', type=Path, help='Copy a generated scale-test folder, never mutate its source')
    parser.add_argument('--expected-records', type=int, default=4)
    args = parser.parse_args()
    if args.generate_fixtures:
        fixtures(args.generate_fixtures)
        return 0
    from docking_universal.gui.qt import QtCore, QtWidgets
    from docking_universal.gui.host_client import ApplicationHostClient
    from docking_universal.gui.desktop import StudyWindow
    from docking_universal.application import StudyController
    from docking_universal.models import ArtifactRecord, CompletionStatus
    from docking_universal.state import JsonStudyStore
    from PyQt6.QtTest import QTest
    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    args.output.mkdir(parents=True, exist_ok=True)
    results = {'checks': []}
    def check(name, ok):
        results['checks'].append({'name': name, 'passed': bool(ok)})
        if not ok:
            raise AssertionError(name)
    def wait_until(predicate):
        deadline = time.monotonic() + 15
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(25)
        if not predicate():
            raise AssertionError('Timed out waiting for asynchronous library/preview')
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        inputs = root / 'ligands'
        if args.library:
            shutil.copytree(args.library, inputs)
        else:
            subprocess.run([args.scientific_python, __file__, '--generate-fixtures', str(inputs)], check=True)
        source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs.iterdir()}
        bundle_before = hashlib.sha256(args.protocol.read_bytes()).hexdigest()
        store = JsonStudyStore(root / 'state')
        StudyController(store).create_study('library-test', 'Isolated library review — no docking')
        state = store.load('library-test')
        state.selected_pocket_ids = ['P1']
        state.completion_status = CompletionStatus.COMPLETED
        state.artifacts = [ArtifactRecord('bundle', 'protocol_bundle', str(args.protocol.resolve()), sha256=bundle_before)]
        store.save(state)
        before = store.path_for('library-test').read_bytes()
        client = ApplicationHostClient(root / 'state', ROOT / 'libexec/docking-universal-application-host.py',
                                       python_executable=args.scientific_python)
        window = None
        try:
            client.start()
            settings = QtCore.QSettings(str(root / 'ui.ini'), QtCore.QSettings.Format.IniFormat)
            window = StudyWindow(store, 'library-test', host_client=client, settings=settings)
            window.resize(1440, 1000)
            window.show()
            window.screen_ligands.setText(str(inputs))
            window.screen_output.setText(str(root / 'never-launched'))
            panel = window.screening_setup_panel.library_panel
            beats = []
            timer = QtCore.QTimer()
            timer.setInterval(10)
            timer.timeout.connect(lambda: beats.append(True))
            timer.start()
            panel.read_button.click()
            check('read feedback is immediate and workload launch is gated', panel.loading and not window.start_screening_button.isEnabled())
            wait_until(lambda: panel.library is not None or panel.read_error)
            check('real scientific host reads every requested record',
                  panel.library is not None and len(panel.library['records']) == args.expected_records)
            check('GUI remains responsive during host read', len(beats) > 0)
            check('inspection never selects compounds automatically', not panel.selection()['record_ids'])
            target = 0 if args.library else next(i for i, row in enumerate(panel.library['records']) if row['name'] == 'Caffeine')
            panel.table.setCurrentCell(target, 1)
            wait_until(lambda: panel._pixmap is not None)
            check('actual host-rendered 2D appears without selecting it for docking',
                  not panel._pixmap.isNull() and not panel.selection()['record_ids'])
            panel.table.item(target, 0).setCheckState(QtCore.Qt.CheckState.Checked)
            window.preview_screening()
            check('one checked compound determines the exact host workload', window._screening_plan['compound_count'] == 1)
            if args.expected_records > 50:
                plan = window._screening_plan
                panel.next_button.click()
                check('next page renders only 50 rows without invalidating workload',
                      panel.table.rowCount() == 50 and window._screening_plan is plan)
                panel.table.item(0, 0).setCheckState(QtCore.Qt.CheckState.Checked)
                panel.page_number.setValue(panel.page_number.maximum())
                panel.table.item(panel.table.rowCount() - 1, 0).setCheckState(QtCore.Qt.CheckState.Checked)
                panel.page_number.setValue(1)
                check('selection survives first middle and last pages',
                      len(panel.selection()['record_ids']) == 3 and panel.table.item(0, 0).checkState() == QtCore.Qt.CheckState.Checked)
                window.preview_screening()
                check('host workload includes checked records across pages', window._screening_plan['compound_count'] == 3)
            # Visible-but-clipped text must not auto-scroll the list under the mouse.
            window.resize(1100, 850)
            QTest.qWait(80)
            window.screen_ligands.setFocus()
            QTest.qWait(40)
            panel.table.horizontalScrollBar().setValue(90)
            panel.table.verticalScrollBar().setValue(5)
            window.stage_form_scroll.verticalScrollBar().setValue(60)
            check('cycling regression uses a horizontally clipped compound column',
                  panel.table.horizontalScrollBar().value() > 0)
            before_cycle = (window.geometry(), window.stage_form_scroll.verticalScrollBar().value(),
                            panel.table.geometry(), panel.splitter.sizes(), panel.table.horizontalScrollBar().value())
            for row in range(min(3, panel.table.rowCount())):
                if not panel.library['records'][row]['valid']:
                    continue
                index = panel.table.model().index(row, 1)
                rect = panel.table.visualRect(index).intersected(panel.table.viewport().rect())
                QTest.mouseClick(panel.table.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=rect.center())
                wait_until(lambda: panel._pixmap is not None)
                check('compound cycling preserves window layout and both scroll positions',
                      (window.geometry(), window.stage_form_scroll.verticalScrollBar().value(),
                       panel.table.geometry(), panel.splitter.sizes(), panel.table.horizontalScrollBar().value()) == before_cycle)
            for width, height in [(1440, 1000), (1100, 850)]:
                window.resize(width, height)
                QTest.qWait(150)
                check(f'compound table and 2D remain visible at {width}', panel.table.isVisibleTo(window) and panel.preview.isVisibleTo(window))
                window.grab().save(str(args.output / f'library-{width}.png'))
            panel.set_all(True)
            valid_count = sum(row['valid'] for row in panel.library['records'])
            check('selection change invalidates the workload and excludes invalid record',
                  window._screening_plan is None and len(panel.selection()['record_ids']) == valid_count)
            window.preview_screening()
            check('select all covers valid records on every page', window._screening_plan['compound_count'] == valid_count)
            (inputs / 'library.sdf').write_text((inputs / 'library.sdf').read_text() + '\n')
            with patch('docking_universal.gui.desktop.QtWidgets.QMessageBox.critical') as error:
                window.preview_screening()
                check('changed input is rejected before any docking can start', error.called and window._screening_plan is None)
            check('no study authority or scientific jobs were written by inspection', store.path_for('library-test').read_bytes() == before)
            check('protocol bundle is unchanged', hashlib.sha256(args.protocol.read_bytes()).hexdigest() == bundle_before)
            if not args.library:
                check('MOL coordinates and chemistry file remain unchanged', hashlib.sha256((inputs / 'lactate.MOL').read_bytes()).hexdigest() == source_hashes['lactate.MOL'])
            check('no screening output or job exists', not (root / 'never-launched').exists() and not store.load('library-test').jobs)
            timer.stop()
        except Exception as exc:
            results['error'] = str(exc)
        finally:
            if window:
                window.close()
            client.close()
    (args.output / 'verification.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    return int('error' in results)


if __name__ == '__main__':
    raise SystemExit(main())
