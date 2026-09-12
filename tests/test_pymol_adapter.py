import tempfile
import unittest
from pathlib import Path

from docking_universal.viewer.identities import AtomIdentity, StructureIdentity
from docking_universal.viewer.pymol_adapter import PymolAdapter, RegisteredStructure
from docking_universal.viewer.selections import Selection


class FakeClient:
    def __init__(self):
        self.requests = []

    def request(self, operation, payload=None):
        self.requests.append((operation, payload or {}))
        if operation == "load_structure":
            return {"object_name": payload["object_name"], "path": payload["path"], "atoms": 2}
        if operation == "apply_selection":
            residue = payload["residues"][0]
            return {"name": payload["name"], "atoms": [{
                **residue, "resn": residue["residue_name"], "name": "CA",
                "atom_name": "CA", "altloc": residue["altloc"],
            }]}
        if operation == "get_pick":
            return {"pick": {"residue_atoms": [{
                "model": "du_receptor", "segi": "", "chain": "A",
                "residue_number": "10", "insertion_code": "A", "residue_name": "SER",
                "atom_name": "CA", "altloc": "B",
            }]}}
        return payload or {}


class FakeController:
    def stop(self):
        return None


class PymolAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        path = Path(self.temporary.name) / "receptor.pdb"
        path.write_text("END\n")
        self.identity = StructureIdentity("receptor", "a" * 64, "source")
        self.registered = RegisteredStructure(self.identity, path, "du_receptor")
        self.adapter = PymolAdapter(path, path, Path(self.temporary.name))
        self.adapter.controller = FakeController()
        self.adapter.client = FakeClient()
        self.adapter.register_structure(self.registered)

    def tearDown(self):
        self.temporary.cleanup()

    def test_selection_translation_never_uses_viewer_index(self):
        selected = Selection("du_candidate", (
            AtomIdentity(self.identity, "", "A", "10", "A", "SER", "CA", "B"),
        ), "request-1")
        applied = self.adapter.apply_selection(selected)
        payload = self.adapter.client.requests[-1][1]
        self.assertNotIn("index", payload["residues"][0])
        self.assertEqual(applied.origin_request_id, "request-1")
        self.assertEqual(applied.atoms[0].insertion_code, "A")

    def test_pick_from_unknown_model_is_rejected(self):
        self.adapter.client.request = lambda *_args, **_kwargs: {"pick": {"residue_atoms": [{
            "model": "not_registered", "residue_number": "1", "atom_name": "CA",
        }]}}
        with self.assertRaisesRegex(ValueError, "unregistered model"):
            self.adapter.get_pick()

    def test_apply_rejects_atom_from_unregistered_artifact(self):
        other = StructureIdentity("other", "b" * 64, "source")
        selection = Selection("bad", (AtomIdentity(other, "", "A", "1", "", "GLY", "CA"),))
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.adapter.apply_selection(selection)


if __name__ == "__main__":
    unittest.main()
