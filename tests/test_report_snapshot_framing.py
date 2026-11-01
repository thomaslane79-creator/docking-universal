"""Report panel sizing must not cut off edge labels in retained snapshots."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None

SCRIPT = Path(__file__).resolve().parents[1] / 'libexec/docking-universal-report-figures.py'
SPEC = importlib.util.spec_from_file_location('snapshot_framing_figures', SCRIPT)
FIGURES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIGURES)


@unittest.skipIf(Image is None, 'Pillow unavailable')
class SnapshotFramingTests(unittest.TestCase):
    def test_full_edge_content_survives_all_panel_counts_and_aspect_ratios(self):
        colors = ((255, 0, 255), (0, 255, 255), (0, 255, 0), (0, 0, 0))
        for count in (1, 2, 3):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                rows = []
                original = {}
                for index, size in enumerate(((300, 900), (900, 300), (600, 600))[:count], 1):
                    folder = root / f'cluster_{index:03d}/interactions'
                    folder.mkdir(parents=True)
                    source = folder / 'complex_plip_all_in_one.png'
                    image = Image.new('RGB', size, 'white')
                    draw = ImageDraw.Draw(image)
                    w, h = size
                    for color, box in zip(colors, ((0, 0, 35, 35), (w-36, 0, w-1, 35),
                                                   (0, h-36, 35, h-1), (w-36, h-36, w-1, h-1))):
                        draw.rectangle(box, fill=color)
                    image.save(source)
                    original[source] = source.read_bytes()
                    rows.append({'cluster_id': str(index), 'energy_rank': str(index),
                                 'best_energy_kcal_per_mol': '-7'})
                output = root / 'panels.png'
                self.assertTrue(FIGURES.combine_cluster_snapshots(root, rows, output))
                with Image.open(output) as rendered:
                    # Exact-color interiors of all four edge markers must
                    # survive independently in each frame, not just somewhere
                    # in the combined report image.
                    if count == 1:
                        positions, cell_w, image_h = [(350, 140)], 2100, 1320
                    elif count == 2:
                        positions, cell_w, image_h = [(20, 60), (3860, 60)], 3600, 2400
                    else:
                        positions, cell_w, image_h = [(20, 60), (3860, 60), (1940, 2700)], 3600, 2400
                    for x, y in positions:
                        panel = rendered.crop((x+32, y+32, x+32+cell_w, y+32+image_h))
                        palette = {color for _n, color in panel.getcolors(panel.width * panel.height)}
                        self.assertTrue(set(colors).issubset(palette))
                for path, before in original.items():
                    self.assertEqual(path.read_bytes(), before)
                manifest = json.loads(output.with_suffix('.manifest.json').read_text())
                self.assertEqual(manifest['snapshot_count'], count)
                self.assertEqual(manifest['color_order'], list(FIGURES.TOP_COLORS[:count]))


if __name__ == '__main__':
    unittest.main()
