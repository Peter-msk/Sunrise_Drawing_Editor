"""PNG background policy: preserve native layers and geometry; opt-in alpha only."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import hashlib
import tempfile
import unittest

import fitz
from PIL import Image

from drawing_editor.core import DrawingDocument, DrawingError, OutputOptions
from drawing_editor.tiles import save_png_tiled


class PNGTransparencyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.pdf = self.folder / 'onmap-alpha-check.pdf'
        with fitz.open() as doc:
            page = doc.new_page(width=200, height=100)
            # A small painted map region and a white-filled source object:
            # true source white must never be turned transparent accidentally.
            page.draw_rect(fitz.Rect(20, 20, 80, 70), color=None, fill=(0, .6, .2))
            page.draw_rect(fitz.Rect(100, 25, 170, 75), color=None, fill=(1, 1, 1))
            doc.save(self.pdf)
        self.original_sha = hashlib.sha256(self.pdf.read_bytes()).hexdigest()

    def test_default_png_stays_opaque_and_transparent_option_is_opt_in(self):
        with DrawingDocument(self.pdf) as doc:
            doc.export_image(self.folder / 'old.png', OutputOptions('png', 'custom', 400, 200))
            doc.export_image(self.folder / 'alpha.png',
                             OutputOptions('png', 'custom', 400, 200,
                                           background='transparent'))
        with Image.open(self.folder / 'old.png') as original, Image.open(self.folder / 'alpha.png') as result:
            self.assertEqual(original.mode, 'RGB')
            self.assertEqual(result.mode, 'RGBA')
            self.assertEqual(original.getpixel((5,5)), (255,255,255))
            self.assertEqual(result.getpixel((5,5))[3], 0)
            self.assertEqual(result.getpixel((80,80))[3], 255)
            # White objects explicitly drawn in the PDF are real map content.
            self.assertEqual(result.getpixel((240,100)), (255,255,255,255))
        self.assertEqual(self.original_sha, hashlib.sha256(self.pdf.read_bytes()).hexdigest())

    def test_transparent_png_tiling_alpha_and_dimensions(self):
        with fitz.open(self.pdf) as doc:
            stream = BytesIO()
            save_png_tiled(doc[0], stream, 2400, 600, 144, transparent=True)
        with Image.open(BytesIO(stream.getvalue())) as im:
            self.assertEqual(im.mode,'RGBA')
            self.assertEqual(im.size,(2400,600))
            self.assertEqual(im.getpixel((6,6))[3],0)
            self.assertEqual(im.getpixel((360,300))[3],255)
            self.assertEqual(im.getpixel((1300,300)),(255,255,255,255))

    def test_transparent_large_export_uses_streaming_rgba(self):
        # >12 megapixels forces the production tiled path.
        with DrawingDocument(self.pdf) as doc:
            output = self.folder / 'tiled-alpha.png'
            doc.export_image(output, OutputOptions('png', 'custom', 5000, 2500,
                                                   background='transparent'))
        with Image.open(output) as im:
            self.assertEqual(im.size, (5000,2500))
            self.assertEqual(im.mode, 'RGBA')
            self.assertEqual(im.getpixel((10,10))[3],0)
            self.assertEqual(im.getpixel((900,900))[3],255)
        self.assertEqual(self.original_sha, hashlib.sha256(self.pdf.read_bytes()).hexdigest())

    def test_render_bytes_png_option_and_cache_isolated(self):
        with DrawingDocument(self.pdf) as doc:
            opaque = doc.render_bytes(OutputOptions('png'), preview=(400,200))
            clear = doc.render_bytes(OutputOptions('png',background='transparent'),
                                     preview=(400,200))
            opaque_again = doc.render_bytes(OutputOptions('png'), preview=(400,200))
        with Image.open(BytesIO(opaque)) as first, Image.open(BytesIO(clear)) as second:
            self.assertEqual(first.mode, 'RGB')
            self.assertEqual(second.mode,'RGBA')
            self.assertEqual(second.getpixel((5,5))[3],0)
        self.assertEqual(opaque,opaque_again)

    def test_jpeg_does_not_silently_discard_transparency(self):
        with self.assertRaises(DrawingError):
            OutputOptions('jpg', background='transparent').checked()
        with self.assertRaises(DrawingError):
            OutputOptions('png', background='invalid').checked()

    def test_empty_page_transparent_vs_opaque(self):
        blank = self.folder / 'blank.pdf'
        with fitz.open() as d:
            d.new_page(width=100,height=60)
            d.save(blank)
        with DrawingDocument(blank) as d:
            d.export_image(self.folder/'blank-alpha.png',
                           OutputOptions('png','custom',300,180,background='transparent'))
        with Image.open(self.folder/'blank-alpha.png') as im:
            self.assertEqual(im.mode,'RGBA')
            self.assertEqual(im.getpixel((150,90))[3],0)


if __name__=='__main__':
    unittest.main()
