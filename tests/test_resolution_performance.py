"""Original-first export options, aspect-ratio safety, and bounded fast raster stripes."""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import patch

import fitz
from PIL import Image

from drawing_editor.core import (DrawingDocument, DrawingError, OutputOptions,
                                 preview_snapshot, _thread_document)
from drawing_editor.batch import plan_exports, run_batch_exports
from drawing_editor.tiles import raster_stripes, save_png_tiled


class RasterCountingPage:
    def __init__(self, page):
        self._page = page
        self.rect = page.rect
        self.calls = 0

    def get_pixmap(self, **kwargs):
        self.calls += 1
        return self._page.get_pixmap(**kwargs)


class ResolutionTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.landscape = self.folder / 'landscape.pdf'
        self.portrait = self.folder / 'portrait.pdf'
        for path, wh in ((self.landscape, (720, 360)),
                         (self.portrait, (360, 720))):
            with fitz.open() as doc:
                page = doc.new_page(width=wh[0], height=wh[1])
                layer = doc.add_ocg('도로')
                shape = page.new_shape()
                shape.draw_rect(fitz.Rect(20, 20, wh[0]-20,wh[1]-20))
                shape.finish(color=(1, 0, 0), fill=(.2,.7,.3),oc=layer)
                shape.commit()
                doc.save(path)

    def test_original_is_unmodified_default(self):
        with DrawingDocument(self.landscape) as doc:
            self.assertEqual(doc.export_dimensions(), doc.export_dimensions(OutputOptions()))
            self.assertEqual(doc.export_dimensions()[:2], (3000,1500))

    def test_presets_keep_aspect_in_both_orientations(self):
        for source, expected in ((self.landscape,(1920,960)),
                                 (self.portrait,(960,1920))):
            with DrawingDocument(source) as doc:
                self.assertEqual(doc.export_dimensions(OutputOptions('png','fhd'))[:2],expected)
                self.assertEqual(doc.export_dimensions(OutputOptions('png','uhd'))[:2],
                                 tuple(n*2 for n in expected))

    def test_custom_bounds_not_stretched_or_upscaled_to_both_axes(self):
        with DrawingDocument(self.landscape) as doc:
            opts=OutputOptions('png','custom',width=975,height=925)
            self.assertEqual(doc.export_dimensions(opts)[:2],(975,488))
            target=self.folder/'custom.png'
            doc.export_image(target,opts)
            with Image.open(target) as im:
                self.assertEqual(im.size,(975,488))

    def test_dpi_and_jpeg_metadata(self):
        with DrawingDocument(self.landscape) as doc:
            opts=OutputOptions('jpg','dpi',dpi=144)
            self.assertEqual(doc.export_dimensions(opts),(1440,720,144))
            path=self.folder/'dpi.jpg'
            doc.export_image(path,opts)
        with Image.open(path) as im:
            self.assertEqual(im.size,(1440,720))
            self.assertEqual(im.format,'JPEG')
            self.assertAlmostEqual(im.info['dpi'][0],144,delta=2)

    def test_png_manual_tiled_exceeds_small_image_limit(self):
        source=self.portrait
        sha=hashlib.sha256(source.read_bytes()).hexdigest()
        with DrawingDocument(source) as doc:
            opts=OutputOptions('png','custom',width=3000,height=5500)
            result=doc.export_dimensions(opts)
            self.assertEqual(result[:2],(2750,5500))
            target=self.folder/'large.png'
            doc.export_image(target,opts)
            with Image.open(target) as im:
                self.assertEqual(im.size, result[:2])
        self.assertEqual(sha, hashlib.sha256(source.read_bytes()).hexdigest())

    def test_batch_export_uses_one_resolution_policy_per_file(self):
        with DrawingDocument(self.landscape) as first, DrawingDocument(self.portrait) as second:
            opts=OutputOptions('png','fhd')
            jobs=plan_exports([first,second],self.folder,opts)
            result=run_batch_exports(jobs,opts)
        self.assertEqual(result.errors,())
        self.assertEqual(len(result.completed),2)
        sizes=[]
        for dest in result.completed:
            with Image.open(dest) as im:
                sizes.append(im.size)
        self.assertEqual(sizes,[(1920,960),(960,1920)])

    def test_invalid_options_rejected(self):
        for opts in (OutputOptions('bmp'), OutputOptions('png','bad'),
                     OutputOptions('png','custom',width=0,height=500),
                     OutputOptions('jpg','custom',width=100,height=None),
                     OutputOptions('png','dpi',dpi=0),
                     OutputOptions('png','dpi',dpi=5000)):
            with self.subTest(opts=opts),self.assertRaises(DrawingError):
                opts.checked()

    def test_full_width_stripes_reduce_raster_calls(self):
        with fitz.open(self.landscape) as pdf:
            page=RasterCountingPage(pdf[0])
            width,height=2340,1900
            output=BytesIO()
            save_png_tiled(page,output,width,height,144)
            # With 512-wide tiles, each stripe required five get_pixmap
            # calls. Full-width band uses one call for each y strip.
            self.assertLessEqual(page.calls,5)
            with Image.open(BytesIO(output.getvalue())) as im:
                self.assertEqual(im.size,(width,height))

    def test_repeat_preview_uses_geometry_and_image_cache(self):
        first = preview_snapshot(str(self.landscape), {}, 0, (500,320))
        doc = _thread_document(str(self.landscape))
        with patch.object(doc, '_get_page_context', side_effect=AssertionError('unnecessary reopen')):
            second = preview_snapshot(str(self.landscape), {}, 0, (500,320))
        self.assertEqual(first, second)


if __name__ == '__main__':
    unittest.main()
