"""Report-only synchronization acceptance; never run preparation or docking."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from unittest.mock import patch
from autodock_gpu_trial import check_idle, digest

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'validation/runs/report-sync-20261017'
MODULES=('test_report_synchronization test_report_cavity test_retained_report_artifacts '
         'test_protocol_finalization test_protocol_finalization_integration test_multisite_report_figures '
         'test_figure_labels test_control_pose_landscape test_protocol_types test_multisite_protocol '
         'test_guided_options test_run_selection test_protocol_workflow test_screening_workflow '
         'test_screening_service test_screening_progress').split()


def load(name, filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'libexec'/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def main():
    check_idle();OUT.mkdir(exist_ok=False)
    result={'status':'running','scientific_searches':0,'test_modules':MODULES}
    def save():(OUT/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    save()
    env={**os.environ,'PATH':'/opt/anaconda3/envs/docking-universal/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin',
         'PYTHONPATH':str(ROOT/'libexec')+':'+str(ROOT/'tests'),'MPLCONFIGDIR':str(OUT/'matplotlib')}
    try:
        test=subprocess.run([sys.executable,'-m','unittest',*MODULES],env=env,capture_output=True,text=True)
        (OUT/'regressions.log').write_text(test.stdout+'\n'+test.stderr)
        result['regression_tests']=int(re.search(r'Ran (\d+) tests',test.stderr)[1])
        if test.returncode:raise ValueError('Regression failure; see regressions.log')
        source=ROOT/'validation/runs/report-bold-callouts-20261017/study'
        before={str(p):digest(p) for p in source.rglob('*') if p.is_file()}
        study=OUT/'study';study.mkdir()
        for path in source.iterdir():
            if path.name=='report':shutil.copytree(path,study/path.name,ignore=shutil.ignore_patterns('*.pdf'))
            else:(study/path.name).symlink_to(path,target_is_directory=path.is_dir())
        previous=json.loads((study/'report/study_summary.json').read_text())
        runner=load('sync_accepted_run','docking-universal-run.py')
        pdf=load('sync_accepted_pdf','docking-universal-pdf-report.py')
        run=subprocess.run
        def presentation_only(command,*args,**kwargs):
            name=Path(str(command[1])).name if len(command)>1 else ''
            if name=='docking-universal-report-figures.py':
                return subprocess.CompletedProcess(command,0,'Accepted retained figures reused','')
            if name=='docking-universal-pdf-report.py':
                with patch.object(sys,'argv',[str(command[1]),*map(str,command[2:])]):pdf.main()
                return subprocess.CompletedProcess(command,0,'Shared PDF generated','')
            return run(command,*args,**kwargs)
        with patch.object(runner.subprocess,'run',side_effect=presentation_only):
            runner.write_reports(study,previous,previous['compounds'])
        summary=json.loads((study/'report/study_summary.json').read_text())
        final=study/'report'/summary['pdf_report']
        text=run(['/opt/homebrew/bin/pdftotext',str(final),'-'],capture_output=True,text=True,check=True).stdout
        normalized=' '.join(text.split())
        for phrase in ('Selected P2Rank score 2.49','Selected P2Rank probability 0.069',
                       'Best docking score Scoring function','Distinct pose clusters'):
            if phrase not in normalized:raise ValueError('PDF omitted '+phrase)
        for phrase in ('recorded in the protocol-selection report','Independent-seed support',
                       'Conformer support','Selected representatives'):
            if phrase in text:raise ValueError('Old report wording remains: '+phrase)
        html=(study/'report/index.html').read_text();md=(study/'report/study_report.md').read_text()
        assert 'Best docking score</th><th>Scoring function' in html
        assert 'Best docking score | Scoring function' in md
        assert '<td>AD4</td>' in html and '| AD4 |' in md
        assert 'best_cluster_seed_support' not in html and '| Seed support |' not in md
        assert all(digest(Path(path))==value for path,value in before.items())
        result.update(status='passed',pdf=str(final),pdf_sha256=digest(final),
            html=str(study/'report/index.html'),markdown=str(study/'report/study_report.md'),
            original_artifacts_hash_verified=len(before),visual_review='pending',
            reused_protocol_score=2.49,reused_protocol_probability=.069)
    except BaseException as exc:
        result.update(status='failed',error=str(exc));raise
    finally:save()
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
