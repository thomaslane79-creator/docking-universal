import unittest

from docking_universal.viewer.identities import AtomIdentity, IdentityMapping, StructureIdentity
from docking_universal.viewer.messages import Command
from docking_universal.viewer.selections import AtomPoint, Selection, SelectionOperation


HASH_A = "a" * 64
HASH_B = "b" * 64


def atom(structure, chain="A", residue="10", insertion="", name="CA", altloc=""):
    return AtomIdentity(structure, "", chain, residue, insertion, "SER", name, altloc)


class ViewerContractTests(unittest.TestCase):
    def setUp(self):
        self.original = StructureIdentity("original-pdb", HASH_A, "receptor")
        self.prepared = StructureIdentity("prepared-pdb", HASH_B, "receptor_prepared")

    def test_identity_round_trip_preserves_text_residue_and_variant_fields(self):
        identity = atom(self.original, residue="-1", insertion="A", name="OG", altloc="B")
        self.assertEqual(AtomIdentity.from_dict(identity.to_dict()), identity)
        self.assertEqual(identity.residue_number, "-1")
        self.assertEqual(identity.insertion_code, "A")
        self.assertEqual(identity.altloc, "B")

    def test_mapping_rejects_ambiguity_and_missing_atoms(self):
        source = atom(self.original)
        target = atom(self.prepared)
        mapping = IdentityMapping(((source, target),))
        self.assertEqual(mapping.map((source,)), (target,))
        self.assertEqual(mapping.map((target,), reverse=True), (source,))
        with self.assertRaisesRegex(KeyError, "No exact"):
            mapping.map((atom(self.original, chain="B"),))
        with self.assertRaisesRegex(ValueError, "Ambiguous target"):
            IdentityMapping(((source, target), (source, atom(self.prepared, name="CB"))))

    def test_selection_operations_are_explicit_and_deterministic(self):
        ca = atom(self.original)
        cb = atom(self.original, name="CB")
        other = atom(self.original, residue="11")
        left = Selection("left", (cb, ca))
        right = Selection("right", (other, cb))
        self.assertEqual(left.combine(right, SelectionOperation.INTERSECTION).atoms, (cb,))
        self.assertEqual(left.combine(right, SelectionOperation.EXCLUSION).atoms, (ca,))
        self.assertEqual(left.whole_residues((other, cb, ca)).atoms, (ca, cb))

    def test_within_distance_validates_geometry(self):
        ca = AtomPoint(atom(self.original), (0.0, 0.0, 0.0))
        cb = AtomPoint(atom(self.original, name="CB"), (2.0, 0.0, 0.0))
        result = Selection.within_distance("near", (ca, cb), (ca,), 1.5)
        self.assertEqual(result.atoms, (ca.atom,))
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            Selection.within_distance("bad", (ca,), (ca,), -1)

    def test_message_parser_rejects_unknown_versions_and_fields(self):
        value = {
            "study_id": "study", "session_id": "session", "request_id": "request",
            "operation": "snapshot", "version": 1,
        }
        self.assertEqual(Command.from_dict(value).operation, "snapshot")
        with self.assertRaisesRegex(ValueError, "Unsupported protocol"):
            Command.from_dict({**value, "version": 2})
        with self.assertRaisesRegex(ValueError, "Unknown command fields"):
            Command.from_dict({**value, "python": "import os"})

    def test_selection_name_cannot_become_viewer_command_text(self):
        with self.assertRaisesRegex(ValueError, "safe viewer identifier"):
            Selection("picked; delete all", (atom(self.original),))


if __name__ == "__main__":
    unittest.main()
