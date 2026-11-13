"""Candidate must remain opt-in for large DXF and byte/pixel safe.

No real 402MiB fixture is claimed by these isolated tests.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import fitz

from drawing_editor.core import DrawingDocument
from quality.audit_displaylist_fourth_pass import compare, _view_clips


class FourthPassDisplayListGates(unittest.TestCase):
    def setUp(self):
        pdf = fitz.open()
        self.addCleanup(pdf.close)
        page = pdf.new_page(width=300, height=200)
        shape = page.new_shape()
        shape.draw_line((10, 20), (240, 150))
        shape.draw_circle((80, 100), 28)
        shape.finish(color=(1, 0, 0), width=1)
        shape.commit()
        self.page = page
        self.drawing = object.__new__(DrawingDocument)
        obj = self.drawing
        obj.path = Path(__file__)
        obj._pdf = None
        obj._cad_view_pdf = pdf
        obj._cad_layered_pdf = None
        obj._cad_view_pdf_bytes = 128_000
        obj._cad_selective_last_stats = SimpleNamespace(selected_entities=214)
        obj._states = {'ARCS': True}
        obj._cad_selective_key = tuple(obj._states.items())
        obj.page_index = 0
        obj._preview_display_key = None
        obj._preview_display_list = None
        obj._preview_display_failed_key = None
        obj._experimental_large_cad_displaylist = False

    def _request(self, rectangle=(0, 0, 200, 160)):
        return self.drawing._get_preview_display_list(self.page, None, rectangle)

    def test_large_source_is_disabled_by_default_even_on_second_clip(self):
        with patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=421_316_933)):
            self.assertIsNone(self._request())
            self.assertIsNone(self._request((4, 4, 205, 161)))
        self.assertIsNone(self.drawing._preview_display_list)

    def test_explicit_audit_optin_is_lazy_and_exact(self):
        self.drawing._experimental_large_cad_displaylist = True
        with patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=421_316_933)):
            self.assertIsNone(self._request())
            dl = self._request((4, 4, 205, 161))
            self.assertIsNotNone(dl)
            self.assertIs(self._request((8, 8, 210, 163)), dl)
        for alpha in (False, True):
            clip = fitz.Rect(0, 0, 200, 160)
            matrix = fitz.Matrix(2, 2)
            old = self.page.get_pixmap(matrix=matrix, clip=clip, alpha=alpha,
                                       colorspace=fitz.csRGB, annots=True)
            new = dl.get_pixmap(matrix=matrix, clip=clip, alpha=alpha,
                                 colorspace=fitz.csRGB)
            self.assertEqual(bytes(old.samples), bytes(new.samples))

    def test_audit_optin_still_rejects_large_pdf_or_expanded_layer_count(self):
        self.drawing._experimental_large_cad_displaylist = True
        with patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=421_316_933)):
            self.drawing._cad_view_pdf_bytes = 2 * 1024 * 1024 + 1
            self.assertIsNone(self._request())
            self.drawing._cad_view_pdf_bytes = 512_000
            self.drawing._cad_selective_last_stats = SimpleNamespace(selected_entities=9533)
            self.assertIsNone(self._request())
            self.drawing._cad_selective_last_stats = SimpleNamespace(selected_entities=0)
            self.assertIsNone(self._request())

    def test_outdated_layer_state_never_enables_large_audit(self):
        self.drawing._experimental_large_cad_displaylist = True
        self.drawing._cad_selective_key = (('ARCS', False),)
        with patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=421_316_933)):
            self.assertIsNone(self._request())

    def test_explicit_reset_releases_cached_native_list(self):
        self.drawing._experimental_large_cad_displaylist = True
        with patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=421_316_933)):
            self._request()
            self.assertIsNotNone(self._request((4, 4, 205, 161)))
        # The real layer-transition code explicitly calls the same reset.
        self.drawing._preview_display_list = None
        self.drawing._preview_display_key = None
        self.drawing._preview_display_failed_key = None
        self.assertIsNone(self.drawing._preview_display_list)
        self.assertIsNone(self._request())

    def test_small_benchmark_compares_both_background_modes(self):
        result = compare(self.page, self.page.get_displaylist(annots=True),
                         trials=3, views=5)
        self.assertTrue(result['all_pixel_hashes_equal'])
        self.assertTrue(result['all_pixel_sizes_equal'])
        self.assertEqual(len(result['trials']), 3)
        self.assertEqual(len(_view_clips(self.page, 5)), 5)


if __name__ == '__main__':
    unittest.main()
