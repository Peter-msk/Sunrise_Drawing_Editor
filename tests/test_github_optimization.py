"""Source-backed PyMuPDF display-list and streaming PNG/JPEG optimizations."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import hashlib
import tempfile
import unittest

import fitz
from PIL import Image, ImageChops

from drawing_editor.core import DrawingDocument, OutputOptions, _render_page
from drawing_editor.tiles import save_png_tiled, save_jpg_tiled


class BrokenListPage:
    """A supported PDF where optional display-list acquisition fails."""
    def __init__(self, page):
        self._page = page
        self.rect = page.rect
        self.fallback_calls = 0
    def get_displaylist(self, *, annots=True):
        raise RuntimeError('list unavailable')
    def get_pixmap(self, **kwargs):
        self.fallback_calls += 1
        return self._page.get_pixmap(**kwargs)


class GitHubOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pdf_path = self.root / 'ocg_with_annotation.pdf'
        with fitz.open() as doc:
            page = doc.new_page(width=500, height=400)
            self.layer1 = doc.add_ocg('도로')
            self.layer2 = doc.add_ocg('건물')
            shape = page.new_shape()
            shape.draw_rect(fitz.Rect(80, 70, 320, 250))
            shape.finish(fill=(.9, .25, .2), color=(.1, .2, .8), oc=self.layer1)
            shape.draw_line((20, 300), (460, 300))
            shape.finish(color=(0, .6, 0), width=3, oc=self.layer2)
            shape.commit()
            annot = page.add_rect_annot(fitz.Rect(350, 50, 405, 110))
            annot.set_colors(stroke=(0.2, 0.0, 0.9))
            annot.update()
            doc.save(self.pdf_path)
        self.initial_sha = hashlib.sha256(self.pdf_path.read_bytes()).hexdigest()

    def test_zoom_display_list_reused_same_ocg_and_page(self):
        with DrawingDocument(self.pdf_path) as drawing:
            clip1 = (30, 45, 260, 260)
            clip2 = (90, 75, 310, 310)
            drawing.render_bytes(preview=(370, 320), clip=clip1)
            first = drawing._preview_display_list
            self.assertIsNotNone(first)
            result = drawing.render_bytes(preview=(450, 350), clip=clip2)
            self.assertIs(drawing._preview_display_list, first)
            direct = _render_page(drawing._pdf[0], 'png', (450, 350), clip2)
            self.assertEqual(Image.open(BytesIO(result)).tobytes(),
                             Image.open(BytesIO(direct)).tobytes())

    def test_toggle_invalidates_display_list_and_redraws_correctly(self):
        with DrawingDocument(self.pdf_path) as drawing:
            clip = (30, 40, 335, 275)
            before = drawing.render_bytes(preview=(500, 390), clip=clip)
            self.assertIsNotNone(drawing._preview_display_list)
            drawing.set_visibility(self.layer1, False)
            self.assertIsNone(drawing._preview_display_list)
            hidden = drawing.render_bytes(preview=(500, 390), clip=clip)
            self.assertNotEqual(before, hidden)
            self.assertIsNotNone(drawing._preview_display_list)
            drawing.set_visibility(self.layer1, True)
            self.assertIsNone(drawing._preview_display_list)
            restored = drawing.render_bytes(preview=(500, 390), clip=clip)
            self.assertEqual(before, restored)
        self.assertEqual(hashlib.sha256(self.pdf_path.read_bytes()).hexdigest(),
                         self.initial_sha)

    def test_annotation_present_in_cached_clipped_display_list(self):
        with DrawingDocument(self.pdf_path) as drawing:
            clip = (330, 30, 430, 130)
            cached = drawing.render_bytes(preview=(400, 400), clip=clip)
            direct = _render_page(drawing._pdf[0], 'png', (400, 400), clip)
            self.assertEqual(cached, direct)

    def test_tiled_png_with_display_list_preserves_visible_layer_state(self):
        with DrawingDocument(self.pdf_path) as drawing:
            dest = self.root / 'large.png'
            drawing.set_visibility(self.layer1, False)
            drawing.export_image(dest, OutputOptions('png', 'custom', 2600, 2080))
            with Image.open(dest) as image:
                self.assertEqual(image.size, (2600, 2080))
                center = image.getpixel((1100, 850))
                self.assertEqual(center, (255, 255, 255))
            drawing.set_visibility(self.layer1, True)
            visible = self.root / 'visible.png'
            drawing.export_image(visible, OutputOptions('png', 'custom', 2600, 2080))
            with Image.open(visible) as image:
                self.assertNotEqual(image.getpixel((1100, 850)), center)

    def test_large_png_uses_fallback_on_display_list_error(self):
        with fitz.open(self.pdf_path) as doc:
            broken = BrokenListPage(doc[0])
            stream = BytesIO()
            save_png_tiled(broken, stream, 1100, 880, 200)
            self.assertGreater(broken.fallback_calls, 0)
            with Image.open(BytesIO(stream.getvalue())) as im:
                self.assertEqual(im.size, (1100, 880))

    def test_stream_png_and_disk_backed_jpeg_outputs_valid(self):
        with fitz.open(self.pdf_path) as doc:
            png_buffer = BytesIO()
            save_png_tiled(doc[0], png_buffer, 1400, 1120, 144)
            jpeg_path = self.root / 'large.jpg'
            save_jpg_tiled(doc[0], jpeg_path, 1400, 1120, 144)
            with Image.open(BytesIO(png_buffer.getvalue())) as png, Image.open(jpeg_path) as jpg:
                self.assertEqual(png.size, jpg.size)
                self.assertEqual(png.format, 'PNG')
                self.assertEqual(jpg.format, 'JPEG')
                self.assertEqual(len(png.getbands()), 3)
                self.assertEqual(jpg.getpixel((5, 5)), (255, 255, 255))
            self.assertFalse(list(self.root.glob('.drawing-rgb-*')))


if __name__ == '__main__':
    unittest.main()
