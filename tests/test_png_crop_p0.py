"""P0 regressions: no white-ink loss, no thumbnail aliasing, OCG correctness."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

import fitz
from PIL import Image

from drawing_editor.core import DrawingDocument, DrawingError, OutputOptions
from drawing_editor.trim import find_content_crop


class CropP0Regression(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.source = self.folder / 'ink-and-map.pdf'
        with fitz.open() as pdf:
            p = pdf.new_page(width=400, height=400)
            p.draw_rect(fitz.Rect(100, 100, 300, 300), color=None, fill=(.2, .3, .4))
            # Solid white artwork far OUTSIDE the colored rectangle is visible
            # on a transparent canvas, despite being white-on-white to an RGB scan.
            p.draw_rect(fitz.Rect(35, 35, 55, 55), color=None, fill=(1, 1, 1))
            # Fractional hairline near a different corner; catches preview loss.
            p.draw_line(fitz.Point(358, 345), fitz.Point(362, 351),
                        color=(.9, .9, .9), width=.06)
            pdf.save(self.source)
        self.sha = hashlib.sha256(self.source.read_bytes()).hexdigest()

    def _export_pair(self, max_size):
        full = self.folder / ('full-%s.png' % max_size)
        crop = self.folder / ('crop-%s.png' % max_size)
        with DrawingDocument(self.source) as drawing:
            drawing.export_image(full, OutputOptions('png', 'custom', max_size, max_size,
                                                      background='transparent'))
            drawing.export_image(crop, OutputOptions('png', 'custom', max_size, max_size,
                                                      background='transparent', crop_margins=True))
        return full, crop

    def _assert_full_alpha_region_retained(self, full, crop):
        with Image.open(full) as whole, Image.open(crop) as trimmed:
            bounds = whole.getchannel('A').getbbox()
            self.assertIsNotNone(bounds)
            self.assertEqual(trimmed.size, (bounds[2]-bounds[0], bounds[3]-bounds[1]))
            expected = whole.crop(bounds)
            try:
                self.assertEqual(expected.tobytes(), trimmed.tobytes())
            finally:
                expected.close()
            # The white symbol is opaque after crop (same physical location).
            # Choose an actual point in the white glyph instead of the margin.
            pixel = trimmed.getpixel((45*whole.width//400 - bounds[0],
                                      45*whole.height//400 - bounds[1]))
            self.assertEqual(pixel, (255, 255, 255, 255))
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.sha)

    def test_transparent_white_ink_survives_small_crop(self):
        self._assert_full_alpha_region_retained(*self._export_pair(800))

    def test_white_ink_and_hairline_survive_large_tiled_crop(self):
        self._assert_full_alpha_region_retained(*self._export_pair(3600))
        # Opaque RGB may conservatively retain extra invisible white artwork
        # in the large tiled path. The standalone original-PDF validator must
        # accept an exact corresponding full-page ROI, not report false loss.
        from quality.validate_onmap_source_pdf import validate
        report = validate(self.source, 1, 3600, [], self.folder)
        self.assertTrue(report['pass'])

    def test_opaque_page_white_paper_can_still_crop(self):
        doc = self.folder / 'opaque.pdf'
        with fitz.open() as pdf:
            p = pdf.new_page(width=400, height=400)
            p.draw_rect(p.rect, color=None, fill=(1, 1, 1))
            p.draw_rect(fitz.Rect(100, 110, 310, 310), color=None, fill=(.3, .5, .8))
            p.draw_rect(fitz.Rect(135, 145, 150, 160), color=None, fill=(1, 1, 1))
            pdf.save(doc)
        with DrawingDocument(doc) as drawing:
            output = self.folder / 'opaque-crop.png'
            drawing.export_image(output, OutputOptions('png', 'custom', 3600, 3600,
                                                        crop_margins=True, background='transparent'))
        with Image.open(output) as image:
            self.assertLess(image.width, 2100)
            self.assertGreater(image.width, 1750)
            self.assertEqual(image.getpixel((400, 400))[3], 255)

    def test_ocg_toggle_recomputes_exact_crop(self):
        pdf_file = self.folder / 'ocg.pdf'
        with fitz.open() as pdf:
            page = pdf.new_page(width=400, height=400)
            main = pdf.add_ocg('Main', on=1)
            extra = pdf.add_ocg('Extra', on=1)
            page.draw_rect(fitz.Rect(100, 100, 300, 300), color=None, fill=(.2,.3,.4), oc=main)
            page.draw_rect(fitz.Rect(15, 15, 35, 35), color=None, fill=(.2,.3,.4), oc=extra)
            pdf.save(pdf_file)
        with fitz.open(pdf_file) as pdf:
            both = find_content_crop(pdf[0], 1600, 1600)
            pdf.set_layer_ui_config(1, action=2)
            only_main = find_content_crop(pdf[0], 1600, 1600)
            pdf.set_layer_ui_config(1, action=0)
            restored = find_content_crop(pdf[0], 1600, 1600)
        self.assertEqual(both, restored)
        self.assertEqual(only_main, (400, 400, 1200, 1200))
        self.assertLess(both[0], only_main[0])

    def test_scan_cancel_leaves_no_output_or_temporary_file(self):
        output = self.folder / 'cancelled.png'
        calls = [0]
        def cancelled():
            calls[0] += 1
            return calls[0] > 2
        with DrawingDocument(self.source) as drawing:
            with self.assertRaises(DrawingError):
                drawing.export_image(output, OutputOptions('png', 'custom', 3600, 3600,
                              crop_margins=True), cancelled=cancelled)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.folder.glob('.drawing-*')), [])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.sha)


if __name__ == '__main__':
    unittest.main()
