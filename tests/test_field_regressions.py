"""Engine field-regressions for irregular PDF geometry and source preservation.

Only the drawing engine is executed here; these tests do not claim a Windows UI
or customer-original runtime pass.
"""
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


def make_irregular_pdf(path: Path, width: float, height: float, angle: int):
    with fitz.open() as pdf:
        page = pdf.new_page(width=width, height=height)
        line = pdf.add_ocg('현황 레이어')
        box = pdf.add_ocg('끄기 시험')
        s = page.new_shape()
        s.draw_line(fitz.Point(width*.07,height*.1),fitz.Point(width*.93,height*.91))
        s.finish(color=(0.1,.4,.8),width=1.6,oc=line)
        s.commit()
        s = page.new_shape()
        s.draw_rect(fitz.Rect(width*.2,height*.25,width*.8,height*.76))
        s.finish(color=(.7,.1,.4),fill=(.8,.4,.2),oc=box)
        s.commit()
        page.set_rotation(angle)
        pdf.save(path)


class IrregularDocumentFieldTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.folder = Path(t.name)

    def test_fractional_pages_and_rotation_have_exact_pixel_contract(self):
        cases = [(532.3658593,77.5192266,0),
                 (304.786555,68.782398,180),
                 (343.9236479,77.48997,90),
                 (261.2980966,105.0910096,270)]
        for i, (w, h, rotation) in enumerate(cases):
            with self.subTest(rotation=rotation,i=i):
                source = self.folder / f'국토 도면 {i}.pdf'
                make_irregular_pdf(source,w,h,rotation)
                sha = hashlib.sha256(source.read_bytes()).hexdigest()
                with DrawingDocument(source) as drawing:
                    expected = drawing.export_dimensions()[:2]
                    actual = self.folder / f'output_{i}.png'
                    drawing.export_image(actual,OutputOptions('png'))
                    with Image.open(actual) as raster:
                        self.assertEqual(raster.size, expected)
                    with fitz.open(source) as pdf:
                        page = pdf[0]
                        tile = BytesIO()
                        save_png_tiled(page,tile,*expected,300)
                        direct = Image.open(BytesIO(_render_page(page,'png',None)))
                        tiled = Image.open(BytesIO(tile.getvalue()))
                        direct.load(); tiled.load()
                        self.assertEqual(direct.size,expected)
                        self.assertEqual(tiled.size,expected)
                        # PDF clip rasterization may have subpixel AA variations
                        # at tile joins. Treat severe seams or color drift as
                        # regressions, while preserving exact output dimensions.
                        diff = ImageChops.difference(direct, tiled)
                        red, green, blue = diff.split()
                        mask = ImageChops.lighter(ImageChops.lighter(red, green), blue)
                        self.assertLessEqual(mask.getextrema()[1], 16)
                        changed = sum(mask.histogram()[1:])
                        self.assertLess(changed / (expected[0] * expected[1]), .003)
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),sha)

    def test_jpg_large_tiled_dimension(self):
        source = self.folder/'large ratio.pdf'
        make_irregular_pdf(source,452.381,163.789,90)
        with fitz.open(source) as pdf:
            page=pdf[0]
            width,height=1277,3528
            out=self.folder/'tiled.jpg'
            save_jpg_tiled(page,out,width,height,300, cancelled=lambda:False)
        with Image.open(out) as image:
            self.assertEqual(image.size,(width,height))
            self.assertEqual(image.format,'JPEG')

    def test_pdf_layer_change_zoom_and_reexport(self):
        source = self.folder/'one sheet.pdf'
        make_irregular_pdf(source,413.5,573.2,270)
        original = hashlib.sha256(source.read_bytes()).hexdigest()
        with DrawingDocument(source) as drawing:
            p0 = drawing.render_bytes(preview=(580,440))
            key = next(layer.key for layer in drawing.layers() if layer.name == '끄기 시험')
            drawing.set_visibility(key,False)
            p1 = drawing.render_bytes(preview=(580,440))
            self.assertNotEqual(p0,p1)
            size = drawing.page_size()
            clip=(size[0]*.15,size[1]*.10,size[0]*.81,size[1]*.89)
            detail = drawing.render_bytes(preview=(780,600),clip=clip)
            self.assertTrue(detail.startswith(b'\x89PNG'))
            saved = self.folder/'rendered.png'
            drawing.export_image(saved,OutputOptions('png'))
            drawing.set_visibility(key,True)
            self.assertEqual(drawing.render_bytes(preview=(580,440)),p0)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),original)

if __name__ == '__main__':
    unittest.main()
