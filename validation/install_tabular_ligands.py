"""Backed-up, targeted installation after source table-import acceptance."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from autodock_gpu_trial import ROOT, STATE_ROOT, check_idle, digest


OUT = ROOT / 'validation/runs/tabular-ligands-20261017'
DEST = Path('/opt/anaconda3/envs/docking-universal/libexec/docking-universal')
FILES = ('docking_universal/services/ligand_table.py', 'docking_universal/services/ligand_input.py',
         'docking_universal/services/ligand_library.py', 'docking_universal/services/screening.py',
         'docking_universal/host.py', 'docking_universal/gui/application_host_controller.py',
         'docking_universal/gui/ligand_library_panel.py', 'docking_universal/gui/desktop.py',
         'docking_universal/gui/workflow_panels.py', 'docking-universal-run.py')
SCIENCE_TESTS = ('tests.test_ligand_input', 'tests.test_ligand_library', 'tests.test_ligand_tables',
                 'tests.test_screening_service', 'tests.test_screening_workflow',
                 'tests.test_screening_progress', 'tests.test_application_host', 'tests.test_run_selection')
GUI_TESTS = ('tests.test_ligand_library_panel', 'tests.test_application_host_controller',
             'tests.test_desktop_workspace', 'tests.test_gui_full_journey', 'tests.test_workflow_panels',
             'tests.test_host_client', 'tests.test_gui_protocol_import')


def main():
    assert json.loads((OUT / 'source-guarded/summary.json').read_text())['status'] == 'passed'
    for name in ('scientific-tests.log', 'gui-tests.log'):
        text = (OUT / name).read_text()
        assert '\nOK\n' in text and 'FAILED (' not in text, name
    check_idle()
    protected = {str(path): digest(path) for path in STATE_ROOT.glob('*/application_state.json')}
    # Retained original studies/results from the preceding preparation acceptance.
    prior = json.loads((ROOT / 'validation/runs/reduce2-frame-fix-installed-20261017/summary.json').read_text())
    for path in prior['protected_sha256']:
        assert Path(path).is_file(), path
        protected[path] = digest(path)
    backup = Path(tempfile.mkdtemp(prefix='installation-backup-', dir=OUT))
    record = {'status': 'installing', 'files': [], 'protected_sha256': protected, 'backup': str(backup),
              'scientific_docking_searches': 0, 'scientific_approvals': 0}
    def publish(source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.tabular-new')
        shutil.copy2(source, temporary)
        temporary.replace(target)
    try:
        for relative in FILES:
            source, target, saved = ROOT / 'libexec' / relative, DEST / relative, backup / relative
            row = {'relative': relative, 'sha256': digest(source),
                   'previous_sha256': digest(target) if target.is_file() else None}
            if target.is_file():
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            record['files'].append(row)
            publish(source, target)
            assert digest(target) == row['sha256']
        environment = dict(os.environ, PYTHONPATH=os.pathsep.join((str(DEST), str(ROOT), str(ROOT / 'tests'))),
                           QT_QPA_PLATFORM='offscreen')
        commands = (
            ('installed-scientific-tests.log', ['/opt/anaconda3/envs/docking-universal/bin/python', '-m', 'unittest', *SCIENCE_TESTS]),
            ('installed-gui-tests.log', ['/opt/anaconda3/envs/docking-universal-gui-next/bin/python', '-m', 'unittest', *GUI_TESTS]),
            ('installed-acceptance.log', ['/opt/anaconda3/envs/docking-universal-gui-next/bin/python',
                str(ROOT / 'validation/tabular_ligands_gui.py'), '--runtime', str(DEST), '--out', str(OUT / 'installed-guarded')]),
        )
        for name, command in commands:
            with (OUT / name).open('w') as log:
                subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
                               check=True, timeout=180)
        qa = json.loads((OUT / 'installed-guarded/summary.json').read_text())
        assert qa['status'] == 'passed' and qa['scientific_docking_searches'] == 0
        assert all(digest(path) == value for path, value in protected.items())
        assert all(digest(DEST / row['relative']) == digest(ROOT / 'libexec' / row['relative']) == row['sha256']
                   for row in record['files'])
        record.update(status='installed', existing_studies_and_results_unchanged=True,
                      installed_validation=str(OUT / 'installed-guarded/summary.json'))
    except BaseException as exc:
        for row in reversed(record['files']):
            target = DEST / row['relative']
            if row['previous_sha256'] is not None:
                publish(backup / row['relative'], target)
            elif target.is_file() and digest(target) == row['sha256']:
                target.unlink()
        record.update(status='failed', error=str(exc), previous_installation_restored=True)
        raise
    finally:
        (OUT / 'installation.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'status': record['status'], 'files': len(record['files']),
                      'existing_studies_and_results_unchanged': True}))


if __name__ == '__main__':
    main()
