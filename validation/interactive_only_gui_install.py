"""Install the accepted presentation change with recoverable GUI-file backups."""
import json
import os
from pathlib import Path
import shutil
import subprocess

from autodock_gpu_trial import ROOT, check_idle, digest

OUT = ROOT / 'validation/runs/gui-interactive-only-20261017'
BEFORE = {
    'desktop.py': 'a96d9957489c67cc4af3adcbd52719db4306f0d17a5edf3378b0b51b77566dcc',
    'pocket_evidence.py': '4778a527431dfd332d02b4313fbe3785c5f42ac957d3cccb0a4d73971ea05d79',
    'results_review.py': '6ba7b8857fe76ea9c87ae7074eed14d42cd83d1f4822d5e1446561d0dbd1949f',
}


def main():
    qa = json.loads((OUT / 'summary.json').read_text())
    assert qa['status'] == 'passed' and qa['total_tests'] == 384
    assert qa['native_checks'] == {'initial-native': 31, 'cluster-native': 61}
    check_idle()
    destination = Path('/opt/anaconda3/envs/docking-universal/libexec/docking-universal')
    for name, expected in BEFORE.items():
        assert digest(destination / 'docking_universal/gui' / name) == expected
    state = Path(json.loads((ROOT / 'validation/runs/adgpu-integration-20261016/gui-ready/summary.json').read_text())['source_state'])
    before_state = digest(state)
    backup = OUT / 'installation-backup'
    backup.mkdir(exist_ok=False)
    record = {'status': 'installing', 'files': []}

    def publish(source, target):
        temporary = target.with_name(target.name + '.interactive-only-new')
        shutil.copy2(source, temporary)
        temporary.replace(target)

    try:
        for name in BEFORE:
            relative = Path('docking_universal/gui') / name
            source, target = ROOT / 'libexec' / relative, destination / relative
            shutil.copy2(target, backup / name)
            publish(source, target)
            assert digest(source) == digest(target)
            record['files'].append({'relative': str(relative), 'sha256': digest(target)})
        env = {**os.environ, 'PYTHONPATH': str(destination), 'QT_QPA_PLATFORM': 'offscreen'}
        code = (
            'from docking_universal.gui.desktop import StudyWindow;'
            'from docking_universal.gui.results_review import ResultsReviewPanel;'
            'from docking_universal.gui.qt import QtWidgets;'
            'assert not hasattr(StudyWindow,"_show_selected_decision_figure");'
            'assert hasattr(StudyWindow,"_refresh_structure_scenes");'
            'a=QtWidgets.QApplication([]);p=ResultsReviewPanel({"status":"unavailable","missing":[]});'
            'assert p.open_diagram_button.text()=="Open 2D/3D review";'
            'print("Installed interactive-only GUI modules verified")'
        )
        smoke = subprocess.run(['/opt/anaconda3/envs/docking-universal-gui-next/bin/python', '-c', code],
                               env=env, text=True, capture_output=True, check=True, timeout=30)
        record['installed_smoke'] = smoke.stdout.strip()
        assert digest(state) == before_state
        record.update(status='installed', original_study_unchanged=True, scientific_searches=0)
    except BaseException as exc:
        for row in record['files']:
            name = Path(row['relative']).name
            publish(backup / name, destination / row['relative'])
        record.update(status='failed', error=str(exc), restored_previous_gui=True)
        raise
    finally:
        (OUT / 'installation.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
