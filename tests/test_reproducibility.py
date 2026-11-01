"""Disclosure and historical runtime provenance must not invent equivalence."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from docking_universal.reproducibility import (
    DOCKING_REPRODUCIBILITY_NOTICE, retained_runtime_context, format_runtime_context, runtime_facts,
)
from docking_universal_dock import _write_manifest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reproducibility_pdf', ROOT/'libexec/docking-universal-pdf-report.py')
REPORT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(REPORT)


class ReproducibilityTests(unittest.TestCase):
    def test_runtime_observation_never_spawns_a_command(self):
        with patch('subprocess.run', side_effect=AssertionError('No shell or external probe')):
            facts = runtime_facts()
        self.assertTrue(facts['operating_system'])
        self.assertTrue(facts['architecture'])

    def test_execution_receipt_takes_precedence_and_zero_cpu_is_retained(self):
        context = retained_runtime_context(
            {'operating_system': 'Darwin', 'execution_backend': 'vina_python_batch', 'cpu': '0'},
            {'operating_system': 'Windows', 'architecture': 'arm64'},
        )
        self.assertEqual(context['operating_system'], 'Darwin')
        self.assertEqual(context['execution_backend'], 'vina_python_batch')
        self.assertEqual(context['cpu'], '0')
        self.assertIn('Vina persistent Python API', format_runtime_context(context))

    def test_legacy_run_is_not_assigned_the_report_generation_platform(self):
        with patch('docking_universal.reproducibility.runtime_facts', side_effect=AssertionError('No current-host inference')):
            context = retained_runtime_context({}, None, {'engine_version': '1.2.7'})
            self.assertTrue(all(value == 'not recorded' for value in context.values()))
            text = REPORT.reproducibility_summary(self.provenance(context), None, True)
        self.assertIn(DOCKING_REPRODUCIBILITY_NOTICE, text)
        self.assertIn('operating system: not recorded', text)
        self.assertNotIn('operating system: Windows', text)

    @staticmethod
    def provenance(context):
        return {'receptor_preparation': {'path': 'retained fixture'}, 'execution_context': context,
                'methods': {'cluster_cutoff_angstrom': 1.5, 'docking_scores_and_poses': 'AutoDock Vina'}}

    def test_pdf_includes_retained_runtime_and_escapes_user_metadata(self):
        context = retained_runtime_context({'operating_system': '<untrusted>', 'architecture': 'arm64',
                                            'execution_backend': 'cli', 'cpu': '8'})
        text = REPORT.reproducibility_summary(self.provenance(context), None, True)
        self.assertIn('API/CLI backends', text)
        self.assertIn('execution backend: CLI', text)
        self.assertIn('&lt;untrusted&gt;', text)
        self.assertNotIn('<untrusted>', text)

    def test_docking_manifest_captures_host_and_selected_backend_without_input_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); config = root/'box.conf'; config.write_bytes(b'center_x = 0\n')
            out = root/'output'; out.mkdir()
            options = SimpleNamespace(engine='vina', output_dir=out, receptor=root/'receptor.pdbqt',
                ligand_dir=root/'ligands', config=config, exhaustiveness=16, num_modes=15,
                energy_range=8, seed=42, cpu=8, cpu_source='explicit')
            before = config.read_bytes()
            with patch('docking_universal.reproducibility.runtime_facts', return_value={
                    'operating_system': 'TestOS', 'operating_system_release': '1', 'architecture': 'test-architecture'}):
                _write_manifest(options, SimpleNamespace(source='fixture', command=('vina',)), '1.2.7',
                                {'execution_backend': 'vina_python_batch'})
            manifest = dict(line.split('\t', 1) for line in (out/'run_manifest.tsv').read_text().splitlines())
            self.assertEqual(manifest['operating_system'], 'TestOS')
            self.assertEqual(manifest['operating_system_release'], '1')
            self.assertEqual(manifest['architecture'], 'test-architecture')
            self.assertEqual(manifest['execution_backend'], 'vina_python_batch')
            self.assertEqual(manifest['seed'], '42')
            self.assertEqual(config.read_bytes(), before)
            self.assertEqual((out/'box.conf.used').read_bytes(), before)
