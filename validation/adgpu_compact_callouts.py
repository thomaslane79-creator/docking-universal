#!/usr/bin/env python3
"""Render the requested closer report callouts without changing structure/camera inputs."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from docking_universal.ad4_gpu import digest

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gui',type=Path,required=True);a=p.parse_args()
    root=a.gui.resolve();out=root/'compact-callout-review';out.mkdir(exist_ok=False)
    screen=Path(json.loads((root/'summary.json').read_text())['screening_report']).parent.parent
    record={'status':'running','font_size_unchanged':40,'label_columns_before':.82,'label_columns_after':.68,'figures':[]}
    def save():(out/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    save()
    env={**os.environ,'PYTHONPATH':str(ROOT/'libexec'),'DOCKING_UNIVERSAL_PYTHON':sys.executable,
         'DOCKING_UNIVERSAL_CLI':str(ROOT/'bin/docking-universal'),'DOCKING_UNIVERSAL_LIBEXEC':str(ROOT/'libexec')}
    try:
        for pml in sorted(screen.glob('compounds/*/pose_analysis/cluster_*/interactions/complex_plip_all_in_one.pml')):
            png=pml.with_suffix('.png');pse=pml.with_suffix('.pse');labels=pml.with_suffix('.residue-labels.json')
            old=json.loads(labels.read_text());before={str(p):digest(p) for p in (pml,pml.parent/'report.xml',pml.parent.parent/'representative.sdf')}
            backup=out/pml.parents[3].name/pml.parent.parent.name;backup.mkdir(parents=True)
            for path in (png,pse,labels):shutil.copy2(path,backup/path.name)
            command=[str(ROOT/'bin/docking-universal'),'render3d',str(pml),'--out',str(png),
                     '--session-out',str(pse),'--contact-residue-labels','--pymol','pymol']
            result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=60)
            (backup/'render.log').write_text(result.stdout+'\n'+result.stderr)
            if result.returncode:raise ValueError('Compact label rendering failed')
            new=json.loads(labels.read_text())
            if len(new)!=len(old) or [x['label'] for x in new]!=[x['label'] for x in old]:raise ValueError('Label identities changed')
            if any(digest(path)!=value for path,value in before.items()):raise ValueError('Callout change altered scientific inputs')
            record['figures'].append({'png':str(png),'labels':len(new),'sha256':digest(png),'structure_inputs_unchanged':True})
            save()
        record['status']='completed_compact_callout_rendering'
    except BaseException as exc:
        record.update(status='failed',error=str(exc));raise
    finally:save()
    print(json.dumps(record,indent=2))


if __name__=='__main__':main()
