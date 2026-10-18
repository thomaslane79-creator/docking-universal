"""Bounded experimental AD4 GPU method; never a Vina fallback or score rewrite.

The first supported profile is dry rigid-receptor docking of ordinary mapped
ligands on Apple Silicon. Native XML/PDBQT files and build identity stay retained.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET


ENGINE = "adgpu"
ENGINE_LABEL = "AutoDock-GPU (AD4, experimental)"
PINNED_ENGINE_SHA256 = "062b5816f8342fa4c2150d65852e83f52940fe2f2cb603710e27527b33a9d02a"
LIGAND_TYPES = frozenset(("A", "C", "HD", "N", "NA", "OA", "S", "SA", "F", "Cl", "Br", "I", "P"))
RECEPTOR_TYPES = LIGAND_TYPES | {"H", "O"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class Ad4Settings:
    lga_runs: int = 20
    heuristic_cap: int = 12_000_000
    autostop: bool = True
    population: int = 150
    generations: int = 42_000
    local_iterations: int = 300
    grid_spacing: float = 0.375

    def validate(self):
        for name, low, high in (("lga_runs",1,100),("heuristic_cap",1000,100_000_000)):
            value=getattr(self,name)
            if isinstance(value,bool) or not isinstance(value,int) or not low<=value<=high:
                raise ValueError(f"AD4 {name} must be an integer from {low} to {high}")
        if not isinstance(self.autostop,bool):raise ValueError("AD4 autostop must be boolean")
        if (self.population,self.generations,self.local_iterations,self.grid_spacing)!=(150,42000,300,.375):
            raise ValueError("Unsupported experimental AD4 profile; population/local search/grid spacing are fixed")

    def to_dict(self):
        self.validate();return asdict(self)


def read_settings(parameters):
    if "ad4" not in parameters:
        raise ValueError("AD4 protocol lacks explicit AD4 search settings; Vina settings cannot substitute")
    try:
        settings = Ad4Settings(**parameters["ad4"])
    except TypeError as exc:
        raise ValueError("AD4 search settings must contain only supported profile fields") from exc
    settings.validate()
    return settings


def atom_inventory(path, *, receptor=False):
    atoms=[]
    for line in Path(path).read_text().splitlines():
        if line.startswith(("ATOM  ","HETATM")):
            xyz=tuple(float(line[i:i+8]) for i in (30,38,46));charge=float(line[70:76]);kind=line[77:].strip()
            if not all(math.isfinite(v) for v in (*xyz,charge)):raise ValueError("Nonfinite AD4 coordinates/charge")
            atoms.append((line[:30],xyz,charge,kind))
    if not atoms:raise ValueError("Empty AD4 atom inventory")
    unsupported=sorted({a[3] for a in atoms}-(RECEPTOR_TYPES if receptor else LIGAND_TYPES))
    if unsupported:raise ValueError("Unsupported experimental AD4 atom types: "+", ".join(unsupported)+". Macrocycle pseudoatoms, metals and special parameters are not validated; no fallback was run.")
    return atoms


def typed_ligand(text):
    from meeko import PDBQTMolecule, RDKitMolCreate
    from rdkit import Chem
    molecules=RDKitMolCreate.from_pdbqt_mol(PDBQTMolecule(text,skip_typing=True))
    if len(molecules)!=1 or molecules[0] is None:raise ValueError("AD4 requires one Meeko-mapped ligand")
    mol=Chem.RemoveHs(molecules[0])
    if any(len(ring)>=8 for ring in mol.GetRingInfo().AtomRings()):
        raise ValueError("Macrocycles are not validated for the experimental AD4 option; their treatment will not be silently changed")
    return mol


def checked_pose(template, native_pose):
    from rdkit import Chem
    before=atom_inventory(template);after=atom_inventory(native_pose)
    if len(before)!=len(after) or any(a[0]!=b[0] or a[2:]!=b[2:] for a,b in zip(before,after)):
        raise ValueError("AD4 output changed atom identity/order, charge or type")
    initial=typed_ligand(Path(template).read_text());mol=typed_ligand(Path(native_pose).read_text())
    expected=Chem.MolToSmiles(initial,isomericSmiles=True)
    if Chem.MolToSmiles(mol,isomericSmiles=True)!=expected:raise ValueError("AD4 output changed mapped chemical identity")
    geometry=Chem.Mol(mol);Chem.AssignStereochemistryFrom3D(geometry,replaceExistingTags=True)
    Chem.AssignStereochemistry(geometry,cleanIt=True,force=True)
    if Chem.MolToSmiles(geometry,isomericSmiles=True)!=expected:raise ValueError("AD4 output coordinate stereochemistry changed")
    return mol


def grid_geometry(box, spacing=.375):
    center=[float(box['center_'+a]) for a in 'xyz'];requested=[float(box['size_'+a]) for a in 'xyz']
    if not all(math.isfinite(v) for v in center+requested) or min(requested)<=0:raise ValueError("Invalid AD4 grid geometry")
    intervals=[2*math.ceil(v/(2*spacing)) for v in requested]
    if max(intervals)>256:raise ValueError("AD4 grid exceeds the bounded experimental size limit")
    return {"spacing_angstrom":spacing,"center":center,"requested_size":requested,
            "grid_intervals":intervals,"actual_size":[v*spacing for v in intervals],
            "policy":"Round intervals up to even cells; actual extents are separately locked and reported"}


def grid_parameter_text(geometry, receptor_types, ligand_types):
    from meeko.gridbox import get_gpf_string
    text,npts=get_gpf_string(geometry['center'],geometry['actual_size'],'receptor.pdbqt',
                           sorted(receptor_types),sorted(ligand_types),map_prefix='receptor')
    if list(npts)!=geometry['grid_intervals']:raise ValueError("Unexpected AD4 grid rounding")
    return re.sub(r'^gridcenter .*','gridcenter '+' '.join(f'{x:.6f}' for x in geometry['center']),text,flags=re.M)


def native_arguments(engine, maps, settings, seed):
    settings.validate()
    if isinstance(seed,bool) or not isinstance(seed,int) or not 0<=seed<=2**32-1:raise ValueError("AD4 seed must fit an unsigned 32-bit integer")
    return list(map(str,[engine,'--ffile',maps,'--lfile','ligand.pdbqt','--resnam','result',
        '--seed',seed,'--devnum',1,'--nrun',settings.lga_runs,'--psize',settings.population,
        '--ngen',settings.generations,'--lsmet','ad','--lsrat',100,'--lsit',settings.local_iterations,
        '--npdb',1,'--gbest',0,'--gfpop',1,'--rmstol',1.5,'--output-cluster-poses',0,
        '--heuristics',1,'--heurmax',settings.heuristic_cap,'--autostop',int(settings.autostop)]))


def parse_native_ranking(path, expected_runs):
    root=ET.parse(path).getroot()
    if int(root.findtext('run_requested'))!=expected_runs:raise ValueError("AD4 run count differs from the locked method")
    rows=[]
    for run in root.findall('./runs/run'):
        row={"native_run":int(run.attrib['id']),"binding_energy_kcal_mol":float(run.findtext('free_NRG_binding')),
             "intermolecular_kcal_mol":float(run.findtext('final_intermol_NRG')),
             "internal_kcal_mol":float(run.findtext('internal_ligand_NRG')),
             "torsional_kcal_mol":float(run.findtext('torsonial_free_NRG'))}
        if not all(math.isfinite(v) for v in row.values()):raise ValueError("Nonfinite AD4 energy")
        if abs(row['binding_energy_kcal_mol']-row['intermolecular_kcal_mol']-row['torsional_kcal_mol'])>.0151:
            raise ValueError("Unexpected dry freely roaming AD4 binding-energy convention")
        rows.append(row)
    if len(rows)!=expected_runs or {r['native_run'] for r in rows}!=set(range(1,expected_runs+1)):
        raise ValueError("Missing or duplicate AD4 run winners")
    if any(a['binding_energy_kcal_mol']>b['binding_energy_kcal_mol']+.0001 for a,b in zip(rows,rows[1:])):
        raise ValueError("AD4 native ranking is not energy ordered")
    # Preserve XML order, including rounded ties. Never sort by crystal RMSD.
    return rows


def assemble_results(native_root, template, output, settings):
    """Engine-neutral model indices retain exact native-run provenance."""
    rows=parse_native_ranking(Path(native_root)/'result.xml',settings.lga_runs)
    parts=[]
    for model,row in enumerate(rows,1):
        pose=Path(native_root)/f"ligand_docked_run{row['native_run']}_entity1.pdbqt"
        checked_pose(template,pose)
        text=pose.read_text()
        if any(line.startswith(('MODEL','ENDMDL','REMARK VINA RESULT:')) for line in text.splitlines()):
            raise ValueError("Unexpected native AD4 model/score annotations")
        row.update(model=model,native_pose=str(pose.resolve()),native_pose_sha256=digest(pose))
        parts.append(f"MODEL {model}\nREMARK AD4 RESULT: {row['binding_energy_kcal_mol']:.2f}\nREMARK AD4 NATIVE RUN: {row['native_run']}\n"+text.rstrip()+"\nENDMDL\n")
    output=Path(output);temporary=output.with_suffix(output.suffix+'.partial')
    temporary.write_text(''.join(parts));temporary.replace(output)
    record={"schema":"docking-universal-engine-results-v1","engine":ENGINE,"scoring_function":"AD4",
            "energy_units":"kcal/mol","energy_meaning":"AD4 estimated binding energy; not GPU total search energy",
            "output_sha256":digest(output),"native_xml":str((Path(native_root)/'result.xml').resolve()),
            "native_xml_sha256":digest(Path(native_root)/'result.xml'),"template_sha256":digest(template),
            "settings":settings.to_dict(),"poses":rows}
    output.with_suffix(output.suffix+'.json').write_text(json.dumps(record,indent=2)+'\n')
    return record


def runtime_descriptor(environment=None, *, allow_validation=False):
    """Only a locally configured, pinned, explicitly experimental installation."""
    environment=os.environ if environment is None else environment
    if 'DOCKING_UNIVERSAL_ADGPU_CONFIG' in environment:
        # An explicit missing override is intentional (including isolated tests):
        # do not fall back to a different installation or HOME configuration.
        path=Path(environment['DOCKING_UNIVERSAL_ADGPU_CONFIG'])
    else:
        local=Path(sys.prefix)/'share/docking-universal/adgpu/runtime.json'
        path=local if local.is_file() else Path.home()/'.config/docking-universal/adgpu.json'
    if not path.is_file():raise ValueError("Experimental AD4 GPU is not configured; Vina has not been substituted")
    record=json.loads(path.read_text())
    if not isinstance(record, dict):
        raise ValueError('Experimental AD4 runtime configuration must be an object')
    validation=(allow_validation and environment.get('DOCKING_UNIVERSAL_ADGPU_VALIDATION')=='1'
                and record.get('validation_only') is True)
    if record.get('schema')!='docking-universal-adgpu-runtime-v1' or not (record.get('integration_accepted') is True or validation):
        raise ValueError("Experimental AD4 GPU has not passed local integration acceptance")
    engine=Path(record['executable']).expanduser().resolve()
    if platform.system()!='Darwin' or platform.machine()!='arm64':raise ValueError("This experimental AD4 build requires Apple-Silicon macOS")
    version=platform.mac_ver()[0]
    if not version or tuple(int(p) for p in version.split('.')[:2]) < (26,2):
        raise ValueError('The pinned experimental AD4 build requires macOS 26.2 or newer')
    if not engine.is_file() or not os.access(engine,os.X_OK) or digest(engine)!=PINNED_ENGINE_SHA256:
        raise ValueError("Experimental AD4 executable differs from the tested patched 128-work-item build")
    if record.get('autogrid_executable'):
        autogrid=Path(record['autogrid_executable'])
        if (not autogrid.is_file() or not os.access(autogrid,os.X_OK)
                or digest(autogrid)!=record.get('autogrid_sha256')):
            raise ValueError('Installed AutoGrid executable is missing or differs from its installation record')
    return {**record,'executable':str(engine)}


def available(environment=None):
    try:runtime_descriptor(environment,allow_validation=True);return True
    except (ValueError,OSError,KeyError,json.JSONDecodeError):return False


def run_prepared_batch(options, invocation, environment, stdout, stderr):
    """Sequential native jobs with one map set, hash-checked skip, no fallback."""
    from datetime import datetime, timezone
    import time
    from docking_universal_dock import DockBatchResult, DockRuntimeError
    settings=Ad4Settings(**(options.ad4_settings or {}));settings.validate()
    configured=runtime_descriptor(environment,allow_validation=True)
    if tuple(invocation.command)!=(configured['executable'],):raise DockRuntimeError('AD4 runtime/executable identity mismatch')
    if any(getattr(options,key) is not None for key in ('exhaustiveness','num_modes','energy_range','cpu','vina_backend')):
        raise DockRuntimeError('AD4 requires AD4 settings, not Vina exhaustiveness, pose windows, CPU counts or backends')
    seed=int(options.seed) if options.seed is not None else 20260808
    ligands=sorted(options.ligand_dir.glob('*.pdbqt'))
    if not ligands:raise DockRuntimeError('No prepared AD4 ligand inputs')
    receptor_atoms=atom_inventory(options.receptor,receptor=True)
    ligand_types=set()
    # Validate the complete batch before map generation or any search.
    for ligand in ligands:
        ligand_types.update(a[3] for a in atom_inventory(ligand))
        typed_ligand(ligand.read_text())
    box={}
    ignored=[]
    for line in options.config.read_text().splitlines():
        clean=line.split('#',1)[0]
        if '=' not in clean:continue
        key,value=map(str.strip,clean.split('=',1))
        if key in {'center_'+a for a in 'xyz'}|{'size_'+a for a in 'xyz'}:box[key]=float(value)
        else:ignored.append(key)
    geometry=grid_geometry(box,settings.grid_spacing)
    out=options.output_dir;out.mkdir(parents=True,exist_ok=True)
    maproot=out/'ad4_maps'
    autogrid=(environment.get('DOCKING_UNIVERSAL_AUTOGRID') or configured.get('autogrid_executable')
              or shutil.which('autogrid4',path=environment.get('PATH')))
    if not autogrid or not Path(autogrid).is_file():raise DockRuntimeError('AutoGrid4 is required for AD4 maps; no Vina fallback was run')
    input_hashes={'receptor':digest(options.receptor),'box':digest(options.config),
                  **{'ligand:'+p.name:digest(p) for p in ligands}}
    request={'engine':ENGINE,'executable_sha256':PINNED_ENGINE_SHA256,'settings':settings.to_dict(),
             'autogrid':{'executable':str(Path(autogrid).resolve()),'sha256':digest(autogrid)},
             'seed':seed,'input_hashes':input_hashes,'grid':geometry,'ignored_non_geometry_box_keys':ignored}
    request_hash=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
    manifest=out/'ad4_batch.json'
    previous=json.loads(manifest.read_text()) if manifest.is_file() else None
    if previous and (not options.skip_existing or previous.get('request_sha256')!=request_hash):
        raise DockRuntimeError('AD4 output already exists or its method/inputs changed; choose a new output folder')
    if previous and previous.get('status') != 'completed':
        raise DockRuntimeError('Incomplete or failed AD4 batch retained; choose a new output folder, not an automatic restart')
    if previous:
        from uuid import uuid4
        # Keep previous completion provenance even if a later integrity check fails.
        shutil.copy2(manifest, out/f'ad4_batch.previous-{uuid4().hex}.json')
    state={**request,'schema':'docking-universal-ad4-batch-v1','request_sha256':request_hash,
           'status':'running','started_utc':datetime.now(timezone.utc).isoformat(),'jobs':[],
           'scoring_function':'AD4','energy_units':'kcal/mol','validation_only':configured.get('validation_only',False)}
    def save_state():manifest.write_text(json.dumps(state,indent=2)+'\n')
    def run(command,folder,log):
        started=time.monotonic()
        with log.open('wb') as stream:
            result=subprocess.run(list(map(str,command)),cwd=folder,env=dict(environment),stdout=stream,stderr=subprocess.STDOUT)
        if result.returncode:raise DockRuntimeError(f'AD4 stage failed ({result.returncode}); see {log}. No fallback or retry was run.')
        return time.monotonic()-started
    save_state()
    try:
        if maproot.exists():
            if not previous or not previous.get('map_hashes'):raise DockRuntimeError('Incomplete AD4 map directory; use a new output folder')
            for file,expected in previous['map_hashes'].items():
                if digest(file)!=expected:raise DockRuntimeError('Retained AD4 maps changed')
            state['map_hashes']=previous['map_hashes'];state['map_seconds']=0.;state['maps_reused']=True
        else:
            maproot.mkdir();shutil.copy2(options.receptor,maproot/'receptor.pdbqt')
            (maproot/'receptor.gpf').write_text(grid_parameter_text(geometry,{a[3] for a in receptor_atoms},ligand_types))
            state['map_seconds']=run([autogrid,'-p','receptor.gpf','-l','receptor.glg'],maproot,maproot/'autogrid.log')
            if 'Successful Completion' not in (maproot/'receptor.glg').read_text():raise DockRuntimeError('AutoGrid completion not confirmed')
            state['map_hashes']={str(p.resolve()):digest(p) for p in maproot.glob('receptor.*.map')}
            if len(state['map_hashes'])!=len(ligand_types)+2:raise DockRuntimeError('AD4 affinity-map inventory incomplete')
            for name in ('receptor.maps.fld', 'receptor.gpf', 'receptor.pdbqt'):
                state['map_hashes'][str((maproot/name).resolve())]=digest(maproot/name)
        save_state();successful=failed=skipped=0
        for ligand in ligands:
            output=out/f'{ligand.stem}_adgpu.pdbqt';native=out/'ad4_native'/ligand.stem
            prior=next((row for row in (previous or {}).get('jobs',[]) if row['ligand']==str(ligand.resolve())),None)
            if options.skip_existing and prior and prior['status'] in ('completed','skipped'):
                metadata=output.with_suffix(output.suffix+'.json')
                if not output.is_file() or not metadata.is_file() or digest(output)!=prior['output_sha256'] or digest(metadata)!=prior['metadata_sha256']:
                    raise DockRuntimeError('AD4 skipped result changed; use a new output folder')
                state['jobs'].append({**prior,'status':'skipped'});skipped+=1;print('skip  '+ligand.stem,file=stdout,flush=True);save_state();continue
            if native.exists() or output.exists():raise DockRuntimeError('Partial/failed AD4 job retained; choose a new output folder, not an automatic restart')
            native.mkdir(parents=True);shutil.copy2(ligand,native/'ligand.pdbqt')
            row={'ligand':str(ligand.resolve()),'output':str(output.resolve()),'status':'running'};state['jobs'].append(row);save_state()
            print('run   '+ligand.stem+' [AD4 GPU]',file=stdout,flush=True)
            try:
                command=native_arguments(configured['executable'],(maproot/'receptor.maps.fld').resolve(),settings,seed)
                row['command']=command;row['wall_seconds']=run(command,native,native/'adgpu.log')
                text=(native/'adgpu.log').read_text()
                if not re.search(r'OpenCL device:\s+Apple ',text) or 'All jobs ran without errors.' not in text:
                    raise DockRuntimeError('Native Apple GPU execution/completion not confirmed')
                assembled=assemble_results(native,ligand,output,settings)
                row.update(status='completed',pose_count=len(assembled['poses']),output_sha256=digest(output),
                           metadata_sha256=digest(output.with_suffix(output.suffix+'.json')))
                successful+=1
            except (ValueError,OSError,ET.ParseError,DockRuntimeError) as error:
                row.update(status='failed',error=str(error));failed+=1
                print(str(error),file=stderr,flush=True)
            save_state()
        state['status']='completed_with_failures' if failed else 'completed'
        for key,expected in input_hashes.items():
            path=options.receptor if key=='receptor' else options.config if key=='box' else options.ligand_dir/key.removeprefix('ligand:')
            if digest(path)!=expected:raise DockRuntimeError('AD4 scientific input changed during execution')
        for file,expected in state['map_hashes'].items():
            if digest(file)!=expected:raise DockRuntimeError('AD4 map changed during execution')
        return DockBatchResult(out,successful,failed,skipped)
    except BaseException as error:
        state.update(status='failed',error=str(error));raise
    finally:
        state['finished_utc']=datetime.now(timezone.utc).isoformat();save_state()
