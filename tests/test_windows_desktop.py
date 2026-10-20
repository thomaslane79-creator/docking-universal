import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docking_universal.application import StudyController
from docking_universal.host import CommandDispatcher
from docking_universal.state import JsonStudyStore
from docking_universal.viewer.messages import Command
from docking_universal.windows_desktop import WORKFLOW, installed_host, installed_capabilities, preparation_options, workflow_guard


class NativeDesktopGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = JsonStudyStore(self.root / "studies")
        self.controller = StudyController(self.store)
        self.controller.create_study("native", "Native Ω fixture")
        self.dispatcher = CommandDispatcher(self.controller, "session", workflow_guard=workflow_guard)

    def tearDown(self):
        self.dispatcher.shutdown()
        self.temporary.cleanup()

    def test_unsupported_native_routes_reject_before_state_or_output_mutation(self):
        prior = self.store.path_for("native").read_bytes()
        for operation, payload in (("start_control_validation", {}),
            ("start_receptor_preparation", {"site_mode": "ligand"}),
            ("start_receptor_preparation", {"pocket_engine": "fpocket"}),
            ("start_receptor_preparation", {"preparation_backend": "adfr"}),
            ("start_protocol_finalization", {"engine": "adgpu"}),
            ("start_protocol_finalization", {"engine": "qvinaw"})):
            with self.subTest(operation=operation, payload=payload):
                response = self.dispatcher.dispatch(Command("native", "session", operation + str(payload), operation,
                    {**payload, "output_directory": str(self.root / "should-not-exist")}, self.store.load("native").revision))
                self.assertEqual(response.status, "rejected")
                self.assertEqual(self.store.path_for("native").read_bytes(), prior)
                self.assertFalse((self.root / "should-not-exist").exists())

    def test_import_of_unaccepted_engine_fails_before_any_state_change(self):
        prior = self.store.path_for("native").read_bytes()
        with patch("docking_universal.services.protocol_import.inspect_protocol_bundle", return_value={"engine": "adgpu"}):
            response = self.dispatcher.dispatch(Command("native", "session", "import", "import_protocol_bundle",
                {"protocol_bundle": "other.duprotocol", "reviewed_sha256": "test"}, self.store.load("native").revision))
        self.assertEqual(response.status, "rejected")
        self.assertEqual(self.store.path_for("native").read_bytes(), prior)

    def test_preparation_options_keep_original_mmcif_and_reviewed_options(self):
        original = self.root / "original Ω.cif"
        template = self.root / "reviewed.json"
        options = preparation_options(self.root / "legacy.pdb", self.root / "work", {
            "DOCKING_UNIVERSAL_SOURCE_MMCIF": str(original),
            "DOCKING_UNIVERSAL_MAX_POCKETS": "0", "DOCKING_UNIVERSAL_REDUCE2": "required",
            "MEEKO_SET_TEMPLATE": "A:41=HIE", "MEEKO_ADD_TEMPLATES": str(template)})
        self.assertEqual(options.input_pdb, original)
        self.assertEqual(options.max_pockets, 0)
        self.assertEqual(options.reduce2, "required")
        self.assertEqual(options.meeko_templates, "A:41=HIE")
        self.assertEqual(options.meeko_template_file, template)

    def test_host_requires_exact_owned_scientific_python_and_receipt(self):
        app = self.root / "app"; app.mkdir()
        self.assertIsNone(installed_host(app))
        (app / "native-preview.json").write_text(json.dumps({"scientific_desktop_workflow": WORKFLOW}), encoding="utf-8")
        script = app / "docking-universal-prepare-native.py"; script.touch()
        python = self.root / "owned/python.exe"
        with patch("docking_universal.windows_desktop.scientific_environment", return_value=(python, {"OWNED": "yes"}, {})):
            self.assertEqual(installed_host(app, executing_python=python)[0], script)
            with self.assertRaisesRegex(ValueError, "exact installation-owned"):
                installed_host(app, executing_python=self.root / "foreign/python.exe")

    def test_accepted_viewer_capability_requires_owned_gui_receipt_without_importing_qt(self):
        app = self.root / 'app'; app.mkdir()
        configuration = {'viewer_supported': True}
        (app / 'native-preview.json').write_text(json.dumps(configuration), encoding='utf-8')
        gui = self.root / 'owned-gui/python.exe'
        with patch('docking_universal.windows_viewer_runtime.owned_gui_python', return_value=gui), \
             patch('docking_universal.windows_viewer_runtime.viewer_record', return_value=({}, 'owned.dll')) as verify:
            capabilities = installed_capabilities(app, {})
            self.assertTrue(capabilities['interactive_viewer_accepted'])
            self.assertIn('not GPU docking', capabilities['viewer_graphics'])
            verify.assert_called_once_with(app, configuration, executing_python=gui)
        with patch('docking_universal.windows_viewer_runtime.owned_gui_python', return_value=gui), \
             patch('docking_universal.windows_viewer_runtime.viewer_record', return_value=None):
            with self.assertRaisesRegex(ValueError, 'missing its owned'):
                installed_capabilities(app, {})


if __name__ == "__main__":
    unittest.main()
