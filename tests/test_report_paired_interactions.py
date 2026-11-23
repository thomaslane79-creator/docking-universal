import importlib.util
import tempfile
import unittest
from pathlib import Path
from PIL import Image

script = Path(__file__).resolve().parents[1] / 'libexec/docking-universal-pdf-report.py'
spec = importlib.util.spec_from_file_location('paired_pdf_test', script)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)

class PairedInteractionTests(unittest.TestCase):
    def test_large_report_image_keeps_display_size_and_source_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'large.png'
            Image.new('RGBA', (3000, 1500), (77, 132, 175, 160)).save(source)
            original = source.read_bytes()
            item = report.report_image(source, 432, 288)
            width, height = item.wrap(432, 288)
            self.assertAlmostEqual(width, 432)
            self.assertAlmostEqual(height, 216)
            self.assertEqual((item.imageWidth, item.imageHeight), (1800, 900))
            full = report.report_image(source, 432, 288, quality="high-resolution")
            self.assertEqual(full.wrap(432, 288), (width, height))
            self.assertEqual((full.imageWidth, full.imageHeight), (3000, 1500))
            self.assertEqual(source.read_bytes(), original)

    def test_pair_keeps_both_images_and_requires_both(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a, b, out = root/'scene.png', root/'diagram.png', root/'out.png'
            Image.new('RGB', (80, 80), (255, 0, 255)).save(a)
            Image.new('RGB', (80, 80), (0, 255, 0)).save(b)
            pair = {'scene': str(a), 'diagram': str(b), 'color': '#d62728',
                    'energy_rank': 1, 'cluster_id': 6, 'score': '-13.574'}
            self.assertTrue(report.combine_paired_interaction(pair, out))
            with Image.open(out) as result:
                colors = set(result.getdata())
                self.assertIn((255, 0, 255), colors)
                self.assertIn((0, 255, 0), colors)
                self.assertIn((77, 77, 255), colors)
                self.assertIn((0, 128, 255), colors)
            b.unlink()
            self.assertFalse(report.combine_paired_interaction(pair, out))

    def test_control_pair_uses_explicit_pose_heading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a, b = root/'scene.png', root/'diagram.png'
            Image.new('RGB', (20, 20), 'blue').save(a)
            Image.new('RGB', (20, 20), 'red').save(b)
            pair = {'scene': str(a), 'diagram': str(b), 'color': '#b638a0',
                    'energy_rank': 1, 'heading': 'Experimental reference'}
            self.assertTrue(report.combine_paired_interaction(pair, root/'control.png'))
