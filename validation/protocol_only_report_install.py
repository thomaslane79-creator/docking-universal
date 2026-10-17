"""Publish visually accepted protocol reports and the verified PDF generator."""
import json
import os
from pathlib import Path
import shutil
import subprocess

from autodock_gpu_trial import ROOT, check_idle, digest

OUT = ROOT / 'validation/runs/protocol-only-reports-20261017_b'


def main():
    qa = json.loads((OUT / 'summary.json').read_text())
    assert qa['status'] == 'passed' and qa['regression_tests'] == 230
    assert all(row['visual_review'] == 'passed; all three portrait pages visually inspected'
               and digest(row['pdf']) == row['sha256'] for row in qa['reports'].values())
    check_idle()
    previous = json.loads((ROOT / 'validation/runs/report-sync-20261017/installation.json').read_text())
    expected = next(row['sha256'] for row in previous['files']
                    if row['relative'] == 'docking-universal-pdf-report.py')
    installed = Path('/opt/anaconda3/envs/docking-universal/libexec/docking-universal')
    target = installed / 'docking-universal-pdf-report.py'
    assert digest(target) == expected
    state = Path(json.loads((ROOT / 'validation/runs/adgpu-integration-20261016/gui-ready/summary.json').read_text())['source_state'])
    before_state = digest(state)
    backup = OUT / 'installation-backup'
    backup.mkdir(exist_ok=False)
    shutil.copy2(target, backup / target.name)
    destinations = {
        engine: ROOT / 'output/pdf' / f'2R8N-{engine}-protocol-report.pdf'
        for engine in qa['reports']
    }
    assert not any(path.exists() for path in destinations.values())
    record = {'status': 'installing', 'reports': {}, 'regression_tests': 230}

    def publish(source, destination):
        temporary = destination.with_name(destination.name + '.protocol-report-new')
        shutil.copy2(source, temporary)
        temporary.replace(destination)

    try:
        publish(ROOT / 'libexec' / target.name, target)
        assert digest(target) == digest(ROOT / 'libexec' / target.name)
        code = (
            'import importlib.util,json;'
            f's=importlib.util.spec_from_file_location("installed_protocol_report",{str(target)!r});'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'p={"pocket_detection":{"engine":"p2rank"},"docking_regions":'
            '[{"box_label":"P4","geometry":{},"pocket_prediction":'
            '{"detector":"p2rank","score":1.11,"probability":0.008}}]};'
            'c=m.inherited_protocol_cavity_record(p);'
            'assert c["selected"]["rank_score"]==1.11;'
            'assert m.scoring_function_label("adgpu")=="AD4";'
            'assert m.scoring_function_label("vina")=="Vina";'
            'print(json.dumps({"module":m.__file__,"selected_score":1.11}))'
        )
        smoke = subprocess.run(['/opt/anaconda3/envs/docking-universal/bin/python', '-c', code],
                               env={**os.environ, 'PYTHONPATH': str(installed)},
                               text=True, capture_output=True, check=True)
        record['installed_smoke'] = json.loads(smoke.stdout)
        for engine, destination in destinations.items():
            publish(Path(qa['reports'][engine]['pdf']), destination)
            assert digest(destination) == qa['reports'][engine]['sha256']
            record['reports'][engine] = str(destination)
        assert digest(state) == before_state
        record.update(status='installed', source_sha256=digest(target),
                      original_study_unchanged=True, scientific_searches=0)
    except BaseException as exc:
        publish(backup / target.name, target)
        for destination in destinations.values():
            if destination.exists():
                shutil.move(str(destination), str(backup / destination.name))
        record.update(status='failed', error=str(exc))
        raise
    finally:
        (OUT / 'installation.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
