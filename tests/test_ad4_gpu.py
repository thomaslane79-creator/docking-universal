"""Engine-specific AD4 method contracts; no GPU launches."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docking_universal.ad4_gpu import (Ad4Settings, grid_geometry, native_arguments, receptor_parameter_types,
    parse_native_ranking, runtime_descriptor, read_settings)
from docking_universal_dock import DockOptions, DockUsageError, parse_arguments, validate_options


class Ad4Tests(unittest.TestCase):
    def test_passing_control_locks_ad4_method_and_grid_without_vina_settings(self):
        import subprocess
        import sys
        from docking_universal_bundle import reconcile_protocol_engine, protocol_can_screen
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receptor = root / 'receptor.pdbqt'; receptor.write_text('fixture receptor')
            box = root / 'box.conf'
            box.write_text(''.join(f'center_{axis} = 0\nsize_{axis} = 26\n' for axis in 'xyz'))
            roots = []
            for seed in (1, 2):
                directory = root / str(seed) / 'sample_comparison'
                directory.mkdir(parents=True)
                (directory / 'comparison_summary.json').write_text(json.dumps({
                    'pose_count': 1, 'top_score_affinity_kcal_per_mol': -7,
                    'top_score_rmsd_angstrom': 1, 'best_rmsd_angstrom': 1}))
                roots.append(directory.parent)
            output = root / 'protocol.json'
            script = Path(__file__).resolve().parents[1] / 'libexec/docking-universal-calibration-evaluate.py'
            command = [sys.executable, str(script), *map(str, roots), '--engine', 'adgpu', '--out', str(output),
                       '--receptor', str(receptor), '--box', str(box), '--ad4-settings',
                       json.dumps({'lga_runs': 2, 'heuristic_cap': 1000}), '--conformers', '1',
                       '--macrocycle-treatment', 'unsupported_experimental_ad4', '--min-seeds', '2',
                       '--seed', '1', '--seed', '2', '--no-prompt']
            subprocess.run(command, check=True, capture_output=True, text=True)
            protocol = json.loads(output.read_text())
            self.assertTrue(protocol_can_screen(protocol))
            self.assertEqual(reconcile_protocol_engine(protocol), 'adgpu')
            with self.assertRaisesRegex(ValueError, 'conflicts'):
                reconcile_protocol_engine(protocol, 'vina')
            self.assertEqual(protocol['parameters']['ad4']['lga_runs'], 2)
            self.assertNotIn('exhaustiveness', protocol['parameters'])
            self.assertEqual(protocol['locked_inputs']['boxes'][0]['ad4_grid']['actual_size'], [26.25] * 3)
    def test_receptor_types_come_from_verified_autogrid_parameter_table(self):
        import hashlib
        import io
        import tarfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'autogrid-source.tar.gz'
            data = ('\n'.join('atom_par ' + name + ' 1 1 1 1 0 0 0 0 0 0 # normal atom'
                               for name in ['H', 'C', 'N', 'OA', 'HD', 'Mg', 'Zn']) +
                    '\natom_par G 1 1 1 1 0 0 0 0 0 0 # Ring closure\n').encode()
            with tarfile.open(archive, 'w:gz') as tar:
                info = tarfile.TarInfo('source/ad4_shared/AD4_parameters.dat')
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            (root / 'manifest.json').write_text(json.dumps({'files': {'autogrid-source.tar.gz':
                {'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}}}))
            configured = {'autogrid_executable': str(root / 'autogrid4')}
            types = receptor_parameter_types(configured)
            self.assertTrue({'Mg', 'Zn'}.issubset(types))
            self.assertNotIn('G', types)
            (root / 'manifest.json').write_text('{}')
            self.assertNotIn('Mg', receptor_parameter_types(configured))
    def test_search_arguments_do_not_relabel_vina_settings(self):
        args=native_arguments('adgpu','maps.fld',Ad4Settings(),41001)
        self.assertEqual(args[args.index('--nrun')+1],'20')
        self.assertEqual(args[args.index('--heurmax')+1],'12000000')
        for forbidden in ('--cpu','--exhaustiveness','--num_modes','--energy_range'):
            self.assertNotIn(forbidden,args)

    def test_settings_fail_closed(self):
        for settings in (Ad4Settings(lga_runs=0),Ad4Settings(lga_runs=True),Ad4Settings(heuristic_cap=0),Ad4Settings(population=1),Ad4Settings(grid_spacing=.5)):
            with self.assertRaises(ValueError):settings.validate()
        with self.assertRaises(ValueError):read_settings({'exhaustiveness':16})
        with self.assertRaises(ValueError):read_settings({'ad4':{'unknown_profile_field':1}})

    def test_mac_acceptance_is_not_transferred_to_windows_or_linux(self):
        from docking_universal.ad4_gpu import available
        with tempfile.TemporaryDirectory() as tmp:
            config=Path(tmp)/'runtime.json'
            config.write_text(json.dumps({'schema':'docking-universal-adgpu-runtime-v1',
                'integration_accepted':True,'executable':str(Path(tmp)/'adgpu')}))
            env={'DOCKING_UNIVERSAL_ADGPU_CONFIG':str(config)}
            for system in ('Windows','Linux'):
                with patch('docking_universal.ad4_gpu.platform.system',return_value=system):
                    self.assertFalse(available(env))

    def test_actual_grid_not_smaller_than_requested(self):
        box={**{'center_'+a:1.234567 for a in 'xyz'},**{'size_'+a:26. for a in 'xyz'}}
        grid=grid_geometry(box)
        self.assertEqual(grid['requested_size'],[26.]*3)
        self.assertEqual(grid['actual_size'],[26.25]*3)
        self.assertEqual(grid['center'],[1.234567]*3)
        with self.assertRaises(ValueError):grid_geometry({**box,'size_x':float('nan')})

    def test_native_ranking_preserves_order_for_printed_ties(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'result.xml'
            def run(number):
                return f'<run id="{number}"><free_NRG_binding>-5.00</free_NRG_binding><final_intermol_NRG>-6.0</final_intermol_NRG><internal_ligand_NRG>1.2</internal_ligand_NRG><torsonial_free_NRG>1.0</torsonial_free_NRG></run>'
            path.write_text('<result><run_requested>2</run_requested><runs>'+run(2)+run(1)+'</runs></result>')
            rows=parse_native_ranking(path,2)
            self.assertEqual([r['native_run'] for r in rows],[2,1])
            path.write_text('<result><run_requested>2</run_requested><runs>'+run(1)+run(1)+'</runs></result>')
            with self.assertRaises(ValueError):parse_native_ranking(path,2)

    def test_absent_runtime_does_not_substitute_vina(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'not configured'):
                runtime_descriptor({'DOCKING_UNIVERSAL_ADGPU_CONFIG':str(Path(tmp)/'missing.json')})

    def test_cli_ad4_json_is_explicit_and_not_allowed_for_vina(self):
        parsed=parse_arguments(['--engine','adgpu','--ad4-settings','{"lga_runs":20}'])
        self.assertEqual(parsed.ad4_settings,{'lga_runs':20})
        with self.assertRaises(DockUsageError):parse_arguments(['--ad4-settings','[]'])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'r').touch();(root/'b').touch()
            options=DockOptions(engine='vina',receptor=root/'r',config=root/'b',ligand_dir=root,output_dir=root/'out',ad4_settings={})
            with self.assertRaisesRegex(DockUsageError,'cannot be applied'):
                validate_options(options,root/'helper')


if __name__=='__main__':unittest.main()
