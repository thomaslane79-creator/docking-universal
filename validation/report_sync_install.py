"""Deploy the accepted report-only synchronization with recoverable backups."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from autodock_gpu_trial import ROOT,check_idle,digest

FILES=['docking_universal/reporting.py','docking_universal/pocket_metadata.py',
       'docking_universal/protocol_finalization.py','docking_universal_bundle.py',
       'docking-universal-pdf-report.py','docking-universal-run.py']


def main():
    out=ROOT/'validation/runs/report-sync-20261017'
    qa=json.loads((out/'summary.json').read_text())
    assert qa['status']=='passed' and qa['visual_review'].startswith('passed') and qa['regression_tests']==225
    assert digest(qa['pdf'])==qa['pdf_sha256']
    check_idle()
    old=json.loads((ROOT/'validation/runs/adgpu-integration-20261016/installation/summary.json').read_text())
    expected={row['relative']:row['source_sha256'] for row in old['files']}
    previous=json.loads((ROOT/'validation/runs/report-score-beside-result-20261017/installation.json').read_text())
    expected['docking-universal-pdf-report.py']=previous['sha256']
    prefix=Path('/opt/anaconda3/envs/docking-universal');installed=prefix/'libexec/docking-universal'
    for name in FILES:
        assert digest(installed/name)==expected[name] if name in expected else not (installed/name).exists()
    state=Path(json.loads((ROOT/'validation/runs/adgpu-integration-20261016/gui-ready/summary.json').read_text())['source_state'])
    state_hash=digest(state)
    backup=out/'installation-backup';backup.mkdir(exist_ok=False)
    record={'status':'installing','files':[],'original_study_sha256':state_hash}
    def publish(source,target):
        target.parent.mkdir(parents=True,exist_ok=True)
        tmp=target.with_name(target.name+'.report-sync-new');shutil.copy2(source,tmp);tmp.replace(target)
    try:
        for name in FILES:
            target=installed/name;saved=backup/name
            if target.exists():saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
            publish(ROOT/'libexec'/name,target)
            record['files'].append({'relative':name,'sha256':digest(target)})
        env={**os.environ,'PYTHONPATH':str(installed)}
        code=('import importlib.util,json;from pathlib import Path;import docking_universal.reporting as r;'
              f'p=Path({str(installed)!r});s=importlib.util.spec_from_file_location("installed_report",p/"docking-universal-pdf-report.py");'
              'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
              f'protocol=Path({str(ROOT/"validation/runs/adgpu-integration-20261016/gui-ready/screen-source/inputs/locked_protocol/protocol.json")!r});'
              'c=m.inherited_protocol_cavity_record(json.loads(protocol.read_text()),protocol);'
              'assert c["selected"]["rank_score"]==2.49;assert r.scoring_function_label("vina")=="Vina";'
              'print(json.dumps({"module":r.__file__,"pocket_score":c["selected"]["rank_score"]}))')
        smoke=subprocess.run([str(prefix/'bin/python'),'-c',code],env=env,capture_output=True,text=True,check=True)
        record['installed_smoke']=json.loads(smoke.stdout)
        assert Path(record['installed_smoke']['module'])==installed/'docking_universal/reporting.py'
        assert all(digest(installed/row['relative'])==row['sha256']==digest(ROOT/'libexec'/row['relative']) for row in record['files'])
        assert digest(state)==state_hash
        final=ROOT/'output/pdf/2R8N-docking-report.pdf'
        assert digest(final)==previous['pdf_sha256']
        shutil.copy2(final,backup/'previous-report.pdf');publish(Path(qa['pdf']),final)
        assert digest(final)==qa['pdf_sha256']
        record.update(status='installed',pdf=str(final),pdf_sha256=digest(final),regression_tests=225,
                      original_study_unchanged=True,scientific_searches=0)
    except BaseException as exc:
        record.update(status='failed',error=str(exc))
        for row in reversed(record['files']):
            name=row['relative'];saved=backup/name
            if saved.exists():publish(saved,installed/name)
            else:
                displaced=backup/('new-'+Path(name).name);shutil.move(str(installed/name),str(displaced))
        raise
    finally:(out/'installation.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({key:record[key] for key in ('status','regression_tests','original_study_unchanged','pdf')},indent=2))


if __name__=='__main__':main()
