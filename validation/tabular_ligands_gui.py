"""Real GUI/host table approval and subset import; never prepare or dock."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from unittest.mock import patch

from docking_universal.gui.desktop import StudyWindow
from docking_universal.gui.host_client import ApplicationHostClient
from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.models import ArtifactRecord
from docking_universal.state import JsonStudyStore


ROOT = Path(__file__).resolve().parents[1]
SCIENTIFIC = '/opt/anaconda3/envs/docking-universal/bin/python'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, default=ROOT / 'libexec')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    protected = {str(p): digest(p) for p in (Path.home() / 'Library/Application Support/Docking Universal/studies').glob('*/application_state.json')}
    record = {'status': 'running', 'runtime': str(args.runtime), 'checks': [],
              'scientific_docking_searches': 0, 'scientific_approvals': 0}
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    store = JsonStudyStore(args.out / 'state')
    window = None
    messages = []
    def unexpected(*values, **kwargs):
        messages.append(str(values[1:]))
        return QtWidgets.QMessageBox.StandardButton.Cancel
    def check(condition, description):
        if not condition:
            raise AssertionError(description)
        record['checks'].append(description)
    def wait(condition):
        until = time.monotonic() + 30
        while not condition():
            app.processEvents()
            if time.monotonic() > until:
                raise TimeoutError('GUI table operation did not finish')
            time.sleep(.02)
        app.processEvents()
    try:
        with ApplicationHostClient(store.root, args.runtime / 'docking-universal-application-host.py',
                                   python_executable=SCIENTIFIC, timeout_seconds=30) as host, \
             patch.object(QtWidgets.QMessageBox, 'critical', side_effect=unexpected), \
             patch.object(QtWidgets.QMessageBox, 'warning', side_effect=unexpected):
            host.request('table-review', 'create_study', {'name': 'Synthetic table import acceptance'})
            # Synthetic plan-only recipe; never used to authorize/start a search.
            protocol = args.out / 'plan-only.json'
            protocol.write_text(json.dumps({'schema_name': 'docking-universal-protocol',
                'protocol_type': 'site-guided-exploratory', 'screening_authority': 'user-confirmed-exploratory-use',
                'exploratory_screening_allowed': True, 'engine': 'vina',
                'parameters': {'conformers_per_state': 3, 'seeds': [1, 2]},
                'locked_inputs': {'box': 'synthetic.conf', 'boxes': [{'box': 'synthetic.conf', 'box_label': 'P1'}]}}))
            state = store.load('table-review')
            state.artifacts.append(ArtifactRecord('synthetic-recipe', 'protocol_bundle', str(protocol), digest(protocol)))
            store.save(state)
            state_before = store.path_for('table-review').read_bytes()
            settings = QtCore.QSettings(str(args.out / 'window.ini'), QtCore.QSettings.Format.IniFormat)
            window = StudyWindow(store, 'table-review', host_client=host, settings=settings)
            window.resize(1400, 1000)
            window.show()
            panel = window.screening_setup_panel.library_panel
            source = args.out / 'library.csv'
            source.write_text('ID,SMILES,Alternative\n001,CCO,CCN\n002,C[C@H](O)C(=O)O,CCC\n003,not_smiles,CO\n')
            window.screen_ligands.setText(str(source))
            window.screen_output.setText(str(args.out / 'unused-screen-output'))
            check(not window.preview_screening_button.isEnabled(), 'Unread table blocks workload preview')
            window.read_screening_library()
            wait(lambda: not panel.loading)
            check(panel.library is not None and panel.library['records'] == [], 'Auto-detection loads headers only')
            check(panel.smiles_column.currentData() == 1, 'SMILES suggestion prefilled')
            check(panel.smiles_column.count() == panel.name_column.count() == 4, 'Every header available in both dropdowns')
            check(not window.preview_screening_button.isEnabled(), 'Unapproved columns block workload preview')
            panel.approve_columns.click()
            wait(lambda: not panel.loading)
            check(panel.library['mapping_approved'] and len(panel.library['records']) == 3, 'Explicit approval loads compounds')
            check(panel.selection()['record_ids'] == [], 'No compounds selected automatically')
            check(not panel.library['records'][2]['valid'], 'Invalid row visible but unselectable')
            panel.table.setCurrentCell(1, 1)
            wait(lambda: panel._pixmap is not None)
            check(panel._pixmap.width() > 0, 'Host renders selected compound preview')
            panel.table.item(1, 0).setCheckState(QtCore.Qt.CheckState.Checked)
            window.preview_screening()
            check(window._screening_plan['compound_count'] == 1, 'Workload contains only checked compounds')
            check(window._screening_plan['total_docking_jobs'] == 6, 'Workload preserves locked conformer/seed settings')
            selection = panel.selection()
            selection_path = args.out / 'selection.json'
            selection_path.write_text(json.dumps(selection))
            # Execute the actual high-level materializer, with no docking call.
            code = """import importlib.util,json,sys
from pathlib import Path
runtime,out,source,selection=map(Path,sys.argv[1:])
spec=importlib.util.spec_from_file_location('du_run',runtime/'docking-universal-run.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
rows=module.split_compounds(source,out/'inputs/compounds',json.loads(selection.read_text()))
assert len(rows)==1 and rows[0]['source_row']==3
assert rows[0]['isomeric_smiles']=='C[C@H](O)C(=O)O'
(out/'materialized.json').write_text(json.dumps(rows,indent=2))
"""
            environment = dict(os.environ, PYTHONPATH=str(args.runtime))
            subprocess.run([SCIENTIFIC, '-c', code, str(args.runtime), str(args.out), str(source), str(selection_path)],
                           env=environment, check=True, timeout=30)
            check(True, 'Fresh-process CLI materializes only approved subset with stereochemistry/provenance')
            panel.smiles_column.setCurrentIndex(panel.smiles_column.findData(2))
            check(window._screening_plan is None and not window.preview_screening_button.isEnabled(), 'Changed mapping invalidates workload')
            check(panel.selection()['record_ids'] == [] and panel.review.isHidden(), 'Changed mapping clears selection and hides compounds')
            panel.approve_columns.click()
            wait(lambda: not panel.loading)
            check(all(r['valid'] for r in panel.library['records']), 'Arbitrary header override is used only after reapproval')
            check(panel.selection()['record_ids'] == [], 'Reapproval does not restore old compound selection')
            # Excel worksheet choice and literal-only formula handling.
            window.screen_ligands.setText(str(ROOT / 'tests/fixtures/ligand_tables.xlsx'))
            window.read_screening_library()
            wait(lambda: not panel.loading)
            panel.sheet_combo.setCurrentText('Compounds')
            wait(lambda: not panel.loading)
            check(panel.library['table']['sheet'] == 'Compounds' and not panel.library['records'], 'Worksheet change requires fresh column approval')
            panel.approve_columns.click()
            wait(lambda: not panel.loading)
            check(sum(r['valid'] for r in panel.library['records']) == 3, 'XLSX valid, invalid, numeric and formula rows distinguished')
            # The current CSV/Excel review must remain bounded on a small screen.
            for width in (1400, 1100):
                window.resize(width, 1000)
                app.processEvents()
                window.grab().save(str(args.out / f'gui-{width}.png'))
            check(not messages, 'No unexpected dialogs')
            check(store.path_for('table-review').read_bytes() == state_before, 'Read/approve/preview does not mutate study authority')
            check(not (args.out / 'unused-screen-output').exists(), 'No screening or preparation launched')
        check(all(digest(path) == value for path, value in protected.items()), 'Existing study states unchanged')
        record.update(status='passed', protected_sha256=protected)
    except BaseException as exc:
        record.update(status='failed', error=str(exc), messages=messages)
        raise
    finally:
        if window:
            window.close()
        (args.out / 'summary.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
