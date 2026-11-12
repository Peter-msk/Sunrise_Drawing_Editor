"""Byte-exact DXF staging I/O batching and native preview fallback regression."""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import mmap
import tempfile
import unittest
from unittest.mock import patch

from drawing_editor.cad_selective import _write_selected_entities, VisibleDXFSource
from drawing_editor.core import DrawingDocument, OutputOptions


class CADIOBatchTests(unittest.TestCase):
    def test_contiguous_and_noncontiguous_spans_preserve_exact_byte_sequence(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'records.bin'
            payload = b''.join(bytes([i % 251]) * (13 + i % 19) for i in range(150))
            path.write_bytes(payload)
            starts = []
            pos = 0
            for i in range(150):
                length = 13 + i % 19
                if i % 31 not in (1, 2, 3):
                    starts.append((pos, pos + length, b'LINE', 'on'))
                pos += length
            with path.open('rb') as fp, mmap.mmap(fp.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                out = BytesIO()
                _write_selected_entities(out, mm, starts)
                self.assertEqual(out.getvalue(), b''.join(mm[a:b] for a, b, _, _ in starts))

    def test_staged_dxfs_equal_reference_writer_on_bundled_sample(self):
        from drawing_editor import cad_selective
        example = Path(__file__).resolve().parent.parent / 'sample_data' / 'SAMPLE_3_LAYERS.dxf'
        with tempfile.TemporaryDirectory() as directory:
            normalized = Path(directory) / 'source.dxf'
            normalized.write_bytes(example.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
            source = VisibleDXFSource(normalized)
            baseline = Path(directory) / 'baseline.dxf'
            improved = Path(directory) / 'improved.dxf'
            def original_writer(out, contents, selected):
                for start, end, _, _ in selected:
                    out.write(contents[start:end])
            with patch.object(cad_selective, '_write_selected_entities', original_writer):
                old = source.stage(baseline, ['WATER', 'ROAD'])
            new = source.stage(improved, ['WATER', 'ROAD'])
            self.assertEqual(old.selected_entities, new.selected_entities)
            self.assertEqual(baseline.read_bytes(), improved.read_bytes())
            # The downstream PDF/CAD renderer sees the same staged geometry.
            with DrawingDocument(baseline) as d1, DrawingDocument(improved) as d2:
                a = d1.render_bytes(preview=(640, 480))
                b = d2.render_bytes(preview=(640, 480))
                self.assertEqual(a, b)

    def test_empty_selection_and_oversized_record(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'huge.bin'
            p.write_bytes(b'X' * (4 * 1024 * 1024 + 12))
            with p.open('rb') as fp, mmap.mmap(fp.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                out = BytesIO()
                _write_selected_entities(out, mm, [])
                self.assertEqual(out.getvalue(), b'')
                _write_selected_entities(out, mm, [(0, len(mm), b'LINE', 'A')])
                self.assertEqual(out.getvalue(), p.read_bytes())

    def test_native_displaylist_failure_falls_back_once(self):
        """Only acceleration errors are absorbed; page render errors still raise."""
        from drawing_editor import core
        from collections import OrderedDict
        doc = object.__new__(DrawingDocument)
        doc._states = {'a': True}
        doc._preview_cache = OrderedDict()
        doc._preview_cache_bytes = 0
        doc._preview_display_key = ('view',)
        doc._preview_display_failed_key = None
        doc._preview_display_list = object()
        doc._cad = None
        doc._pdf = object()
        doc.page_index = 0
        doc.path = Path('synthetic.dxf')
        def fake_render(page, fmt, preview, clip, display_list=None):
            if display_list is not None:
                raise RuntimeError('cached list invalid')
            return b'fallback PNG'
        with patch.object(doc, '_get_page_context', return_value=(None, object())), \
             patch.object(doc, '_get_preview_display_list', return_value=object()), \
             patch.object(core, '_render_page', side_effect=fake_render) as render:
            first = doc.render_bytes(OutputOptions(), preview=(200, 140), clip=(1, 2, 30, 40))
            self.assertEqual(first, b'fallback PNG')
            self.assertEqual(render.call_count, 2)
            self.assertIsNone(doc._preview_display_list)
            self.assertEqual(doc._preview_display_failed_key, ('view',))


if __name__ == '__main__':
    unittest.main()
