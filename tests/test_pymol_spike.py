import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from docking_universal.pymol_spike import PymolSpikeClient, PymolSpikeError


BRIDGE_PATH = Path(__file__).parents[1] / "libexec" / "docking-universal-pymol-spike-bridge.py"


def load_bridge_module():
    spec = importlib.util.spec_from_file_location("du_pymol_spike_bridge_test", BRIDGE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCmd:
    def __init__(self):
        self._pymol = SimpleNamespace(session=SimpleNamespace())
        self.rows = [
            ["receptor", "", "A", "10", "SER", "CA", "", 1],
            ["receptor", "", "B", "10", "SER", "CA", "", 2],
            ["receptor", "", "A", "10A", "SER", "CA", "A", 3],
        ]
        self.selected_indices = []
        self.box = None
        self.selection_names = set()
        self.loaded = []
        self.deleted = []
        self.wizard = None
        self.colors = []

    def load(self, path, name=None):
        self.loaded.append((path, name))

    def count_atoms(self, _name):
        return len(self.rows)

    def iterate(self, selection, _expression, space):
        rows = self.rows
        if selection == "pk1":
            rows = self.rows[:1]
        elif selection == "du_user_pick":
            picked = self.rows[0]
            rows = [row for row in self.rows if row[:4] == picked[:4]]
        if selection == "du_residue":
            rows = [row for row in rows if row[7] in self.selected_indices]
        space["rows"].extend(rows)

    def select_list(self, _name, _model, indices, mode):
        self.selected_indices.extend(indices)

    def select(self, name, _expression):
        self.selection_names.add(name)
        return None

    def delete(self, name):
        self.deleted.append(name)
        return None

    def show(self, _representation, _name):
        return None

    def color(self, _color, _name):
        self.colors.append((_color, _name))
        return None

    def hide(self, _representation, _name):
        return None

    def set(self, _setting, _value, _name):
        return None

    def get_names(self, kind):
        self.assert_kind = kind
        return sorted(self.selection_names)

    def set_wizard(self, wizard=None):
        self.wizard = wizard

    def refresh_wizard(self):
        return None

    def unpick(self):
        return None

    def load_cgo(self, graphic, name):
        self.box = (name, graphic)


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_error):
        return None

    def read(self):
        return self.payload


class PymolSpikeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = load_bridge_module()

    def test_selection_distinguishes_chain_insertion_code_and_altloc(self):
        fake = FakeCmd()
        core = self.bridge.BridgeCore(fake)
        result = core.dispatch("apply_selection", {
            "name": "du_residue",
            "residues": [{
                "model": "receptor",
                "chain": "A",
                "residue_number": "10",
                "insertion_code": "A",
                "altloc": "A",
            }],
        })
        self.assertEqual(fake.selected_indices, [3])
        self.assertTrue(all(atom["chain"] == "A" for atom in result["atoms"]))
        self.assertTrue(all(atom["insertion_code"] == "A" for atom in result["atoms"]))

    def test_box_requires_positive_finite_size(self):
        core = self.bridge.BridgeCore(FakeCmd())
        with self.assertRaisesRegex(ValueError, "positive"):
            core.dispatch("show_box", {"name": "du_box", "center": [0, 0, 0], "size": [10, 0, 10]})
        result = core.dispatch("show_box", {"name": "du_box", "center": [1, 2, 3], "size": [10, 12, 14]})
        self.assertEqual(result["center"], [1.0, 2.0, 3.0])
        self.assertEqual(result["size"], [10.0, 12.0, 14.0])

    def test_pocket_loading_accepts_only_coordinate_files_and_known_colors(self):
        with tempfile.TemporaryDirectory() as directory:
            pocket = Path(directory) / "pocket 1.pdb"
            pocket.write_text("END\n")
            core = self.bridge.BridgeCore(FakeCmd())
            result = core.dispatch("load_pocket", {"path": str(pocket), "object_name": "du_pocket_1", "color": "marine"})
            self.assertEqual(result["color"], "marine")
            with self.assertRaisesRegex(ValueError, "color"):
                core.dispatch("load_pocket", {"path": str(pocket), "object_name": "du_pocket_2", "color": "user_expression"})

    def test_report_session_load_is_restricted_and_replaces_the_scene(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "retained report view.pse"
            session.write_bytes(b"pymol session")
            fake = FakeCmd()
            result = self.bridge.BridgeCore(fake).dispatch(
                "load_report_session", {"path": str(session), "replace": True},
            )
            self.assertTrue(result["report_view_restored"])
            self.assertEqual(fake.deleted, ["all"])
            self.assertEqual(fake.loaded, [(str(session.resolve()), None)])

            unsafe = Path(directory) / "not-a-session.pdb"
            unsafe.write_text("END\n")
            with self.assertRaisesRegex(ValueError, "PyMOL session"):
                self.bridge.BridgeCore(fake).dispatch(
                    "load_report_session", {"path": str(unsafe), "replace": True},
                )

    def test_bridge_rejects_arbitrary_operations_and_unsafe_names(self):
        core = self.bridge.BridgeCore(FakeCmd())
        with self.assertRaisesRegex(ValueError, "Unsupported operation"):
            core.dispatch("run_python", {"code": "pass"})
        with self.assertRaisesRegex(ValueError, "Names must"):
            core.dispatch("get_selection", {"name": "bad; delete all"})
        with self.assertRaisesRegex(ValueError, "does not exist"):
            core.dispatch("get_selection", {"name": "pk1"})
        with self.assertRaisesRegex(ValueError, "identity fields"):
            core.dispatch("apply_selection", {"name": "du_bad", "residues": [{"expression": "all"}]})

    def test_client_rejects_mismatched_response(self):
        client = PymolSpikeClient(1234, "x" * 32)
        with patch("urllib.request.urlopen", return_value=Response({
            "request_id": "wrong", "status": "ok", "result": {},
        })):
            with self.assertRaisesRegex(PymolSpikeError, "mismatched"):
                client.request("ping")

    def test_pick_wizard_returns_picked_atom_and_complete_residue(self):
        fake = FakeCmd()
        core = self.bridge.BridgeCore(fake)
        waiting = core.dispatch("start_pick", {})
        self.assertTrue(waiting["waiting_for_pick"])
        self.assertIsNone(core.dispatch("get_pick", {})["pick"])
        fake.wizard.do_pick(0)
        picked = core.dispatch("get_pick", {})
        self.assertEqual(picked["sequence"], 1)
        self.assertEqual(picked["pick"]["picked_atoms"][0]["model"], "receptor")
        self.assertGreaterEqual(len(picked["pick"]["residue_atoms"]), 1)


if __name__ == "__main__":
    unittest.main()
