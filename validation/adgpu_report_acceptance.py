#!/usr/bin/env python3
"""Report-only final QA correction and exact native-to-review pose audit."""
import argparse
import csv
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
from rdkit import Chem
from docking_universal.ad4_gpu import digest, typed_ligand
from docking_universal.state import JsonStudyStore

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gui',type=Path,required=True)
    p.add_argument('--audit-name',default='final-report-pose-audit.json')
    p.add_argument('--verify-existing-protocol-copy',action='store_true')
    a=p.parse_args()
    root=a.gui.resolve();record=json.loads((root/'summary.json').read_text())
    if record['status']!='completed_gui_acceptance':raise ValueError('GUI acceptance has not completed')
    audit_path=root/a.audit_name
    if audit_path.exists():raise ValueError('Final report audit already exists')
    result={'status':'running','redocking_performed':False,'compounds':[]}
    def save():audit_path.write_text(json.dumps(result,indent=2)+'\n')
    save()
    screen=Path(record['screening_report']).parent.parent
    raw={str(p):digest(p) for p in screen.glob('compounds/*/seed_*/docking/**/*') if p.is_file()}
    try:
        spec=importlib.util.spec_from_file_location('report_acceptance_run',ROOT/'libexec/docking-universal-run.py')
        runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
        summary=screen/'report/study_summary.json';source=json.loads(summary.read_text())
        retained=runner.retain_materialized_protocol(Path(source['approved_protocol']),screen,
                    allow_verified_existing=a.verify_existing_protocol_copy)
        for path in (summary,screen/'study_manifest.json'):
            data=json.loads(path.read_text());data['approved_protocol']=str(retained)
            data['approved_protocol_sha256']=digest(retained)
            path.write_text(json.dumps(data,indent=2)+'\n')
        backup=root/('before-'+audit_path.stem);backup.mkdir()
        env={**os.environ,'PYTHONPATH':str(ROOT/'libexec'),'DOCKING_UNIVERSAL_PYTHON':sys.executable,
             'DOCKING_UNIVERSAL_CLI':str(ROOT/'bin/docking-universal'),'DOCKING_UNIVERSAL_LIBEXEC':str(ROOT/'libexec')}
        for key in ('protocol_report','screening_report'):
            pdf=Path(record[key]);shutil.copy2(pdf,backup/pdf.name)
            proc=subprocess.run([sys.executable,str(ROOT/'libexec/docking-universal-pdf-report.py'),str(pdf.parent.parent),'--out',str(pdf)],env=env,capture_output=True,text=True)
            (root/(key+'-finalization.log')).write_text(proc.stdout+'\n'+proc.stderr)
            if proc.returncode:raise ValueError(key+' generation failed')
            text=subprocess.run(['/opt/homebrew/bin/pdftotext',str(pdf),'-'],capture_output=True,text=True,check=True).stdout
            text=' '.join(text.split())
            for phrase in ('AutoDock-GPU','AD4','Genetic runs per repeat','Heuristic evaluation cap','26.25'):
                if phrase not in text:raise ValueError(key+' omitted '+phrase)
            if 'Exhaustiveness NA' in text:raise ValueError('Vina NA fields remain in AD4 report')
        for analysis in sorted(screen.glob('compounds/*/pose_analysis')):
            rows=list(csv.DictReader((analysis/'pose_inventory.csv').open()))
            poses=list(Chem.SDMolSupplier(str(analysis/'all_poses.sdf'),removeHs=True))
            if len(rows)!=20 or len(poses)!=20 or any(m is None for m in poses):raise ValueError('Shared export lost a native winner')
            sources={r['source']:typed_ligand(Path(r['source']).read_text()) for r in rows}
            errors=[]
            for row,pose in zip(rows,poses):
                native=sources[row['source']];model=int(row['model'])-1
                if Chem.MolToSmiles(native)!=Chem.MolToSmiles(pose):raise ValueError('Shared export changed graph/stereo')
                errors.append(float(np.max(np.abs(native.GetConformer(model).GetPositions()-pose.GetConformer().GetPositions()))))
                if abs(float(row['energy_kcal_per_mol'])-pose.GetDoubleProp('DockingUniversal_Energy'))>1e-9:raise ValueError('Shared pose energy identity changed')
            if max(errors)>0.00011:raise ValueError('Shared export changed native coordinates')
            representatives=[]
            for cluster in sorted(analysis.glob('cluster_*')):
                if not cluster.is_dir():continue
                meta=json.loads((cluster/'cluster.json').read_text());index=meta['representative_index']
                mol=next(iter(Chem.SDMolSupplier(str(cluster/'representative.sdf'),removeHs=True)))
                if np.max(np.abs(mol.GetConformer().GetPositions()-poses[index].GetConformer().GetPositions()))>1e-9:raise ValueError('Representative is not its recorded exact pose')
                diagram=cluster/'interactions/representative_plip2d.png'
                manifest=json.loads(diagram.with_suffix('.manifest.json').read_text())
                if manifest.get('renderer_policy')!='approved-poseedit-local-v1' or manifest.get('collision_count')!=0:raise ValueError('Representative lacks approved collision-free 2D rendering')
                labels=json.loads((cluster/'interactions/complex_plip_all_in_one.residue-labels.json').read_text())
                if not labels:raise ValueError('PLIP 3D residue callouts missing')
                representatives.append({'cluster_id':meta['cluster_id'],'source_model':meta['representative']['model'],
                    'representative_sha256':digest(cluster/'representative.sdf'),'diagram_sha256':digest(diagram),
                    'plip_sha256':digest(cluster/'interactions/report.xml'),'residue_label_count':len(labels),
                    'renderer_policy':manifest['renderer_policy'],'ligand_spacing':manifest['ligand_spacing']})
            result['compounds'].append({'id':analysis.parent.name,'pose_count':len(rows),
                'maximum_native_export_coordinate_error_angstrom':max(errors),'representatives':representatives})
        if any(digest(path)!=value for path,value in raw.items()):raise ValueError('Report correction changed raw docking output')
        store=JsonStudyStore(root/'state')
        def refreshed(state):
            from dataclasses import replace
            state.artifacts=[replace(a,sha256=digest(a.path)) if Path(a.path).is_file() and
                (screen in Path(a.path).parents or root/'protocol/report' in Path(a.path).parents or
                 Path(a.path)==screen/'study_manifest.json') else a for a in state.artifacts]
        store.update('ad4-gui-acceptance',refreshed)
        result.update(status='completed_report_and_pose_acceptance',raw_docking_unchanged=True,
                      retained_protocol=str(retained),retained_protocol_sha256=digest(retained),
                      protocol_report=record['protocol_report'],screening_report=record['screening_report'])
    except BaseException as exc:
        result.update(status='failed',error=str(exc));raise
    finally:save()
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
