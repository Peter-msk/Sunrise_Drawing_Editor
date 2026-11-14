"""Stage11 regression: responsive batch export, wheel semantics, exact PNG crop.

Engine and source tests intentionally run without PySide6; real Windows
desktop event-loop responsiveness and field OnMap PDF still need field QA.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import fitz
from PIL import Image, ImageDraw

from drawing_editor.batch import ExportJob
from drawing_editor.batch_worker import run_batch_exports_isolated
from drawing_editor.core import OutputOptions
from drawing_editor.trim import find_content_crop, save_png_tiled_crop_single_pass
from drawing_editor.tiles import save_png_tiled


ROOT = Path(__file__).resolve().parents[1]
WINDOW = (ROOT / "drawing_editor" / "window.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


class Stage11StaticContracts(unittest.TestCase):
    def test_plain_wheel_scrolls_and_ctrl_wheel_zooms(self):
        self.assertIn('if modifiers & Qt.KeyboardModifier.ControlModifier:', WINDOW)
        self.assertIn('self.zoom(zoom_factor_for_delta(dy, pixel_dy))', WINDOW)
        self.assertIn('super().wheelEvent(event)', WINDOW)
        self.assertIn('Qt.KeyboardModifier.ShiftModifier', WINDOW)

    def test_batch_process_bypasses_qt_native_gate(self):
        self.assertIn('run_batch_exports_isolated(', WINDOW)
        self.assertIn("sys.argv[1] == '--batch-worker'", MAIN)
        self.assertNotIn('run_batch_exports(self.jobs,self.options', WINDOW)

    def test_search_icon_toolbar_and_footer_share_both_theme_styles(self):
        self.assertIn("setObjectName('layerSearchFrame')", WINDOW)
        self.assertIn("setObjectName('layerSearchIcon')", WINDOW)
        self.assertIn('QFrame#layerSearchFrame', WINDOW)
        self.assertIn('QToolBar#toolbar QToolButton {{background:{input_bg};', WINDOW)
        self.assertIn('QGroupBox#exportPanel QRadioButton', WINDOW)
        self.assertIn('QGroupBox#exportPanel QLabel#hint', WINDOW)


class Stage11ExactCropContracts(unittest.TestCase):
    def setUp(self):
        self.image = Image.new('RGBA', (240, 180), (0, 0, 0, 0))
        painter = ImageDraw.Draw(self.image)
        painter.rectangle((21, 26, 198, 143), fill=(255, 255, 255, 255))
        painter.line((30, 30, 190, 130), fill=(0, 0, 0, 255), width=3)
        self.addCleanup(self.image.close)

    def stripes(self, _page, width, height, **_kwargs):
        self.assertEqual((width,height),(240,180))
        for y0 in range(0,height,35):
            y1=min(height,y0+35)
            piece=self.image.crop((0,y0,width,y1))
            try:
                yield y0,y1,bytearray(piece.tobytes())
            finally:
                piece.close()


    def test_exact_png_stream_same_as_legacy_two_pass(self):
        with tempfile.TemporaryDirectory() as root:
            with fitz.open() as pdf:
                page = pdf.new_page(width=240, height=180)
                with patch('drawing_editor.trim.raster_stripes', side_effect=self.stripes), \
                     patch('drawing_editor.tiles.raster_stripes', side_effect=self.stripes):
                    bbox = find_content_crop(page, 240, 180)
                    self.assertEqual(bbox, (21, 26, 199, 144))
                    expected = BytesIO()
                    save_png_tiled(page, expected, bbox[2]-bbox[0], bbox[3]-bbox[1],
                                   300, transparent=True, source_rect=(
                                       bbox[0],bbox[1],240,180))
                    optimized = BytesIO()
                    save_png_tiled_crop_single_pass(
                        page, optimized, 240,180,300,scratch_dir=root)
                    self.assertEqual(optimized.getvalue(),expected.getvalue())

    def test_cancelled_crop_cannot_leave_output(self):
        with tempfile.TemporaryDirectory() as root:
            with fitz.open() as pdf:
                page = pdf.new_page(width=240,height=180)
                result = BytesIO()
                with patch('drawing_editor.trim.raster_stripes', side_effect=self.stripes):
                    with self.assertRaises(InterruptedError):
                        save_png_tiled_crop_single_pass(
                            page, result, 240,180,300,scratch_dir=root,
                            cancelled=lambda: True)
                self.assertEqual(list(Path(root).iterdir()), [])


class Stage11ProcessContracts(unittest.TestCase):
    def test_pdf_ocg_visibility_keys_survive_worker_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            source = home / 'layered-onmap.pdf'
            with fitz.open() as pdf:
                page = pdf.new_page(width=100, height=100)
                layer_xref = pdf.add_ocg('Visible map layer', on=1)
                page.draw_rect(fitz.Rect(18,18,82,82), fill=(1,0,0),
                               color=(1,0,0),oc=layer_xref)
                pdf.save(source)
            jobs = [
                ExportJob(str(source), {layer_xref: True}, 0,
                          str(home / 'visible.png')),
                ExportJob(str(source), {layer_xref: False}, 0,
                          str(home / 'hidden.png')),
            ]
            report = run_batch_exports_isolated(
                jobs, OutputOptions('png',resolution='hd'))
            self.assertEqual(len(report.completed), 2)
            self.assertFalse(report.errors)
            with Image.open(home/'visible.png') as enabled, \
                 Image.open(home/'hidden.png') as hidden:
                self.assertNotEqual(enabled.convert('RGB').tobytes(),
                                    hidden.convert('RGB').tobytes())
                self.assertEqual(hidden.convert('RGB').getpixel(
                    (hidden.width//2,hidden.height//2)), (255,255,255))

    def test_fifteen_small_pdf_exports_without_overwriting_source(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            sources, jobs = [], []
            for i in range(15):
                path = home / f'onmap-test-{i:02d}.pdf'
                with fitz.open() as pdf:
                    page = pdf.new_page(width=120, height=90)
                    page.draw_line((2,4),(98,80),color=(0,0,0),width=1)
                    pdf.save(path)
                sources.append(path)
                jobs.append(ExportJob(str(path),{},0,
                                      str(home / f'onmap-test-{i:02d}.png')))
            originals = [path.read_bytes() for path in sources]
            seen = []
            result = run_batch_exports_isolated(
                jobs, OutputOptions('png',resolution='hd'),
                progress=lambda *args: seen.append(args))
            self.assertEqual(len(result.completed),15)
            self.assertEqual(result.errors,())
            self.assertFalse(result.cancelled)
            self.assertEqual([path.read_bytes() for path in sources],originals)
            self.assertTrue(seen)
            for filename in result.completed:
                with Image.open(filename) as image:
                    self.assertEqual(image.format,'PNG')


if __name__ == '__main__':
    unittest.main()
