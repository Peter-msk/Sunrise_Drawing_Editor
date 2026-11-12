"""PNG white-paper crop, including large tiled output and page content safety."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import hashlib
import tempfile
import unittest

import fitz
from PIL import Image

from drawing_editor.core import DrawingDocument, DrawingError, OutputOptions
from drawing_editor.trim import find_content_crop, image_ink_bbox


class OnMapCropTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.pdf = self.folder / 'map-with-paper.pdf'
        with fitz.open() as doc:
            page = doc.new_page(width=400, height=500)
            page.draw_rect(fitz.Rect(45, 60, 350, 400),
                           color=(.80, .50, .28), fill=(.97, .96, .93), width=1)
            page.draw_line(fitz.Point(50, 90), fitz.Point(335, 380), color=(0, .5, .8), width=2)
            # White map symbol INSIDE the content region must not be deleted.
            page.draw_rect(fitz.Rect(180, 200, 220, 235), color=None, fill=(1, 1, 1))
            doc.save(self.pdf)
        self.sha = hashlib.sha256(self.pdf.read_bytes()).hexdigest()

    def test_default_api_stays_full_canvas(self):
        with DrawingDocument(self.pdf) as doc:
            full = self.folder / 'full.png'
            doc.export_image(full, OutputOptions('png', 'custom', 800, 1000))
        with Image.open(full) as img:
            self.assertEqual(img.size, (800, 1000))
            self.assertEqual(img.getpixel((2, 2)), (255, 255, 255))
        self.assertEqual(self.sha, hashlib.sha256(self.pdf.read_bytes()).hexdigest())

    def test_content_region_crop_keeps_dpi_and_original_colors(self):
        with DrawingDocument(self.pdf) as doc:
            doc.export_image(self.folder / 'full.png', OutputOptions('png', 'custom', 800, 1000))
            doc.export_image(self.folder / 'cropped.png', OutputOptions('png', 'custom', 800, 1000,
                                                                        crop_margins=True))
        with Image.open(self.folder / 'full.png') as full, Image.open(self.folder / 'cropped.png') as crop:
            self.assertTrue(600 < crop.width < 665)
            self.assertTrue(675 < crop.height < 715)
            # The exact full-page source pixels remain unchanged in the crop.
            bounds = image_ink_bbox(full)
            self.assertEqual(crop.size, (bounds[2]-bounds[0], bounds[3]-bounds[1]))
            self.assertEqual(crop.tobytes(), full.crop(bounds).tobytes())
            self.assertIn((255, 255, 255), [crop.getpixel((i,j)) for i,j in
                                           [(crop.width//2,crop.height//2), (crop.width//2-10,crop.height//2)]])
        self.assertEqual(self.sha, hashlib.sha256(self.pdf.read_bytes()).hexdigest())

    def test_painted_white_paper_crops_but_keeps_white_map_symbol(self):
        path = self.folder / 'painted-paper.pdf'
        with fitz.open() as pdf:
            page = pdf.new_page(width=200, height=200)
            page.draw_rect(page.rect, fill=(1,1,1), color=None)
            page.draw_rect(fitz.Rect(40, 50, 160, 165), fill=(.92,.82,.65), color=None)
            page.draw_rect(fitz.Rect(85, 85, 110, 112), fill=(1,1,1), color=None)
            pdf.save(path)
        with DrawingDocument(path) as doc:
            doc.export_image(self.folder/'painted.png', OutputOptions('png', 'custom', 400, 400,
                                                                      background='transparent', crop_margins=True))
        with Image.open(self.folder/'painted.png') as im:
            self.assertLess(im.width, 260)
            self.assertLess(im.height, 260)
            self.assertEqual(im.mode, 'RGBA')
            # White drawn symbol is still entirely opaque.
            self.assertEqual(im.getpixel((120, 120)), (255, 255, 255, 255))

    def test_blank_page_falls_back_without_cropping(self):
        p = self.folder/'blank.pdf'
        with fitz.open() as d:
            d.new_page(width=300, height=150)
            d.save(p)
        with DrawingDocument(p) as d:
            d.export_image(self.folder/'blank.png', OutputOptions('png','custom',600,300,
                                                                  crop_margins=True))
        with Image.open(self.folder/'blank.png') as im:
            self.assertEqual(im.size, (600, 300))

    def test_large_tiled_cropped_png_preserves_map(self):
        with DrawingDocument(self.pdf) as doc:
            doc.export_image(self.folder/'large.png', OutputOptions('png','custom',5000,6250,
                                                                    crop_margins=True,background='transparent'))
        with Image.open(self.folder/'large.png') as im:
            self.assertLess(im.width, 4500)
            self.assertLess(im.height, 4800)
            self.assertEqual(im.mode,'RGBA')
            self.assertEqual(im.getpixel((im.width//2,im.height//2))[3],255)
        self.assertEqual(self.sha, hashlib.sha256(self.pdf.read_bytes()).hexdigest())

    def test_tile_clip_matches_uncropped_full_page_pixel(self):
        # Use a large, but cheap, synthetic PDF raster to check offset in tile path.
        with fitz.open(self.pdf) as doc:
            p=doc[0]
            bounds=find_content_crop(p,1600,2000)
            self.assertIsNotNone(bounds)
            from drawing_editor.tiles import save_png_tiled
            full_stream=BytesIO()
            save_png_tiled(p, full_stream, 1600, 2000, 144)
            stream=BytesIO()
            save_png_tiled(p,stream,bounds[2]-bounds[0],bounds[3]-bounds[1],144,
                           source_rect=(bounds[0],bounds[1],1600,2000))
            with Image.open(BytesIO(full_stream.getvalue())) as full, \
                    Image.open(BytesIO(stream.getvalue())) as cropped:
                expected=full.crop(bounds)
                try:
                    self.assertEqual(cropped.size,expected.size)
                    self.assertEqual(cropped.tobytes(),expected.tobytes())
                finally:
                    expected.close()

    def test_jpg_or_invalid_crop_setting_rejected(self):
        with self.assertRaises(DrawingError):
            OutputOptions('jpg',crop_margins=True).checked()
        with self.assertRaises(DrawingError):
            OutputOptions('png',crop_margins='yes').checked()

    def test_gui_has_independent_crop_control(self):
        win = (Path(__file__).parents[1]/'drawing_editor/window.py').read_text('utf-8')
        self.assertIn("self.crop_png.setObjectName('cropPngMarginsCheck')", win)
        self.assertIn('self.crop_png.setChecked(True)',win)
        self.assertIn('crop_margins=(self.png_button.isChecked() and self.crop_png.isChecked())',win)

if __name__=='__main__':
    unittest.main()
