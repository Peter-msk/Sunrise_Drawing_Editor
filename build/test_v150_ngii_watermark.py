"""Synthetic OCG regression; real NGII fingerprint sample is a separate QA gate."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz
from PIL import Image

from drawing_editor import ngii_watermark as wm
from drawing_editor.core import DrawingDocument, OutputOptions, close_thread_document
from drawing_editor.batch import ExportJob, run_batch_exports
from drawing_editor.vector_export import export_vector_snapshot
from drawing_editor.layer_tools import plan_advanced_exports
from drawing_editor.state import DrawingState


class WatermarkTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.addCleanup(close_thread_document)
        self.root = Path(folder.name)
        self.path = self.root / 'synthetic.pdf'
        with fitz.open() as pdf:
            self.road = pdf.add_ocg('ROAD', on=True)
            self.water = pdf.add_ocg('WATER', on=False)
            page = pdf.new_page(width=300, height=200)
            page.draw_rect(fitz.Rect(0, 0, 300, 200), color=None, fill=(0, .7, 0), oc=self.road)
            page.draw_rect(fitz.Rect(0, 0, 50, 50), color=None, fill=(0, 0, 1), oc=self.water)
            self.logo = self.add_image(pdf, page, fitz.Rect(70, 40, 170, 70), (255, 0, 0, 180))
            page.insert_image(fitz.Rect(70, 100, 170, 130), xref=self.logo)
            self.mask = int(pdf.xref_get_key(self.logo, 'SMask')[1].split()[0])
            self.rgb_hash = sha256(pdf.xref_stream(self.logo)).hexdigest()
            self.mask_hash = sha256(pdf.xref_stream(self.mask)).hexdigest()
            page = pdf.new_page(width=300, height=200)
            page.draw_rect(page.rect, color=None, fill=(0, .7, 0), oc=self.road)
            page.insert_image(fitz.Rect(70, 40, 170, 70), xref=self.logo)
            pdf.save(self.path)
        self.before = self.path.read_bytes()

    @staticmethod
    def add_image(pdf, page, rect, color):
        buf = BytesIO()
        Image.new('RGBA', (1280, 385), color).save(buf, format='PNG')
        xref = page.insert_image(rect, stream=buf.getvalue())
        mask = int(pdf.xref_get_key(xref, 'SMask')[1].split()[0])
        # Match the direct DeviceRGB/DeviceGray representation in the supplied patch.
        pdf.xref_set_key(xref, 'ColorSpace', '/DeviceRGB')
        pdf.xref_set_key(mask, 'ColorSpace', '/DeviceGray')
        return xref

    def recognize_fixture(self):
        return patch.multiple(wm, _RGB_SHA256=self.rgb_hash, _MASK_SHA256=self.mask_hash)

    def test_production_fingerprints_do_not_match_synthetic_image(self):
        with DrawingDocument(self.path) as doc:
            self.assertEqual(doc.states(), {self.road: True, self.water: False})
        self.assertEqual(self.path.read_bytes(), self.before)

    def test_toggle_restore_all_off_and_pixels(self):
        with fitz.open(self.path) as original:
            baseline = original[0].get_pixmap().samples
        with self.recognize_fixture(), DrawingDocument(self.path) as doc:
            item = next(l for l in doc.layers() if l.name == wm.LAYER_NAME)
            self.assertTrue(item.visible)
            self.assertFalse(item.locked)
            self.assertFalse(doc.states()[self.water])
            self.assertEqual(doc._pdf[0].get_pixmap().samples, baseline)
            on = doc.render_bytes(preview=(300, 200))
            doc.set_visibility(item.key, False)
            off = doc.render_bytes(preview=(300, 200))
            with Image.open(BytesIO(on)) as a, Image.open(BytesIO(off)) as b:
                a, b = a.convert('RGB'), b.convert('RGB')
                self.assertNotEqual(a.tobytes(), b.tobytes())
                for y in range(200):
                    for x in range(300):
                        if not (69 <= x <= 171 and (39 <= y <= 71 or 99 <= y <= 131)):
                            self.assertEqual(a.getpixel((x,y)), b.getpixel((x,y)))
            doc.set_visibility(item.key, True)
            self.assertEqual(doc.render_bytes(preview=(300, 200)), on)
            doc.set_all(False)
            with Image.open(BytesIO(doc.render_bytes(preview=(300, 200)))) as img:
                self.assertEqual(img.convert('RGB').getextrema(), ((255,255),)*3)
            doc.page_index = 1
            with Image.open(BytesIO(doc.render_bytes(preview=(300, 200)))) as img:
                self.assertEqual(img.convert('RGB').getextrema(), ((255,255),)*3)
        self.assertEqual(self.path.read_bytes(), self.before)

    def test_raster_batch_and_vector_outputs(self):
        with self.recognize_fixture(), DrawingDocument(self.path) as doc:
            key = next(l.key for l in doc.layers() if l.name == wm.LAYER_NAME)
            doc.set_visibility(key, False)
            states = doc.states()
            self.assertEqual(doc._pdf.get_oc(self.logo), key)
            for fmt in ('png', 'jpg'):
                dst = self.root / f'out.{fmt}'
                opts = OutputOptions(fmt=fmt, resolution='custom', width=300, height=200)
                result = run_batch_exports([ExportJob(str(self.path), states, 0, str(dst))], opts)
                self.assertFalse(result.errors, result.errors)
                self.assertTrue(dst.exists())
                with Image.open(dst) as img:
                    r,g,b = img.convert('RGB').getpixel((100,55))
                    self.assertLess(r, 10)
                    self.assertGreater(g, 160)
                    self.assertLess(b, 10)
            for fmt in ('pdf', 'svg'):
                dst = self.root / f'out.{fmt}'
                export_vector_snapshot(self.path, states, 0, dst, OutputOptions(fmt=fmt))
                self.assertTrue(dst.exists())
            with fitz.open(self.root / 'out.pdf') as pdf:
                self.assertFalse(pdf.get_ocgs()[key]['on'])
                self.assertEqual(pdf[0].get_pixmap().pixel(100,55), (0,178,0))
            with fitz.open(self.root / 'out.svg') as svg:
                # SVG conversion rounds the same green to 179 instead of 178.
                r, g, b = svg[0].get_pixmap().pixel(100,55)
                self.assertEqual((r, b), (0, 0))
                self.assertLessEqual(abs(g - 178), 1)
        self.assertEqual(self.path.read_bytes(), self.before)

    def test_group_and_combination_plan(self):
        with self.recognize_fixture(), DrawingDocument(self.path) as doc:
            state = DrawingState(self.path)
            state.load_metadata(doc.layers(), doc.pages)
            key = next(l.key for l in state.layers() if l.name == wm.LAYER_NAME)
            state.set_visibility(key, False)
            opts = OutputOptions(fmt='png', resolution='custom', width=300, height=200)
            jobs = plan_advanced_exports([state], self.root, opts, mode='groups', groups=['도로'])
            self.assertFalse(jobs[0].states[key])
            result = run_batch_exports(jobs, opts)
            self.assertFalse(result.errors, result.errors)
            jobs = plan_advanced_exports([state], self.root, opts, mode='groups', groups=['워터마크'])
            self.assertTrue(jobs[0].states[key])
            self.assertFalse(jobs[0].states[self.road])
            self.assertFalse(state.states()[key])

    def test_idempotence_and_existing_ocg_preserved(self):
        with self.recognize_fixture(), fitz.open(self.path) as pdf:
            old = pdf.add_ocg(wm.LAYER_NAME, on=False)
            pdf.set_layer(-1, locked=[old])
            key = wm.separate_watermark(pdf)
            self.assertNotEqual(old, key)
            self.assertFalse(pdf.get_ocgs()[old]['on'])
            self.assertIn(old, pdf.get_layer()['locked'])
            self.assertEqual(pdf.get_ocgs()[key]['name'], wm.LAYER_NAME+' (2)')
            self.assertIsNone(wm.separate_watermark(pdf))
            self.assertEqual(pdf.get_oc(self.logo), key)
        with self.recognize_fixture(), fitz.open(self.path) as pdf:
            pdf.set_oc(self.logo, self.road)
            self.assertIsNone(wm.separate_watermark(pdf))
            self.assertEqual(pdf.get_oc(self.logo), self.road)

    def test_mask_mismatch_and_same_size_other_image(self):
        with patch.multiple(wm, _RGB_SHA256=self.rgb_hash, _MASK_SHA256='0'*64), fitz.open(self.path) as pdf:
            self.assertIsNone(wm.separate_watermark(pdf))
        with self.recognize_fixture(), fitz.open(self.path) as pdf:
            other = self.add_image(pdf, pdf[0], fitz.Rect(180, 40, 280, 70), (10,20,30,180))
            self.assertIsNotNone(wm.separate_watermark(pdf))
            self.assertEqual(pdf.get_oc(other), 0)


if __name__ == '__main__':
    unittest.main()
