"""Presentation-only bold report callouts; preserve all retained science."""
import csv
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch
from autodock_gpu_trial import check_idle, digest

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    check_idle()
    source = ROOT / 'validation/runs/adgpu-integration-20261016/gui-ready/screen-source'
    out = ROOT / 'validation/runs/report-bold-callouts-20261017'
    out.mkdir(exist_ok=False)
    before = {str(p):digest(p) for p in source.rglob('*') if p.is_file()}
    study = out / 'study'
    shutil.copytree(source,study)
    figures = load('bold_report_figures','libexec/docking-universal-report-figures.py')
    env = {**os.environ,'PYTHONPATH':str(ROOT/'libexec'),
           'PATH':'/opt/anaconda3/envs/docking-universal/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin'}
    record = {'status':'running','font':'Sans Bold','font_id':7,'label_size_unchanged':40,
              'placement_unchanged':True,'scientific_searches':0,'figures':[]}
    def save(): (out/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    save()
    try:
        for pml in sorted(study.glob('compounds/*/pose_analysis/cluster_*/interactions/complex_plip_all_in_one.pml')):
            labels = pml.with_suffix('.residue-labels.json')
            old = json.loads(labels.read_text())
            command = [sys.executable,str(ROOT/'libexec/docking-universal-render3d.py'),str(pml),
                '--out',str(pml.with_suffix('.png')),'--session-out',str(pml.with_suffix('.pse')),
                '--contact-residue-labels','--pymol','pymol']
            result = subprocess.run(command,env=env,capture_output=True,text=True,timeout=90)
            (pml.parent/'bold-callout-render.log').write_text(result.stdout+'\n'+result.stderr)
            if result.returncode: raise ValueError('Bold callout render failed: '+result.stderr)
            assert json.loads(labels.read_text()) == old, 'Label positions/identities changed'
            record['figures'].append({'png':str(pml.with_suffix('.png')),'sha256':digest(pml.with_suffix('.png'))})
            save()
        assert len(record['figures'])==6
        for analysis in sorted(study.glob('compounds/*/pose_analysis')):
            rows = list(csv.DictReader((analysis/'cluster_summary.csv').open()))
            output = study/'report'/(analysis.parent.name+'_top3_3d_snapshots.png')
            assert figures.combine_cluster_snapshots(analysis,rows,output)
        report = load('bold_pdf_report','libexec/docking-universal-pdf-report.py')
        pdf = ROOT/'output/pdf/2R8N-docking-report-bold-labels.pdf'
        assert not pdf.exists()
        run = subprocess.run
        def retained(command,*args,**kwargs):
            if len(command)>1 and Path(command[1]).name=='docking-universal-report-figures.py':
                return subprocess.CompletedProcess(command,0,'Retained figures, updated bold-label composites','')
            return run(command,*args,**kwargs)
        with patch.object(sys,'argv',[str(ROOT/'libexec/docking-universal-pdf-report.py'),str(study),'--out',str(pdf)]), \
                patch.object(report.subprocess,'run',side_effect=retained): report.main()
        assert all(digest(Path(p))==value for p,value in before.items())
        record.update(status='passed',pdf=str(pdf),pdf_sha256=digest(pdf),
                      original_study_files_unchanged=len(before),visual_review='pending')
    except BaseException as exc:
        record.update(status='failed',error=str(exc));raise
    finally: save()
    print(json.dumps(record,indent=2))


if __name__=='__main__': main()
