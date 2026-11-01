"""Build the bounded, offline 2026-10-22 expansion from retained reviewed inputs.

No downloads, preparation, scientific decisions or calculations occur here.
Output files are ignored local validation configuration/data, not release assets.
"""
import copy
import hashlib
import json
from pathlib import Path

from rdkit import Chem

from redock_prepared_ab import verify_coordinate_frame
from prepared_engine_worker import load_manifest, search_command

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / 'validation/local/expanded-20261022'


def pin(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def main():
    LOCAL.mkdir(parents=True, exist_ok=False)
    source = json.loads((ROOT/'validation/local/systematic-mac-20261022.json').read_text())
    profile = source['profile']
    cases = []
    entries = [
        ('indinavir', '2R5P', ROOT/'validation/runs/conformer-ab/indinavir_2r5p_redocking_20261004_framechecked'),
        *[(name, pdb, ROOT/'validation/runs/conformer-ab/four_more_20261005_ready'/folder/'benchmark')
          for name, pdb, folder in [('tipranavir','2O4P','tipranavir_2o4p'),
                                    ('kni577','1MRW','kni577_1mrw'),
                                    ('imatinib','1IEP','imatinib_1iep'),
                                    ('geldanamycin','1YET','geldanamycin_1yet')]]]
    for name, pdb, benchmark in entries:
        summary = json.loads((benchmark/'summary.json').read_text())
        if summary['status'] != 'completed':
            raise ValueError('Historical source is not completed: ' + name)
        first = benchmark/'vacuum_pruned/dock_conf_01'
        command = json.loads((first/'seed_41001/vina.command.json').read_text())
        options = dict(zip(command[1::2], command[2::2]))
        receptor = Path(options['--receptor']).parent
        compare = json.loads((first/'seed_41001/compare.command.json').read_text())
        comparison_options = dict(zip(compare[2::2], compare[3::2]))
        inputs = {key: pin(path) for key, path in {
            'source-summary': benchmark/'summary.json', 'receptor-raw': receptor/'receptor_raw.pdb',
            'receptor-pdb': receptor/'receptor.pdb', 'receptor-pdbqt': options['--receptor'],
            'box': options['--config'], 'ligand-sdf': first/'ligand.sdf',
            'ligand-pdbqt': options['--ligand'], 'crystal': comparison_options['--crystal-ligand'],
            'comparison-tool': ROOT/'libexec/docking-universal-redock-compare.py',
            'exporter': comparison_options['--mk-export']}.items()}
        verify_coordinate_frame(Path(inputs['receptor-raw']['path']), Path(inputs['receptor-pdbqt']['path']))
        # Flexible-macrocycle CG/G closure atom types are not interchangeable
        # with QuickVina-W's rigid-macrocycle preparation. Do not force them in.
        if name != 'geldanamycin':
            for seed in [41001,41002,41003]:
                inputs[f'command-{seed}'] = pin(first/f'seed_{seed}/vina.command.json')
                inputs[f'baseline-{seed}'] = pin(first/f'seed_{seed}/poses.pdbqt')
            manifest = {'engine':'qvinaw','baseline_engine':'vina',
                        'executable':profile['identity_files']['qvinaw'], 'seeds':[41001,41002,41003],
                        'inputs':inputs,
                        'scope':'One exact previously retained MMFF94 conformer; dry rigid receptor; single chemical state; '
                                'three matched seeds. Retained Vina CPU=1 versus new QuickVina-W CPU=8, original search '
                                'effort/modes/window retained. Descriptive pose recovery, not calibration, speed or superiority proof.'}
            path = LOCAL/(name+'-recovery.json'); save(path, manifest)
            load_manifest(path)
            for seed in manifest['seeds']:
                search_command(manifest, seed, LOCAL/'unused.pdbqt')
            cases.append({'id':name+'-qvinaw-recovery','target':pdb, 'layer':'scientific',
                          'driver':'command','engine':'qvinaw','requires':['cpu'],
                          'inputs':dict(inputs, manifest=pin(path)), 'timeout_seconds':7200,
                          'argv':['{python}','{project}/validation/prepared_engine_worker.py',
                                  '--manifest','{manifest}','--out','{out}/benchmark'],
                          'visual_review_required':False,
                          'checks':[{'kind':'json','path':'benchmark/summary.json','keys':['status'],'equals':'completed'},
                                    {'kind':'json','path':'benchmark/summary.json','keys':['new_searches'],'equals':3},
                                    {'kind':'json','path':'benchmark/summary.json','keys':['original_inputs_unchanged'],'equals':True}],
                          'experimental_metrics':{'path':'benchmark/poses.csv','seeds':[41001,41002,41003],
                                                  'coordinate_basis':'experimental-receptor-frame-no-fit',
                                                  'groups':['arm'],'expected_groups':[{'arm':'retained_vina'},{'arm':'new_qvinaw'}],
                                                  'threshold_angstrom':2.0}})
        # Input chemistry, not crystal coordinates, goes through the usual GUI
        # preparation at protocol pH. A screen on 2R8N is not a crystal-recovery
        # test for imatinib or geldanamycin; their native targets differ.
        molecule = next(iter(Chem.SDMolSupplier(inputs['ligand-sdf']['path'], removeHs=False)))
        if molecule is None:
            raise ValueError('Unreadable retained chemistry')
        molecule.SetProp('_Name', name)
        library = LOCAL/(name+'.sdf')
        with Chem.SDWriter(str(library)) as writer:
            writer.write(molecule)
        for engine in ['vina','qvinaw','adgpu']:
            template = next(c for c in source['cases'] if c['id']=='2r8n-screen-vina')
            case = copy.deepcopy(template)
            case.update(id=name+'-gui-'+engine, engine=engine, max_jobs=1,
                        requires=['desktop']+(['ad4_gpu'] if engine=='adgpu' else []),
                        features=['approved protocol reuse','new larger ligand','native linked review','PDF','reopen'],
                        coverage_note='Exploratory workflow robustness on approved 2R8N P1; not native-target pose recovery')
            protocol = ROOT/f'validation/runs/mac-all-engine-gui-20261022-native-b/{engine}/protocol/2R8N_site-guided-exploratory_{engine}.duprotocol'
            case['inputs'] = {'protocol':pin(protocol),'ligands':pin(library)}
            case['checks'][1]['equals'] = engine
            if name == 'geldanamycin' and engine == 'adgpu':
                case['excluded_reason'] = 'Accepted experimental AD4 profile excludes macrocycles; do not force unsupported chemistry'
            cases.append(case)
    # Retain the real import rejection separately; do not relabel this older
    # absolute-path archive as an accepted portable control protocol.
    cases.append({'id':'biotin-legacy-bundle','target':'1STP','layer':'workflow','driver':'screen_gui',
                  'engine':'vina','inputs':{},'visual_review_required':True,
                  'import_review_approved':False,
                  'preflight_issue':'Preflight rejected old retained bundle: absolute box member path is unsafe; needs a new portable export, not bypass'})
    # Scientific cases first, then independent engine/compound GUI processes.
    cases.sort(key=lambda c: (c['layer']!='scientific',c['id']))
    suite = {'schema':source['schema'],'name':'Expanded local panel: four native-target recovery comparisons and 14 new GUI screens',
             'profile':profile,'cases':cases,
             'scope':'No new downloads/preparation for recovery. No repeat of completed Vina searches. '
                     'GUI screens use approved 2R8N protocols with five new larger ligands. '
                     'No production settings/installations/studies changed.'}
    save(LOCAL/'suite.json',suite)
    print(json.dumps({'suite':str(LOCAL/'suite.json'),'cases':len(cases),
                      'new_recovery_searches':12,'new_gui_jobs':14,'excluded':1,'blocked_legacy_import':1},indent=2))


if __name__ == '__main__':
    main()
