"""Candidate-only regression tests for bounded CAD DisplayList reuse."""
from __future__ import annotations
from types import SimpleNamespace
import unittest
import fitz
from drawing_editor.core import DrawingDocument


class _BrokenPage:
    def __init__(self, page):
        self._page = page
        self.calls = 0
    def get_displaylist(self, *, annots=True):
        self.calls += 1
        raise RuntimeError("Optional list unavailable")


class CADDisplayListCandidateTests(unittest.TestCase):
    def setUp(self):
        self.pdf = fitz.open()
        self.page = self.pdf.new_page(width=300, height=200)
        shape = self.page.new_shape()
        shape.draw_circle((120, 95), 35)
        shape.finish(color=(0, 0, 0))
        shape.commit()
        self.drawing = object.__new__(DrawingDocument)
        self.drawing._pdf = None
        self.drawing._cad_view_pdf = self.pdf
        self.drawing._cad_layered_pdf = None
        self.drawing._cad_view_pdf_bytes = 128_000
        self.drawing._cad_selective_last_stats = SimpleNamespace(selected_entities=214)
        self.drawing._states = {"arc_layer": True}
        self.drawing._cad_selective_key = tuple(self.drawing._states.items())
        self.drawing.page_index = 0
        self.drawing._preview_display_key = None
        self.drawing._preview_display_list = None
        self.drawing._preview_display_failed_key = None
        self.addCleanup(self.pdf.close)

    def test_small_staged_pdf_is_lazily_reused(self):
        clip = (0, 0, 240, 160)
        self.assertIsNone(self.drawing._get_preview_display_list(self.page, None, clip))
        dl = self.drawing._get_preview_display_list(self.page, None, clip)
        self.assertIsNotNone(dl)
        self.assertIs(self.drawing._get_preview_display_list(self.page, None, clip), dl)
        a = self.page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(*clip), alpha=False)
        b = dl.get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(*clip), alpha=False)
        self.assertEqual(bytes(a.samples), bytes(b.samples))

    def test_large_staged_pdf_or_entity_count_skips_list(self):
        clip = (0, 0, 200, 150)
        self.drawing._cad_view_pdf_bytes = 3 * 1024 * 1024
        self.assertIsNone(self.drawing._get_preview_display_list(self.page, None, clip))
        self.drawing._cad_view_pdf_bytes = 1024
        self.drawing._cad_selective_last_stats = SimpleNamespace(selected_entities=3000)
        self.assertIsNone(self.drawing._get_preview_display_list(self.page, None, clip))

    def test_stale_staging_stats_cannot_enable_the_cache(self):
        clip = (0, 0, 200, 150)
        self.drawing._cad_selective_key = (("other_layer", True),)
        self.assertIsNone(self.drawing._get_preview_display_list(self.page, None, clip))

    def test_failure_does_not_retry_until_new_state(self):
        clip = (0, 0, 200, 150)
        broken = _BrokenPage(self.page)
        self.assertIsNone(self.drawing._get_preview_display_list(broken, None, clip))
        self.assertIsNone(self.drawing._get_preview_display_list(broken, None, clip))
        self.assertIsNone(self.drawing._get_preview_display_list(broken, None, clip))
        self.assertEqual(broken.calls, 1)


if __name__ == "__main__":
    unittest.main()
