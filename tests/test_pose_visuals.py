import importlib.util
import tempfile
import json
import unittest
from pathlib import Path

from docking_universal.pose_visuals import cluster_color, retained_pose_color, write_pose_view, read_pose_view


class PoseVisualTests(unittest.TestCase):
    def test_experimental_source_kind_is_retained_and_legacy_roles_are_recognized(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = [root / name for name in ('diagram.png', 'ligand.sdf', 'receptor.pdb', 'report.xml')]
            for path in files:
                path.write_text(path.name)
            write_pose_view(*files, 'Experimental control ligand', 'magenta', coordinate_kind='experimental', role='experimental')
            self.assertEqual(read_pose_view(files[0])['coordinate_kind'], 'experimental')
            sidecar = Path(str(files[0]) + '.view.json')
            record = json.loads(sidecar.read_text())
            del record['coordinate_kind']
            sidecar.write_text(json.dumps(record))
            self.assertEqual(read_pose_view(files[0])['coordinate_kind'], 'experimental')
            record['identity']['role'] = 'lowest_rmsd'
            sidecar.write_text(json.dumps(record))
            self.assertEqual(read_pose_view(files[0])['coordinate_kind'], 'docked')
            record['coordinate_kind'] = 'imagined'
            sidecar.write_text(json.dumps(record))
            self.assertIsNone(read_pose_view(files[0]))
            with self.assertRaises(ValueError):
                write_pose_view(*files, 'Invalid kind', 'red', coordinate_kind='imagined')

    def test_rank_color_is_cluster_rank_not_pose_energy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "cluster_summary.csv").write_text("energy_rank,cluster_id\n1,12\n2,18\n3,49\n4,40\n")
            (root / "pose_inventory.csv").write_text("pose_id,cluster_id\n1,12\n38,40\n")
            self.assertEqual([cluster_color(root, cid) for cid in (12, 18, 49, 40)],
                             ["red", "marine", "gold", "gray70"])
            self.assertEqual(cluster_color(root, 12, closest=True), "red")
            self.assertEqual(cluster_color(root, 40, closest=True), "green")
            self.assertEqual(retained_pose_color(root, 1), "red")
            self.assertEqual(retained_pose_color(root, 38), "gray70")

    def test_view_link_requires_every_exact_file_and_color(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = [root / name for name in ("image.png", "pose.sdf", "receptor.pdb", "report.xml")]
            for path in files:
                path.write_text(path.name)
            for color in ("red", "marine", "gold", "green", "magenta", "gray70"):
                self.assertTrue(write_pose_view(*files, "Exact pose", color, pose_id=38))
                record = read_pose_view(files[0])
                self.assertEqual(record["ligand"], files[1].resolve())
                self.assertEqual(record["ligand_color"], color)
            for index in range(4):
                original = files[index].read_bytes()
                files[index].write_bytes(b"changed")
                self.assertIsNone(read_pose_view(files[0]))
                files[index].write_bytes(original)
            with self.assertRaises(ValueError):
                write_pose_view(*files, "Exact pose", "not-a-color")

    def test_standalone_cluster_browser_matches_rank_colors(self):
        script = Path(__file__).resolve().parents[1] / "libexec/docking-universal-cluster-poses.py"
        spec = importlib.util.spec_from_file_location("clusters", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receptor = root / "input.pdb"
            receptor.write_text("receptor")
            selected = [dict(cluster_id=i, representative=dict(energy=-12+i), seed_support=1, pose_count=2)
                        for i in range(1, 5)]
            pml = module.write_browser(root, receptor, selected, 5).read_text()
            for cid, color in zip(range(1, 5), ("red", "marine", "gold", "gray70")):
                self.assertIn(f"color {color}, cluster_{cid:03d}_", pml)


if __name__ == "__main__":
    unittest.main()
