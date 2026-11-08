"""Preparation-time identity survives portability; current installs cannot fill gaps."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from docking_universal.services.backend_provenance import (
    capture_adfr_identity, pinned_file, bind_output, attach_retained_backend, digest, FILENAME)
from docking_universal.services.receptor_model_history import normalize_preparation
from docking_universal_bundle import create_bundle, extract_bundle

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('backend_identity_pdf', ROOT/'libexec/docking-universal-pdf-report.py')
REPORT = importlib.util.module_from_spec(spec); spec.loader.exec_module(REPORT)


class BackendProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.suite = self.root/'ADFRsuite-1.0'  # Deliberately differs from package version.
        (self.suite/'bin').mkdir(parents=True)
        (self.suite/'CCSBpckgs/ADFR').mkdir(parents=True)
        self.version_file = self.suite/'CCSBpckgs/ADFR/__init__.py'
        self.version_file.write_text("__version__=2\n__subversion__=7\n__revision__='rc1'\nraise RuntimeError('Do not import scientific libraries to read metadata')\n")
        entry = self.suite/'CCSBpckgs/AutoDockTools/Utilities24/prepare_receptor4.py'
        entry.parent.mkdir(parents=True); entry.write_text('# deterministic fixture preparer\n')
        self.executable = self.suite/'bin/prepare_receptor'
        self.executable.write_text('#!/bin/sh\nADS_ROOT="' + str(self.suite) + '"\nexec $python $pyflags $ADS_ROOT/CCSBpckgs/AutoDockTools/Utilities24/prepare_receptor4.py $@\n')
        runtime = self.suite/'bin/pythonsh'
        runtime.write_text('#!/bin/sh\nADS_ROOT="' + str(self.suite) + '"\nexport PYTHONPATH="$ADS_ROOT/CCSBpckgs"\nexec "' + sys.executable + '" "$@"\n')
        runtime.chmod(0o755); self.executable.chmod(0o755)
        self.receptor_dir = self.root/'prep/receptor'; self.receptor_dir.mkdir(parents=True)
        self.input = self.receptor_dir/'input.pdb'; self.input.write_text('ATOM input\n')
        self.output = self.receptor_dir/'prepared.pdbqt'; self.output.write_text('ATOM prepared\n')

    def seal(self, route='adfr_primary'):
        startup = self.receptor_dir/'adfr_startup_audit.json'
        startup.write_text(json.dumps(dict(available=True, backend_identity=capture_adfr_identity(self.executable), input=pinned_file(self.input))))
        return bind_output(startup, self.output, route, self.receptor_dir/FILENAME)

    def test_queries_actual_package_metadata_without_import_or_folder_guess(self):
        identity = capture_adfr_identity(self.executable)
        self.assertEqual(identity['version'], '2.7rc1')
        self.assertEqual(identity['identity_status'], 'recorded')
        self.assertEqual(identity['version_source']['sha256'], digest(self.version_file))

    def test_unrecognized_wrapper_keeps_version_unknown(self):
        self.executable.write_text('#!/bin/sh\nexit 0\n')
        self.assertEqual(capture_adfr_identity(self.executable)['version'], 'not recorded')

    def test_primary_and_fallback_receipts_bind_the_accepted_receptor(self):
        for route in ('adfr_primary', 'adfr_legacy_linked_component_fallback'):
            record = self.seal(route)
            self.assertEqual(record['preparation_route'], route)
            result = attach_retained_backend({}, self.receptor_dir.parent, self.output)
            self.assertEqual(result['backend_identity'], record)
            self.assertEqual(result['backend_identity_audit_sha256'], digest(self.receptor_dir/FILENAME))
            normalize_preparation(result, digest(self.output))
            with self.assertRaisesRegex(ValueError, 'different prepared receptor'):
                normalize_preparation(result, 'a'*64)

    def test_tool_or_input_changes_during_execution_cannot_be_sealed(self):
        startup = self.receptor_dir/'startup.json'
        startup.write_text(json.dumps(dict(backend_identity=capture_adfr_identity(self.executable), input=pinned_file(self.input))))
        self.version_file.write_text('__version__=9\n')
        with self.assertRaisesRegex(ValueError, 'changed during preparation'):
            bind_output(startup, self.output, 'adfr_primary', self.receptor_dir/FILENAME)

    def test_report_never_fills_historical_gap_from_current_install(self):
        with patch.object(Path, 'home', return_value=self.root):
            self.assertEqual(REPORT.adfrsuite_version({}, {'adfr_fallback_log': 'retained.log'}), 'not recorded')
        record = self.seal()
        self.assertEqual(REPORT.adfrsuite_version({}, {'backend_identity': record}), '2.7rc1')

    def test_bundle_preserves_identity_without_original_install_or_preparation(self):
        self.seal()
        prep = attach_retained_backend({}, self.receptor_dir.parent, self.output)
        box = self.root/'box.conf'; box.write_text('center_x = 0\ncenter_y = 0\ncenter_z = 0\nsize_x = 26\nsize_y = 26\nsize_z = 26\n')
        protocol = dict(schema_name='docking-universal-protocol', schema_version=1, engine='vina',
            protocol_type='site-guided-exploratory', exploratory_screening_allowed=True,
            screening_authority='user-confirmed-exploratory-use', parameters=dict(conformers_per_state=1,seeds=[11]),
            locked_inputs=dict(receptor=str(self.output), receptor_sha256=digest(self.output), box=str(box), box_sha256=digest(box)),
            receptor_preparation=prep)
        path = self.root/'protocol.json'; path.write_text(json.dumps(protocol))
        bundle = self.root/'portable.duprotocol'; create_bundle(path,self.root,bundle)
        import shutil
        shutil.rmtree(self.suite); shutil.rmtree(self.receptor_dir.parent)
        extracted = extract_bundle(bundle); retained=json.loads(extracted.read_text())
        self.assertEqual(REPORT.adfrsuite_version({},retained['receptor_preparation']), '2.7rc1')
        asset=extracted.parent/retained['receptor_preparation']['backend_identity_audit']
        self.assertEqual(digest(asset), retained['receptor_preparation']['backend_identity_audit_sha256'])

    def test_screening_summary_retains_identity_without_original_protocol(self):
        identity=self.seal(); (self.root/'report').mkdir()
        (self.root/'report/study_summary.json').write_text(json.dumps(dict(protocol_receptor_preparation={'backend_identity':identity})))
        preparation=REPORT.receptor_preparation_record(self.root)
        self.assertEqual(preparation['preparation_route'], 'adfr_primary')
        self.assertEqual(REPORT.adfrsuite_version({},preparation), '2.7rc1')

    def test_raw_preparation_report_uses_its_sealed_identity_and_rejects_changed_output(self):
        self.seal()
        record = REPORT.receptor_preparation_record(self.root)
        self.assertEqual(REPORT.adfrsuite_version({}, record), '2.7rc1')
        self.output.write_text('changed receptor')
        with self.assertRaisesRegex(ValueError, 'no matching prepared receptor'):
            REPORT.receptor_preparation_record(self.root)

    def test_gui_finalization_summary_uses_recorded_primary_backend(self):
        from docking_universal.services.finalization import _preparation_summary
        (self.receptor_dir/'ccd_modification_audit.json').write_text(json.dumps({'preparation_route':'adfr_primary'}))
        (self.receptor_dir.parent/'run.log').write_text('Initial receptor preparation succeeded; PDBFixer was not needed')
        self.assertIn('ADFRsuite', _preparation_summary(self.receptor_dir.parent))
        self.assertNotIn('Strict Meeko', _preparation_summary(self.receptor_dir.parent))
