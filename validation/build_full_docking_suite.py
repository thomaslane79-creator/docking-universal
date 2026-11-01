"""Plan 100 real GUI docking workflows; never substitute component checks.

The first 20 reuse an already reviewed 2R8N protocol with new public CCD ligands.
Other targets stay unbound until the reference-site policy is explicitly approved
and real matching protocols are prepared/reviewed. No scientific job runs here.
"""
import copy
import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from rdkit import Chem

import system_validation as system

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'validation/local/full-docks-100-20261022'
CCD=ROOT/'smoke_runs/mmcif_2r8n_run_file/preparation/2R8N_receptor_prep/cavity/pdb_site_evidence/ccd'


def pin(path):
    return {'path':str(Path(path).resolve()),'sha256':system.sha(path)}


def library(folder, component, source, kind, large=False):
    folder.mkdir(parents=True,exist_ok=False)
    original=next(iter(Chem.SDMolSupplier(str(source),removeHs=True)),None)
    if original is None:raise ValueError('Unreadable CCD chemistry: '+component)
    smiles=Chem.MolToSmiles(original,isomericSmiles=True)
    molecule=Chem.MolFromSmiles(smiles)
    if molecule is None:raise ValueError('CCD graph cannot be rebuilt')
    name='CCD '+component
    molecule.SetProp('_Name',name)
    # Rebuild from chemical identity; never seed preparation from bound poses.
    assert molecule.GetNumConformers()==0
    path=folder/('input-records.'+kind)
    index=72 if large else 0
    mapping=None
    if kind in {'sdf','mol'}:
        if kind=='mol':Chem.MolToMolFile(molecule,str(path))
        else:
            with Chem.SDWriter(str(path)) as writer:
                writer.write(molecule)
                decoy=Chem.MolFromSmiles('CCO');decoy.SetProp('_Name','Unselected decoy');writer.write(decoy)
    elif kind in {'csv','tsv'}:
        with path.open('w',newline='') as stream:
            writer=csv.writer(stream,delimiter=',' if kind=='csv' else '\t')
            writer.writerow(['Name','SMILES','Other chemistry'])
            for row in range(1000 if large else 3):
                writer.writerow([name if row==index else 'Unselected '+str(row),
                                 smiles if row==index else ('not_smiles' if row==1 else 'CCO'),'CCN'])
        mapping={'smiles_column':1,'name_column':0}
    elif kind=='xlsx':
        # Reuse the existing real Excel parser fixture, preserving its invalid,
        # numeric and formula rows as unselected library entries.
        namespace='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
        with zipfile.ZipFile(ROOT/'tests/fixtures/ligand_tables.xlsx') as template,zipfile.ZipFile(path,'w') as target:
            for item in template.infolist():
                data=template.read(item.filename)
                if item.filename=='xl/worksheets/sheet2.xml':
                    tree=ET.fromstring(data)
                    for cell in tree.iter(namespace+'c'):
                        if cell.get('r') in {'A2','B2'}:
                            cell.set('t','str')
                            cell.find(namespace+'v').text=name if cell.get('r')=='A2' else smiles
                    data=ET.tostring(tree,encoding='utf-8',xml_declaration=True)
                target.writestr(item,data)
        mapping={'smiles_column':1,'name_column':0,'sheet':'Compounds'}
    else:raise ValueError('Unknown library format')
    return path,index,mapping,name,smiles


def main():
    OUT.mkdir(parents=True,exist_ok=False)
    baseline=json.loads((ROOT/'validation/local/systematic-mac-20261022.json').read_text())
    template=next(c for c in baseline['cases'] if c['id']=='2r8n-screen-vina')
    cases=[]
    choices=[('JE2','csv'),('016','mol'),('075','tsv'),('O33','xlsx'),('1UN','sdf'),
             ('JZP','csv'),('UNI','mol'),('006','tsv'),('JHG','xlsx'),('JZQ','sdf')]
    for component,kind in choices:
        source=CCD/(component+'_ideal.sdf')
        path,index,mapping,name,smiles=library(OUT/'libraries'/component,component,source,kind,large=component=='JZP')
        for engine in ['vina','qvinaw']:
            case=copy.deepcopy(template)
            case.update(id=f'full-{len(cases)+1:03d}-2r8n-{component.lower()}-{engine}',engine=engine,
                        requires=['desktop'], max_jobs=1, selected_record_indices=[index],
                        expected_source_name=name,expected_input_smiles=smiles,
                        start_path='reviewed protocol import',cohort='100 actual docking workflows',
                        input_format=kind,
                        features=['real new docking','ligand preparation','clusters','PLIP','2D','PDF','native 3D','fresh-host reopen',
                                  'explicit subset selection']+(['1000-record pagination'] if index else []))
            protocol=ROOT/f'validation/runs/mac-all-engine-gui-20261022-native-b/{engine}/protocol/2R8N_site-guided-exploratory_{engine}.duprotocol'
            case['inputs']={'protocol':pin(protocol),'ligands':pin(path),'source-ccd':pin(source)}
            if mapping:case['column_mapping']=mapping
            case['checks'][1]['equals']=engine
            case['checks'] += [{'kind':'json','path':'worker/summary.json','keys':['real_screening_started'],'equals':True},
                               {'kind':'json','path':'worker/summary.json','keys':['workload','compound_count'],'equals':1},
                               {'kind':'json','path':'worker/summary.json','keys':['workload','total_docking_jobs'],'equals':1}]
            cases.append(case)
    # Fixed cohort slots, not passable placeholders. Each target must be bound
    # through an actually reviewed matching protocol before its work can run.
    for target,component in [('2R5P','MK1'),('2O4P','TPV'),('1MRW','K57'),('1IEP','STI'),('1YET','GDM')]:
        engines=['vina']*6+['qvinaw']*6+['adgpu']*4
        for local,engine in enumerate(engines):
            case=copy.deepcopy(template)
            case.update(id=f'full-{len(cases)+1:03d}-{target.lower()}-{engine}-{local+1:02d}',target=target,engine=engine,
                        inputs={},import_review_approved=False,exploratory_authorized=False,
                        requires=['desktop']+(['ad4_gpu'] if engine=='adgpu' else []),
                        intended_anchor_component=component,
                        binding_requirement='Explicit reference-site policy approval and a real matching reviewed protocol; no control authority granted',
                        planned_scope='Complete molecular workflow, not a component test',
                        preparation_interventions_allowed=False,max_jobs=50)
            case['checks'][1]['equals']=engine
            cases.append(case)
    assert len(cases)==100 and len({c['id'] for c in cases})==100
    suite={'schema':system.SCHEMA,'name':'100 full docking workflows — molecular cases only',
           'profile':baseline['profile'],'cases':cases,
           'counting_rule':'Only real completed docking workflows count; software checks, blocked/excluded/preflight-only cases never count',
           'engine_slots':{'vina':40,'qvinaw':40,'adgpu':20},
           'scope':'Functional GUI/pipeline validation, not affinity accuracy or production control calibration',
           'reference_site_policy_approved':False,
           'preparation_policy':'Reference-target binding and fresh-input paths require explicit review; do not invent approval or repair chemistry'}
    system.write(OUT/'planned-100.json',suite)
    first=copy.deepcopy(suite);first['name']='First 20 of 100 real docking workflows — already reviewed site only';first['cases']=cases[:20]
    system.write(OUT/'phase-a-20-reviewed.json',first)
    pilot=copy.deepcopy(first);pilot['name']='Real docking pilot: explicit CSV subset through installed GUI';pilot['cases']=cases[:1]
    system.write(OUT/'pilot.json',pilot)
    print(json.dumps({'planned':100,'ready_first_phase':20,'new_target_slots_require_review':80,
                      'engines':suite['engine_slots'],'local':str(OUT)},indent=2))


if __name__=='__main__':
    main()
