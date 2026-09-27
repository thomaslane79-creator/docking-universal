from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from docking_universal.viewer.embedded_pymol import EmbeddedPymolAdapter


class FakeCommand:
    def __init__(self):
        self.objects = ["receptor", "du_evidence_old"]
        self.view = tuple(float(value) for value in range(18))
        self.restored_view = None
        self.auto_zoom = 1
        self.loads = []
        self.disabled = []
        self.enabled = []
        self.centers = []
        self.cgo_loads = []
        self.colors = []

    def get_view(self):
        return self.view

    def set_view(self, view):
        self.restored_view = tuple(view)
        self.view = tuple(view)

    def get_setting_int(self, name):
        assert name == "auto_zoom"
        return self.auto_zoom

    def set(self, name, value, *_args):
        if name == "auto_zoom":
            self.auto_zoom = int(value)

    def get_names(self, _kind):
        return list(self.objects)

    def disable(self, name):
        self.disabled.append(name)

    def load(self, path, name, zoom=1):
        self.loads.append((path, name, zoom, self.auto_zoom))
        self.objects.append(name)
        # Simulate PyMOL changing the camera when a load is allowed to zoom.
        if zoom or self.auto_zoom:
            self.view = tuple(value + 100 for value in self.view)

    def hide(self, *_args):
        pass

    def show(self, *_args):
        pass

    def color(self, *args):
        self.colors.append(args)

    def enable(self, name):
        self.enabled.append(name)

    def delete(self, name):
        if name in self.objects:
            self.objects.remove(name)

    def load_cgo(self, value, name, zoom=1):
        self.cgo_loads.append((value, name, zoom, self.auto_zoom))
        self.objects.append(name)
        if zoom or self.auto_zoom:
            self.view = tuple(value + 100 for value in self.view)

    def center(self, name, animate=0):
        self.centers.append((name, animate))
        # Model a pan: translation/origin changes while rotation, camera depth,
        # clipping, and orthoscopic scale remain unchanged.
        changed = list(self.view)
        changed[9] += 5
        changed[10] -= 3
        changed[12:15] = [20, 30, 40]
        self.view = tuple(changed)


class FakeWidget:
    def __init__(self):
        self.cmd = FakeCommand()
        self.updates = 0

    def update(self):
        self.updates += 1


class EmbeddedEvidenceCameraTests(unittest.TestCase):
    def test_first_and_repeated_evidence_changes_preserve_exact_camera(self):
        with TemporaryDirectory() as directory:
            first = Path(directory) / "first.pdb"
            second = Path(directory) / "second.pdb"
            first.write_text("ATOM\n")
            second.write_text("ATOM\n")
            widget = FakeWidget()
            adapter = EmbeddedPymolAdapter(widget)
            protein_view = widget.cmd.get_view()

            adapter.sync_evidence_ligands([first])
            self.assertEqual(widget.cmd.get_view(), protein_view)
            self.assertEqual(widget.cmd.loads[0][2:], (0, 0))
            self.assertEqual(widget.cmd.auto_zoom, 1)

            adapter.sync_evidence_ligands([second])
            self.assertEqual(widget.cmd.get_view(), protein_view)
            self.assertEqual(widget.cmd.loads[1][2:], (0, 0))
            self.assertEqual(widget.cmd.auto_zoom, 1)
            self.assertIn("du_evidence_old", widget.cmd.disabled)

    def test_candidate_box_recenters_without_changing_rotation_or_zoom(self):
        from unittest.mock import patch

        widget = FakeWidget()
        adapter = EmbeddedPymolAdapter(widget)
        before = widget.cmd.get_view()
        fake_cgo = type("CGO", (), {
            "LINEWIDTH": 1, "BEGIN": 2, "LINES": 3, "COLOR": 4,
            "VERTEX": 5, "END": 6, "CYLINDER": 7,
        })
        with patch.dict("sys.modules", {"pymol": type("P", (), {"cgo": fake_cgo})}):
            result = adapter.show_box([20, 30, 40], [10, 12, 14], color="marine")

        after = widget.cmd.get_view()
        self.assertEqual(after[:9], before[:9])
        self.assertEqual(after[11], before[11])
        self.assertEqual(after[15:], before[15:])
        self.assertEqual(widget.cmd.cgo_loads[0][2:], (0, 0))
        box_cgo = widget.cmd.cgo_loads[0][0]
        self.assertEqual(box_cgo[0], fake_cgo.CYLINDER)
        self.assertEqual(box_cgo[7], 0.35)
        self.assertEqual(widget.cmd.centers, [("du_box", 0)])
        self.assertEqual(widget.cmd.auto_zoom, 1)
        self.assertEqual(result["camera"], "center_preserving_scale")
        self.assertEqual(result["edge_representation"], "cylinders")
        self.assertEqual(result["edge_radius_angstrom"], 0.35)
        self.assertEqual(result["color"], "marine")
        self.assertEqual(box_cgo[8:11], [0.0, 0.5, 1.0])

    def test_candidate_highlight_replaces_retained_and_redundant_evidence_boxes(self):
        from unittest.mock import patch

        widget = FakeWidget()
        widget.cmd.objects.extend(["candidate_box_P1", "ligand_site_box"])
        adapter = EmbeddedPymolAdapter(widget)
        fake_cgo = type("CGO", (), {
            "LINEWIDTH": 1, "BEGIN": 2, "LINES": 3, "COLOR": 4,
            "VERTEX": 5, "END": 6, "CYLINDER": 7,
        })
        with patch.dict("sys.modules", {"pymol": type("P", (), {"cgo": fake_cgo})}):
            result = adapter.show_box(
                [20, 30, 40], [10, 12, 14],
                source_object_name="candidate_box_P1",
                redundant_object_names=("ligand_site_box",),
            )

        self.assertEqual(widget.cmd.disabled, ["candidate_box_P1", "ligand_site_box"])
        self.assertEqual(result["replaces"], "candidate_box_P1")
        self.assertEqual(result["hides_redundant"], ["ligand_site_box"])

    def test_associated_ligand_visibility_follows_candidate_selection(self):
        from unittest.mock import patch

        widget = FakeWidget()
        widget.cmd.objects.append("ligand_site_representative")
        adapter = EmbeddedPymolAdapter(widget)
        fake_cgo = type("CGO", (), {
            "LINEWIDTH": 1, "BEGIN": 2, "LINES": 3, "COLOR": 4,
            "VERTEX": 5, "END": 6, "CYLINDER": 7,
        })
        with patch.dict("sys.modules", {"pymol": type("P", (), {"cgo": fake_cgo})}):
            adapter.show_box(
                [20, 30, 40], [10, 12, 14],
                visible_associated_object_names=("ligand_site_representative",),
            )
            adapter.show_box([40, 50, 60], [10, 12, 14])

        self.assertIn("ligand_site_representative", widget.cmd.enabled)
        self.assertIn("ligand_site_representative", widget.cmd.disabled)

    def test_specific_evidence_selection_temporarily_hides_report_representative(self):
        from unittest.mock import patch

        with TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence.pdb"
            evidence.write_text("ATOM\n")
            widget = FakeWidget()
            widget.cmd.objects.append("ligand_site_representative")
            adapter = EmbeddedPymolAdapter(widget)
            fake_cgo = type("CGO", (), {
                "LINEWIDTH": 1, "BEGIN": 2, "LINES": 3, "COLOR": 4,
                "VERTEX": 5, "END": 6, "CYLINDER": 7,
            })
            with patch.dict("sys.modules", {"pymol": type("P", (), {"cgo": fake_cgo})}):
                adapter.show_box(
                    [20, 30, 40], [10, 12, 14],
                    visible_associated_object_names=("ligand_site_representative",),
                )
            adapter.sync_evidence_ligands([evidence])
            self.assertEqual(widget.cmd.disabled[-1], "ligand_site_representative")
            self.assertTrue(any(call[0] == "green" for call in widget.cmd.colors))

            adapter.sync_evidence_ligands([])
            self.assertEqual(widget.cmd.enabled[-1], "ligand_site_representative")


if __name__ == "__main__":
    unittest.main()
