"""Focused P0 regression: cancellation must never become an expensive fallback.

Pure engine and AST contracts run without PySide6; Qt GUI itself is NOT RUN.
"""
from __future__ import annotations

import ast
from io import BytesIO
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import fitz
from PIL import Image

from drawing_editor import core
from drawing_editor.cad_selective import VisibleDXFSource, SelectiveDXFCancelled

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'drawing_editor' / 'window.py').read_text('utf-8')
TREE = ast.parse(SOURCE)
MAIN = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'DrawingWindow')


def method(name):
    return next(n for n in MAIN.body if isinstance(n, ast.FunctionDef) and n.name == name)


class RecoveryContracts(unittest.TestCase):
    def test_cancel_before_loading_does_not_open_a_document(self):
        with patch.object(core, '_thread_document', side_effect=AssertionError('opened')):
            with self.assertRaises(core.RenderCancelled):
                core.preview_snapshot('missing.pdf', {}, 0, (640, 480), cancelled=lambda: True)
            with self.assertRaises(core.RenderCancelled):
                core.render_snapshot('missing.pdf', {}, 0, (640, 480), cancelled=lambda: True)

    def test_cancel_after_native_pixmap_discards_stale_result(self):
        source = ROOT / 'sample_data' / 'SAMPLE_3_LAYERS.pdf'
        flag = threading.Event()
        real_render = core._render_page

        def finish_render(*args, **kwargs):
            result = real_render(*args, **kwargs)
            flag.set()
            return result

        with patch.object(core, '_render_page', side_effect=finish_render):
            with self.assertRaises(core.RenderCancelled):
                core.preview_snapshot(str(source), {}, 0, (400, 300), cancelled=flag.is_set)
        flag.clear()
        data, bounds = core.preview_snapshot(str(source), {}, 0, (400, 300), cancelled=flag.is_set)
        self.assertGreater(len(data), 100)
        self.assertGreater(bounds[0], 0)

    def test_dxf_staging_cancel_raises_distinct_error(self):
        source = ROOT / 'sample_data' / 'SAMPLE_3_LAYERS.dxf'
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'scratch.dxf'
            reader = VisibleDXFSource(source)
            with self.assertRaises(SelectiveDXFCancelled):
                reader.stage(output, {'A'}, cancelled=lambda: True)
            self.assertFalse(output.exists())

    def test_cancel_is_never_swallowed_into_expensive_full_dxf_fallback(self):
        source = ROOT / 'sample_data' / 'SAMPLE_3_LAYERS.dxf'
        doc = object.__new__(core.DrawingDocument)
        doc._cad_selective = object()
        doc._cad_selective_key = None
        doc._cad = None
        doc._states = {'A': True}
        doc._preview_cancelled = lambda: True
        with patch.object(core.ezdxf, 'readfile', side_effect=AssertionError('full parse')):
            with self.assertRaises(core.RenderCancelled):
                doc._ensure_selective_cad()

    def test_many_pdf_ocgs_have_unique_fast_ui_mapping_and_reversible_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            filename = Path(tmp) / 'many_layers.pdf'
            with fitz.open() as created:
                page = created.new_page(width=400, height=300)
                for idx in range(75):
                    xref = created.add_ocg(f'layer_{idx}', on=True)
                    page.draw_rect(fitz.Rect(idx*2, idx*2, idx*2+7,idx*2+7),
                                   color=(0, 0, 0), oc=xref)
                created.save(str(filename))
            before = filename.read_bytes()
            with core.DrawingDocument(filename) as doc:
                self.assertEqual(len(doc._pdf_ui_map), 75)
                first = doc.render_bytes(preview=(500, 400))
                first_layer = next(iter(doc.states()))
                doc.set_visibility(first_layer, False)
                other = doc.render_bytes(preview=(500, 400))
                self.assertNotEqual(Image.open(BytesIO(first)).convert('RGB').tobytes(),
                                    Image.open(BytesIO(other)).convert('RGB').tobytes())
                doc.set_visibility(first_layer, True)
                self.assertEqual(first, doc.render_bytes(preview=(500,400)))
            self.assertEqual(before, filename.read_bytes())

    def test_close_cannot_be_permanently_blocked_by_nonresponsive_worker(self):
        close_src = ast.get_source_segment(SOURCE, method('closeEvent'))
        prompt_src = ast.get_source_segment(SOURCE, method('_offer_force_exit'))
        self.assertIn('self._offer_force_exit()', close_src)
        self.assertIn('self._export_cancel.set()', close_src)
        self.assertIn('self.pool.clear()', close_src)
        self.assertIn('os._exit(0)', prompt_src)
        self.assertIn('QMessageBox.StandardButton.Yes', prompt_src)
        self.assertNotIn('os._exit(0)', close_src)

    def test_latest_preview_cancels_previous_and_drop_is_available_everywhere(self):
        prev_src = ast.get_source_segment(SOURCE, method('request_preview'))
        add_src = ast.get_source_segment(SOURCE, method('add_files'))
        self.assertIn('self._preview_cancel.set()', prev_src)
        self.assertIn('self._preview_seq+=1', prev_src)
        self.assertIn('setUpdatesEnabled(False)', add_src)
        self.assertIn('self.centralWidget().installEventFilter(self)', SOURCE)
        self.assertIn('self.canvas.viewport().installEventFilter(self)', SOURCE)
        self.assertIn('FileDropList._paths(event.mimeData())', SOURCE)
        self.assertIn('doc._preview_cancelled = cancelled',
                      (ROOT / 'drawing_editor' / 'core.py').read_text('utf-8'))

    def test_duplicate_pdf_ocg_state_uses_bounded_single_serialized_view(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'duplicate_ocg.pdf'
            with fitz.open() as created:
                page = created.new_page(width=240, height=180)
                first = created.add_ocg('중복', on=True)
                second = created.add_ocg('중복', on=True)
                page.draw_rect(fitz.Rect(20,20,90,90),fill=(1,0,0),oc=first)
                page.draw_rect(fitz.Rect(110,20,200,90),fill=(0,0,1),oc=second)
                created.save(str(source))
            before = source.read_bytes()
            with core.DrawingDocument(source) as doc:
                self.assertTrue(doc._serialize_fallback)
                original = doc.render_bytes(preview=(420,300))
                self.assertIsNone(doc._pdf_fallback_view)
                doc.set_visibility(first, False)
                changed = doc.render_bytes(preview=(420,300))
                self.assertNotEqual(original,changed)
                cached = doc._pdf_fallback_view
                self.assertIsNotNone(cached)
                doc.render_bytes(preview=(680,400))
                self.assertIs(cached,doc._pdf_fallback_view)
                doc.set_visibility(first,True)
                self.assertIsNone(doc._pdf_fallback_view)
                self.assertEqual(original,doc.render_bytes(preview=(420,300)))
            self.assertEqual(before,source.read_bytes())

    def test_mupdf_tasks_are_serialized_across_worker_pools(self):
        self.assertIn('with _MUPDF_GATE:',SOURCE)
        self.assertIn('_MUPDF_GATE.acquire(timeout=0.15)',SOURCE)
        self.assertIn('_MUPDF_GATE.release()',SOURCE)
        self.assertIn("if kind == '.pdf':", SOURCE)

if __name__ == '__main__':
    unittest.main()
