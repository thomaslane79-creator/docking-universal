"""Check exact runtime GUI/result labels and report provenance without searches.

Only disposable synthetic study files and screenshots are written below --out.
No user study, docking result, protocol or installed configuration is changed.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(runtime))
    from docking_universal.gui.qt import QtCore, QtWidgets
    from docking_universal.gui.desktop import StudyWindow
    from docking_universal.application import StudyController
    from docking_universal.models import ArtifactRecord
    from docking_universal.state import JsonStudyStore
    import docking_universal.gui.results_model as results_model
    if not Path(results_model.__file__).resolve().is_relative_to(runtime):
        raise AssertionError('The selected application runtime was not imported')
    spec = importlib.util.spec_from_file_location('checked_pdf', runtime / 'docking-universal-pdf-report.py')
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)
    checks = []

    def check(condition, name):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    ligand_protocol = {'pocket_detection': {'engine': 'none'},
                       'docking_regions': [{'site_source': 'input_bound_ligand', 'geometry': {}}]}
    record = report.reproducibility_record(ligand_protocol, args.out, None)
    check(any(row['role'] == 'Docking-region definition' and row['software'] == 'Exact input-ligand site'
              for row in record['software']), 'No-prediction report has no invented detector')
    rows = report.pocket_prediction_rows(report.inherited_protocol_cavity_record(ligand_protocol))
    check(rows == [['Pocket prediction', 'Not requested; exact input-ligand site']],
          'Ligand-defined pocket table states prediction was not requested')
    record = report.reproducibility_record(
        {'pocket_detection': {'engine': 'p2rank', 'engine_version': '2.5.1'}}, args.out, None)
    detector = next(row for row in record['software'] if row['software'] == 'P2Rank')
    check(detector['version'] == '2.5.1', 'Retained detector-operation version is preserved')
    report.require_complete_used_versions({'software': [detector]})
    try:
        report.require_complete_used_versions({'software': [{**detector, 'version': 'not recorded'}]})
    except SystemExit:
        checks.append('Genuinely missing version still rejects incomplete provenance')
    else:
        raise AssertionError('Missing provenance was incorrectly accepted')

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = JsonStudyStore(args.out / 'synthetic-studies')
    StudyController(store).create_study('labels', 'Synthetic GUI label checks - no docking')
    state = store.load('labels')
    for name, engine in (('Synthetic Vina', 'vina'), ('Synthetic QuickVina', 'qvinaw'),
                         ('Synthetic AD4', 'adgpu'), ('Legacy unrecorded', None)):
        root = args.out / name
        root.mkdir()
        manifest = root / 'screen_manifest.json'
        manifest.write_text(json.dumps({'engine': engine, 'completion_status': 'synthetic fixture'}))
        (root / 'all_scores.csv').write_text('affinity\n-6.5\n-7.2\n')
        state.artifacts.append(ArtifactRecord(name, 'screening_compound_manifest', str(manifest)))
    store.save(state)
    before = store.path_for('labels').read_bytes()
    settings = QtCore.QSettings(str(args.out / 'isolated.ini'), QtCore.QSettings.Format.IniFormat)
    window = StudyWindow(store, 'labels', settings=settings)
    try:
        window.resize(1280, 900)
        window.show()
        window._activate_workflow_target('screening_results_dock')
        app.processEvents()
        table = window.screening_results
        check(table.horizontalHeaderItem(4).text() == 'Best energy (kcal/mol)', 'GUI energy units are explicit')
        check(table.horizontalHeaderItem(5).text() == 'Scoring function', 'Energy model column is adjacent')
        displayed = {table.item(i, 0).text(): table.item(i, 5).text() for i in range(table.rowCount())}
        check(displayed == {'Synthetic Vina': 'Vina', 'Synthetic QuickVina': 'Vina',
                            'Synthetic AD4': 'AD4', 'Legacy unrecorded': 'Not recorded'},
              'GUI uses each retained engine and does not guess missing historical identity')
        check(all(table.item(i, 4).text() == '-7.2' for i in range(table.rowCount())),
              'Presentation does not change energies')
        window.detach_results_review()
        app.processEvents()
        header = table.horizontalHeader()
        check(header.sectionViewportPosition(5) >= 0 and
              header.sectionViewportPosition(5) + header.sectionSize(5) <= table.viewport().width(),
              'Energy and scoring identity fit the detached results window')
        window.screening_results_dock.grab().save(str(args.out / 'results-labels.png'))
        check(store.path_for('labels').read_bytes() == before, 'Review does not change study authority')
    finally:
        window.close()
        app.processEvents()
    summary = {'status': 'passed', 'runtime': str(runtime), 'checks': checks,
               'scientific_searches': 0, 'scientific_approvals': 0}
    (args.out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
