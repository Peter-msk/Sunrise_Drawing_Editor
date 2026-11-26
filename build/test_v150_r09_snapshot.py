"""R09 full snapshot boundary: reject ambiguous requests and stale sources."""
import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz
from PIL import Image
from drawing_editor import core


class SnapshotBoundaryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(core.close_thread_document)
        self.path = Path(tmp.name) / 'source.pdf'
        with fitz.open() as pdf:
            self.a = pdf.add_ocg('ROAD', on=True)
            self.b = pdf.add_ocg('WATER', on=True)
            pdf.set_layer(-1, locked=[self.a])
            page = pdf.new_page(width=100, height=100)
            page.draw_rect(fitz.Rect(10, 10, 40, 40), color=None, fill=(1, 0, 0), oc=self.a)
            page.draw_rect(fitz.Rect(60, 60, 90, 90), color=None, fill=(0, 0, 1), oc=self.b)
            pdf.save(self.path)
        self.states = {self.a: True, self.b: False}
        self.before = hashlib.sha256(self.path.read_bytes()).digest()

    def preview(self, states, **kwargs):
        return core.preview_snapshot(str(self.path), states, 0, (100, 100), **kwargs)[0]

    def export(self, states, name='out.png', **kwargs):
        return core.export_snapshot(str(self.path), states, 0, str(self.path.parent / name),
                                    core.OutputOptions(resolution='custom', width=100, height=100), **kwargs)

    def test_unstamped_partial_snapshot_rejected_then_recovers(self):
        self.preview(self.states)
        for states in ({self.a: True}, {**self.states, 9999: True}, {**self.states, self.a: False}):
            for name, operation in (('preview', self.preview), ('export', self.export)):
                with self.subTest(states=states, operation=name):
                    with self.assertRaises(core.DrawingError):
                        operation(states)
            self.assertFalse((self.path.parent / 'out.png').exists())
        with Image.open(BytesIO(self.preview({self.a: True, self.b: True}))) as image:
            self.assertEqual(image.getpixel((70, 70)), (0, 0, 255))
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(), self.before)

    def test_detail_rejects_partial_without_stamp(self):
        with self.assertRaises(core.DrawingError):
            core.render_snapshot(str(self.path), {}, 0, (100, 100))

    def test_unstamped_preview_detects_source_change_during_render(self):
        original = core._render_page
        def mutate(*args, **kwargs):
            result = original(*args, **kwargs)
            with self.path.open('ab') as stream:
                stream.write(b'\n% changed')
            return result
        with patch.object(core, '_render_page', side_effect=mutate):
            with self.assertRaisesRegex(core.DrawingError, '원본 도면이 변경'):
                self.preview(self.states)
        self.assertIsNone(getattr(core._cache, 'document', None))

    def test_float_pdf_layer_key_rejected(self):
        # Python floats can compare equal to integer xrefs.
        doc = core._thread_document(str(self.path))
        with self.assertRaises(core.DrawingError):
            core._validate_snapshot(doc, {float(self.a): True, self.b: False}, 0, doc.source_signature)

    def test_cached_parser_revision_must_match_guard(self):
        doc = core._thread_document(str(self.path))
        with self.path.open('ab') as stream:
            stream.write(b'\n% changed')
        new_stamp = core.source_signature(self.path)
        with self.assertRaisesRegex(core.DrawingError, '원본 도면이 변경'):
            core._validate_snapshot(doc, self.states, 0, new_stamp)


if __name__ == '__main__':
    unittest.main()
