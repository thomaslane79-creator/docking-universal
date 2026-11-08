"""Cross-platform checks for a version-bound, app-owned Cocoa plugin."""
import copy
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import sys
import shutil

from docking_universal.qt_cocoa_runtime import (
    LIBRARIES, SCHEMA, _download, _run, _verified_sources, runtime_root, sha256,
    specification, verified_plugin_root,
)


class CocoaRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.prefix = Path(temporary.name).resolve()
        self.root = runtime_root(self.prefix)
        plugin = self.root/'plugins/platforms/libqcocoa.dylib'
        plugin.parent.mkdir(parents=True)
        plugin.write_bytes(b'owned-plugin-fixture')
        for name in LIBRARIES:
            path = self.prefix/name; path.parent.mkdir(exist_ok=True)
            path.write_bytes(name.encode())
        spec = specification()
        self.record = {'schema':SCHEMA, 'qt_version':spec['qt_version'], 'architecture':'arm64',
            'qt_prefix':str(self.prefix), 'source_commit':spec['qt_source']['commit'],
            'patch_commit':spec['patch']['commit'], 'plugin_sha256':sha256(plugin),
            'libraries':{name:sha256(self.prefix/name) for name in LIBRARIES}}
        self.save()

    def save(self, record=None):
        (self.root/'runtime.json').write_text(json.dumps(record or self.record))

    def resolve(self, **overrides):
        values = dict(system='Darwin', machine='arm64')
        values.update(overrides)
        return verified_plugin_root(self.prefix,'6.11.2',**values)

    def test_exact_registered_runtime_is_selected_and_foreign_platforms_are_untouched(self):
        self.assertEqual(self.resolve(),self.root/'plugins')
        self.assertIsNone(self.resolve(system='Windows'))
        self.assertIsNone(self.resolve(system='Linux'))
        (self.root/'runtime.json').unlink()
        with self.assertRaisesRegex(RuntimeError,'stale or damaged'):self.resolve()
        shutil.rmtree(self.root)
        self.assertIsNone(self.resolve())

    def test_identity_version_architecture_or_source_mismatch_is_rejected(self):
        for key,value in [('qt_version','6.12.0'),('architecture','x86_64'),
                          ('source_commit','f'*40),('patch_commit','a'*40),
                          ('qt_prefix',str(self.prefix/'other'))]:
            with self.subTest(key=key):
                record=copy.deepcopy(self.record);record[key]=value;self.save(record)
                with self.assertRaisesRegex(RuntimeError,'stale or damaged'):
                    self.resolve()

    def test_modified_or_missing_plugin_and_libraries_are_rejected(self):
        for relative in ['plugins/platforms/libqcocoa.dylib']:
            path=self.root/relative;original=path.read_bytes();path.write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError,'checksum changed'):self.resolve()
            path.unlink()
            with self.assertRaisesRegex(RuntimeError,'stale or damaged'):self.resolve()
            path.write_bytes(original)
        library=self.prefix/LIBRARIES[0];library.write_bytes(b'updated-qt')
        with self.assertRaisesRegex(RuntimeError,'Qt library changed'):self.resolve()

    def test_failed_build_step_preserves_diagnostics_and_names_the_log(self):
        log = self.prefix/'compiler.log'
        with self.assertRaisesRegex(RuntimeError,'compiler.log'):
            _run([sys.executable,'-c',"print('compiler diagnostic'); raise SystemExit(1)"],log)
        self.assertIn('compiler diagnostic',log.read_text())

    def test_malformed_manifest_and_incomplete_library_pins_are_rejected(self):
        (self.root/'runtime.json').write_text('{bad')
        with self.assertRaises(RuntimeError):self.resolve()
        record=copy.deepcopy(self.record);record['libraries'].pop(LIBRARIES[0]);self.save(record)
        with self.assertRaises(RuntimeError):self.resolve()

    def test_source_archive_and_cached_file_mismatch_fail_before_building(self):
        archive=self.prefix/'source.tar'
        with tarfile.open(archive,'w') as bundle:
            data=b'verified source';info=tarfile.TarInfo('root/src/plugins/platforms/cocoa/input.mm')
            info.size=len(data);bundle.addfile(info,io.BytesIO(data))
        destination=self.prefix/'sources';destination.mkdir()
        _verified_sources(archive,destination,('src/plugins/platforms/cocoa/',))
        path=destination/'root/src/plugins/platforms/cocoa/input.mm'
        self.assertEqual(path.read_bytes(),b'verified source')
        path.write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError,'Cached build source changed'):
            _verified_sources(archive,destination,('src/plugins/platforms/cocoa/',))
        _verified_sources(archive,destination,('src/plugins/platforms/cocoa/',),
            {'src/plugins/platforms/cocoa/input.mm':[sha256(path)]})
        with self.assertRaisesRegex(ValueError,'Cached source checksum mismatch'):
            _download({'url':'https://example.invalid/unused','sha256':'a'*64},archive)


if __name__ == '__main__':
    unittest.main()
