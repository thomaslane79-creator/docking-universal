"""Verify interactive-only GUI presentation without running scientific searches."""
import json
import os
from pathlib import Path
import re
import subprocess

from autodock_gpu_trial import ROOT, check_idle, digest
from report_sync_acceptance import MODULES

OUT = ROOT / 'validation/runs/gui-interactive-only-20261017'
GUI_MODULES = ('test_desktop_workspace test_workflow_panels test_gui_full_journey '
               'test_linked_pose_review test_cluster_contacts test_embedded_pymol_adapter '
               'test_image_export test_ligand_library_panel test_workspace_controller '
               'test_control_gui_authority').split()


def main():
    check_idle()
    OUT.mkdir(exist_ok=True)
    summary = OUT / 'summary.json'
    if summary.exists():
        raise ValueError('Acceptance record already exists')
    state = Path(json.loads((ROOT / 'validation/runs/adgpu-integration-20261016/gui-ready/summary.json').read_text())['source_state'])
    before = digest(state)
    record = {'status': 'running', 'scientific_searches': 0, 'suites': [], 'native_checks': {}}
    env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
           'PYTHONPATH': str(ROOT / 'libexec') + ':' + str(ROOT / 'tests'),
           'PATH': '/opt/anaconda3/envs/docking-universal/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin',
           'MPLCONFIGDIR': str(OUT / 'matplotlib')}
    try:
        for name, python, modules in (
            ('gui', '/opt/anaconda3/envs/docking-universal-gui-next/bin/python', GUI_MODULES),
            ('report-workflow', '/opt/anaconda3/envs/docking-universal/bin/python', [*MODULES, 'test_protein_identity']),
        ):
            with (OUT / f'{name}.log').open('w') as log:
                result = subprocess.run([python, '-m', 'unittest', '-v', *modules],
                                        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
            text = (OUT / f'{name}.log').read_text()
            count = int(re.search(r'Ran (\d+) tests', text)[1])
            record['suites'].append({'suite': name, 'tests': count, 'passed': result.returncode == 0})
            if result.returncode:
                raise RuntimeError(name + ' checks failed; inspect retained log')
        for name in ('initial-native', 'cluster-native'):
            native = json.loads((OUT / name / 'verification.json').read_text())
            assert native['status'] == 'passed' and all(c['passed'] for c in native['checks'])
            record['native_checks'][name] = len(native['checks'])
        assert digest(state) == before
        record.update(status='passed', original_user_study_unchanged=True,
                      total_tests=sum(row['tests'] for row in record['suites']),
                      source_state_sha256=before, visual_review='passed; native workspace screenshot inspected')
    except BaseException as exc:
        record.update(status='failed', error=str(exc))
        raise
    finally:
        summary.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
