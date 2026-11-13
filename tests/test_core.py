"""Executable engine tests for original-quality image exporting and fast OCG UI toggling."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from PIL import Image, ImageChops
import ezdxf
import fitz
import hashlib
import tempfile
import unittest

from drawing_editor.core import (
    DrawingDocument, DrawingError, OutputOptions,
    _thread_document, render_snapshot, preview_snapshot, export_snapshot,
    close_thread_document,
)


def create_pdf(path: Path):
    pdf = fitz.open()
    pg = pdf.new_page(width=400, height=300)
    red = pdf.add_ocg('하천')
    blue = pdf.add_ocg('도로')
    shape = pg.new_shape()
    shape.draw_rect(fitz.Rect(10, 10, 180, 120))
    shape.finish(fill=(1, 0, 0), color=(1, 0, 0), oc=red)
    shape.commit()
    shape = pg.new_shape()
    shape.draw_rect(fitz.Rect(220, 120, 380, 280))
    shape.finish(fill=(0, 0, 1), color=(0, 0, 1), oc=blue)
    shape.commit()
    pdf.save(path)
    pdf.close()


def create_raster_pdf(path: Path):
    image = Image.new('RGB', (1200, 800), (220, 120, 70))
    buf = BytesIO()
    image.save(buf, format='PNG')
    pdf = fitz.open()
    pg = pdf.new_page(width=600, height=400)
    pg.insert_image(pg.rect, stream=buf.getvalue())
    pdf.save(path)
    pdf.close()


def create_dxf(path: Path):
    dxf = ezdxf.new('R2013')
    dxf.layers.new('하천')
    dxf.layers.new('도로')
    dxf.modelspace().add_circle((20, 20), 10, dxfattribs={'layer': '하천'})
    dxf.modelspace().add_line((0, 0), (35, 36), dxfattribs={'layer': '도로'})
    dxf.saveas(path)


def image_from_bytes(blob):
    image = Image.open(BytesIO(blob))
    image.load()
    return image


class DrawingCoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(close_thread_document)
        self.directory = Path(tmp.name)
        self.pdf = self.directory / 'layered.pdf'
        self.dxf = self.directory / 'sample.dxf'
        create_pdf(self.pdf)
        create_dxf(self.dxf)

    def test_release_cached_document_closes_native_pdf_handle(self):
        preview_snapshot(str(self.pdf), {}, 0, (320, 240))
        cached = _thread_document(str(self.pdf))
        self.assertIsNotNone(cached._pdf)
        close_thread_document()
        self.assertIsNone(cached._pdf)
        self.assertIsNone(_thread_document.__globals__['_cache'].document)

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_live_pdf_ocg_without_serialization_and_original_protected(self):
        old = self.sha(self.pdf)
        with DrawingDocument(self.pdf) as doc:
            self.assertFalse(doc._serialize_fallback)
            self.assertEqual(len(doc._pdf_ui_map), 2)
            default = image_from_bytes(doc.render_bytes(preview=(420, 320)))
            doc.set_visibility(doc.layers()[0].key, False)
            changed = image_from_bytes(doc.render_bytes(preview=(420, 320)))
            self.assertIsNotNone(ImageChops.difference(default, changed).getbbox())
            doc.set_visibility(doc.layers()[0].key, True)
            restored = image_from_bytes(doc.render_bytes(preview=(420, 320)))
            self.assertIsNone(ImageChops.difference(default, restored).getbbox())
        self.assertEqual(old, self.sha(self.pdf))

    def test_dxf_visibility_and_original_protected(self):
        old = self.sha(self.dxf)
        with DrawingDocument(self.dxf) as doc:
            self.assertIn('하천', doc.states())
            original = image_from_bytes(doc.render_bytes(preview=(420, 320)))
            doc.set_visibility('하천', False)
            changed = image_from_bytes(doc.render_bytes(preview=(420, 320)))
            self.assertIsNotNone(ImageChops.difference(original, changed).getbbox())
            doc.set_visibility('하천', True)
            again = image_from_bytes(doc.render_bytes(preview=(420, 320)))
            self.assertIsNone(ImageChops.difference(original, again).getbbox())
        self.assertEqual(old, self.sha(self.dxf))

    def test_batch_changes_only_once(self):
        with DrawingDocument(self.pdf) as doc:
            initial = doc.states()
            target = {key: False for key in initial}
            doc.apply_snapshot(target)
            self.assertTrue(all(not s for s in doc.states().values()))
            doc.apply_snapshot(initial)
            self.assertFalse(doc.dirty)

    def test_native_raster_pixel_dimensions(self):
        target = self.directory / 'raster.pdf'
        create_raster_pdf(target)
        with DrawingDocument(target) as doc:
            self.assertEqual(doc.export_dimensions()[:2], (1200, 800))
            output = self.directory / 'raster.png'
            doc.export_image(output, OutputOptions('png'))
            with Image.open(output) as image:
                self.assertEqual(image.size, (1200, 800))

    def test_vector_auto_size_no_4k_cap(self):
        with DrawingDocument(self.pdf) as doc:
            w, h, dpi = doc.export_dimensions()
            self.assertEqual(dpi, 300)
            self.assertEqual((w, h), (1667, 1250))
            image = image_from_bytes(doc.render_bytes(OutputOptions('png')))
            self.assertEqual(image.size, (w, h))

    def test_png_jpg_output_and_format(self):
        with DrawingDocument(self.pdf) as doc:
            for fmt in ('png', 'jpg'):
                with self.subTest(fmt=fmt):
                    target = self.directory / ('result.' + fmt)
                    doc.export_image(target, OutputOptions(fmt))
                    with Image.open(target) as image:
                        self.assertEqual(image.size, doc.export_dimensions()[:2])
                        self.assertEqual(image.format, 'PNG' if fmt == 'png' else 'JPEG')

    def test_blank_cad_no_crash(self):
        with DrawingDocument(self.dxf) as doc:
            doc.set_all(False)
            result = image_from_bytes(doc.render_bytes(preview=(440, 300)))
            self.assertEqual(result.size, (440, 300))
            self.assertEqual(result.getpixel((100, 100)), (255, 255, 255))

    def test_thread_local_cache_reuse_and_switch(self):
        first = _thread_document(str(self.pdf))
        self.assertIs(first, _thread_document(str(self.pdf)))
        second = _thread_document(str(self.dxf))
        self.assertIsNot(first, second)
        self.assertIs(second, _thread_document(str(self.dxf)))

    def test_preview_snapshot_uses_source_state_and_no_update_to_file(self):
        digest = self.sha(self.pdf)
        with DrawingDocument(self.pdf) as doc:
            states = doc.states()
            key = doc.layers()[0].key
        before = render_snapshot(str(self.pdf), states, 0, (600, 450))
        states[key] = False
        after = render_snapshot(str(self.pdf), states, 0, (600, 450))
        self.assertNotEqual(before, after)
        self.assertEqual(self.sha(self.pdf), digest)

    def test_export_snapshot(self):
        with DrawingDocument(self.pdf) as doc:
            states = doc.states()
            states[doc.layers()[-1].key] = False
        target = self.directory / 'result.png'
        actual = export_snapshot(str(self.pdf), states, 0,
                                 str(target), OutputOptions('png'))
        # Windows may normalize 8.3 paths (RUNNER~1) to long names.
        self.assertTrue(Path(actual).samefile(target))
        self.assertTrue(target.is_file())

    def test_no_overwrite_and_no_partials(self):
        target = self.directory / 'existing.png'
        target.write_bytes(b'EXISTING')
        with DrawingDocument(self.pdf) as doc:
            with self.assertRaises(DrawingError):
                doc.export_image(target, OutputOptions('png'))
        self.assertEqual(target.read_bytes(), b'EXISTING')
        self.assertFalse(list(self.directory.glob('.drawing-*.tmp')))

    def test_tiled_large_png_exceeds_prior_50mp_limit(self):
        # 6438 x 9308 px, identical to the field failure class; no huge source bitmap.
        large = self.directory / 'large.pdf'
        doc = fitz.open()
        p = doc.new_page(width=6438 * 72 / 300, height=9308 * 72 / 300)
        p.draw_rect(fitz.Rect(4, 4, 18, 18), color=(1, 0, 0), fill=(1, 0, 0))
        doc.save(large)
        doc.close()
        with DrawingDocument(large) as viewer:
            w, h, dpi = viewer.export_dimensions()
            self.assertEqual((w, h), (6438, 9308))
            output = self.directory / 'large.png'
            viewer.export_image(output, OutputOptions('png'))
            with Image.open(output) as image:
                self.assertEqual(image.size, (6438, 9308))
                self.assertEqual(image.format, 'PNG')
                image.crop((0,0,200,200)).load()

    def test_tiled_matches_full_render(self):
        with DrawingDocument(self.pdf) as doc:
            target = self.directory / 'compare.png'
            doc.export_image(target, OutputOptions('png'))
            full = image_from_bytes(doc.render_bytes())
            with Image.open(target) as tiled:
                self.assertEqual(tiled.size,full.size)
                self.assertIsNone(ImageChops.difference(tiled.convert('RGB'),full.convert('RGB')).getbbox())

    def test_export_cancel_cleans_partial(self):
        with DrawingDocument(self.pdf) as doc:
            target = self.directory / 'canceled.png'
            with self.assertRaisesRegex(DrawingError, '취소'):
                doc.export_image(target, OutputOptions('png'), cancelled=lambda: True)
            self.assertFalse(target.exists())
            self.assertFalse(list(self.directory.glob('.drawing-*.png')))

    def test_zoom_clip_changes_pixels(self):
        with DrawingDocument(self.pdf) as doc:
            whole = image_from_bytes(doc.render_bytes(preview=(400,300)))
            crop = image_from_bytes(doc.render_bytes(preview=(400,300), clip=(0,0,200,150)))
            self.assertEqual(crop.size,(400,300))
            self.assertNotEqual(crop.tobytes(),whole.tobytes())

    def test_zoom_region_respects_latest_ocg_toggle(self):
        with DrawingDocument(self.pdf) as doc:
            initial = doc.states()
            key = doc.layers()[0].key
        region = (0., 0., 200., 150.)
        before = render_snapshot(str(self.pdf), initial, 0, (800, 600), clip=region)
        initial[key] = False
        after = render_snapshot(str(self.pdf), initial, 0, (800, 600), clip=region)
        self.assertNotEqual(before, after)

    def test_preview_snapshot_size_and_bounded_cache(self):
        with DrawingDocument(self.pdf) as doc:
            states = doc.states()
        data, page_size = preview_snapshot(str(self.pdf), states, 0, (500, 350))
        self.assertEqual(page_size, (400., 300.))
        with Image.open(BytesIO(data)) as image:
            self.assertTrue(image.width <= 500)
        cached = _thread_document(str(self.pdf))
        # Cached snapshots reuse bytes for identical layer/page/view combinations.
        data2, _ = preview_snapshot(str(self.pdf), states, 0, (500, 350))
        self.assertIs(data, data2)
        self.assertLessEqual(len(cached._preview_cache), 6)

    def test_large_jpg_streamed_tile_staging(self):
        large = self.directory / 'large_jpg.pdf'
        doc = fitz.open()
        p = doc.new_page(width=6438 * 72 / 300, height=9308 * 72 / 300)
        p.draw_line(fitz.Point(5, 5), fitz.Point(100, 100), color=(0, .3, .6))
        doc.save(large)
        doc.close()
        with DrawingDocument(large) as drawing:
            target = self.directory / 'large.jpg'
            drawing.export_image(target, OutputOptions('jpg'))
            with Image.open(target) as image:
                self.assertEqual(image.size,(6438,9308))
                self.assertEqual(image.format,'JPEG')
        self.assertFalse(list(self.directory.glob('.drawing-rgb-*.raw')))

    def test_invalid_format(self):
        with self.assertRaises(DrawingError):
            OutputOptions('webp').checked()

    def test_dwg_missing_dependency_reports_explicitly(self):
        path = self.directory / 'test.dwg'
        path.write_bytes(b'not-a-real-DWG')
        from ezdxf.addons import odafc
        if not odafc.is_installed():
            with self.assertRaisesRegex(DrawingError, 'ODA File Converter'):
                DrawingDocument(path)


if __name__ == '__main__':
    unittest.main()


class LargeCadCacheTests(unittest.TestCase):
    def test_switching_cad_layers_back_reuses_pdf_render(self):
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / 'layers.dxf'
            create_dxf(src)
            with DrawingDocument(src) as doc:
                original = doc.render_bytes(preview=(400, 300))
                self.assertEqual(doc._cad_render_count, 1)
                doc.set_visibility('하천', False)
                changed = doc.render_bytes(preview=(400, 300))
                self.assertNotEqual(original, changed)
                self.assertEqual(doc._cad_render_count, 1)  # native PDF OCG switch
                doc.set_visibility('하천', True)
                self.assertEqual(doc.render_bytes(preview=(400, 300)), original)
                self.assertEqual(doc._cad_render_count, 1)  # restored by OCG, not PDF rebuild
