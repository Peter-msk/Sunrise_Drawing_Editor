"""R10: shared preview cache and bounded tiled fallback regression."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz
from drawing_editor import core, tiles


class PreviewCacheTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.addCleanup(core.close_thread_document)
        self.path = Path(temp.name) / 'map.pdf'
        with fitz.open() as pdf:
            self.layer = pdf.add_ocg('ROAD')
            for _ in range(2):
                page = pdf.new_page(width=120, height=80)
                page.draw_rect(fitz.Rect(10, 10, 110, 70), fill=(1,0,0), oc=self.layer)
            pdf.save(self.path)
        self.states = {self.layer: True}
        self.before = hashlib.sha256(self.path.read_bytes()).digest()

    def test_shared_cache_both_directions(self):
        with patch.object(core, '_render_page', wraps=core._render_page) as render:
            for page, size, overview_first in [(0,(600,400),False),(1,(900,600),True)]:
                def overview():
                    return core.preview_snapshot(str(self.path), self.states, page, size)[0]
                def detail():
                    return core.render_snapshot(str(self.path), self.states, page, size)
                a,b = (overview(),detail()) if overview_first else (detail(),overview())
                self.assertEqual(a,b)
            self.assertEqual(render.call_count,2)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(), self.before)

    def test_geometry_evicted_with_pixels_and_background_isolated(self):
        path = str(self.path)
        for i in range(8):
            core.preview_snapshot(path, self.states, 0, (100+i,100+i))
        doc = core._thread_document(path)
        self.assertLessEqual(len(doc._preview_cache),6)
        self.assertTrue(set(doc._preview_geometry_cache) <= set(doc._preview_cache))
        opaque = doc.render_bytes(core.OutputOptions(), preview=(107,107))
        transparent = doc.render_bytes(core.OutputOptions(background='transparent'), preview=(107,107))
        self.assertNotEqual(opaque,transparent)
        self.assertEqual(doc.render_bytes(core.OutputOptions(), preview=(107,107)),opaque)
        self.assertEqual(doc._preview_cache_bytes,sum(map(len,doc._preview_cache.values())))
        self.assertTrue(set(doc._preview_geometry_cache) <= set(doc._preview_cache))

    def test_cancel_before_direct_cached_render(self):
        doc = core._thread_document(str(self.path))
        doc.render_bytes(preview=(100,100))
        doc._preview_cancelled = lambda: True
        with self.assertRaises(core.RenderCancelled):
            doc.render_bytes(preview=(100,100))


class TileFallbackTests(unittest.TestCase):
    def test_cancel_before_expensive_display_list(self):
        class Page:
            rect = fitz.Rect(0,0,100,100)
            def get_displaylist(self, **kwargs):
                raise AssertionError('Cancelled request parsed page')
        with self.assertRaises(InterruptedError):
            next(tiles.raster_stripes(Page(),100,100,cancelled=lambda:True))

    def test_display_list_runtime_failure_falls_back_once(self):
        with fitz.open() as doc:
            page = doc.new_page(width=120,height=80)
            page.draw_rect(fitz.Rect(10,10,110,70),fill=(1,0,0),fill_opacity=.5)
            class Broken:
                calls = 0
                def get_pixmap(self, **kwargs):
                    self.calls += 1
                    raise RuntimeError('optional display list failed')
            class Page:
                rect = page.rect
                def __init__(self): self.display = Broken()
                def get_displaylist(self, **kwargs): return self.display
                def get_pixmap(self, **kwargs): return page.get_pixmap(**kwargs)
            for alpha in (False,True):
                wrapper=Page()
                actual=b''.join(s for _,_,s in tiles.raster_stripes(wrapper,600,400,edge=80,transparent=alpha))
                native=page.get_pixmap(matrix=fitz.Matrix(5,5),alpha=alpha)
                self.assertEqual(actual,native.samples)
                self.assertEqual(wrapper.display.calls,1)


if __name__ == '__main__': unittest.main()
