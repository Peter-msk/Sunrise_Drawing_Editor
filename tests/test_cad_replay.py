"""Focused regression for memory-bounded CAD draw-record reuse."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import patch

import ezdxf
from PIL import Image, ImageChops

from drawing_editor.core import DrawingDocument


def pixels(blob: bytes):
    image = Image.open(BytesIO(blob)).convert('RGB')
    image.load()
    return image


def make_cad(path: Path):
    cad = ezdxf.new('R2013')
    cad.layers.new('LAND')
    cad.layers.new('ROAD')
    cad.layers.new('HIDDEN')
    cad.layers.get('HIDDEN').off()
    m = cad.modelspace()
    m.add_lwpolyline([(0, 0), (100, 0), (100, 80), (0, 80)],
                     close=True, dxfattribs={'layer': 'LAND', 'color': 1})
    m.add_line((5, 40), (95, 40), dxfattribs={'layer': 'ROAD', 'color': 5})
    block = cad.blocks.new('SYMBOL')
    block.add_circle((0, 0), 7, dxfattribs={'layer': '0', 'color': 3})
    m.add_blockref('SYMBOL', (25, 25), dxfattribs={'layer': 'ROAD'})
    m.add_circle((85, 60), 15, dxfattribs={'layer': 'HIDDEN', 'color': 2})
    cad.saveas(path)


class CadReplayTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'cad.dxf'
        make_cad(self.path)

    def test_all_visible_matches_legacy_and_source_unchanged(self):
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with DrawingDocument(self.path) as fast, DrawingDocument(self.path) as legacy:
            # The direct pipeline is an independent fallback baseline.
            legacy._cad_recording_attempted = True
            fast.set_visibility('HIDDEN', True)
            legacy.set_visibility('HIDDEN', True)
            a = pixels(fast.render_bytes(preview=(560, 420)))
            b = pixels(legacy.render_bytes(preview=(560, 420)))
            self.assertIsNotNone(fast._cad_recorder)
            self.assertEqual(a.size, b.size)
            self.assertIsNone(ImageChops.difference(a,b).getbbox())
            self.assertEqual(fast._cad_render_count, 1)
            fast.set_visibility('ROAD', False)
            hidden = pixels(fast.render_bytes(preview=(560, 420)))
            self.assertIsNotNone(ImageChops.difference(a, hidden).getbbox())
            fast.set_visibility('ROAD', True)
            self.assertIsNone(ImageChops.difference(
                a, pixels(fast.render_bytes(preview=(560, 420)))).getbbox())
            self.assertEqual(fast._cad_render_count, 1)  # OCG: no CAD-to-PDF regeneration on toggle
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), digest)

    def test_initially_hidden_layer_can_be_enabled(self):
        with DrawingDocument(self.path) as fast:
            first = pixels(fast.render_bytes(preview=(640, 500)))
            self.assertFalse(fast.states()['HIDDEN'])
            self.assertIsNotNone(fast._cad_recorder)
            color = fast._cad.layers.get('HIDDEN').dxf.color
            fast.set_visibility('HIDDEN', True)
            later = pixels(fast.render_bytes(preview=(640, 500)))
            self.assertIsNotNone(ImageChops.difference(first, later).getbbox())
            self.assertNotEqual(color, fast._cad.layers.get('HIDDEN').dxf.color)
            self.assertEqual(first.size,later.size)

    def test_records_budget_fallback_and_visibility_restored(self):
        with patch('drawing_editor.core.CAD_REPLAY_RECORD_LIMIT', 1):
            with DrawingDocument(self.path) as drawing:
                old = drawing.states()
                initial = drawing.render_bytes(preview=(640, 480))
                self.assertIsNone(drawing._cad_recorder)
                self.assertTrue(drawing._cad.layers.get('HIDDEN').is_off())
                drawing.set_visibility('ROAD', False)
                changed = drawing.render_bytes(preview=(640, 480))
                self.assertNotEqual(initial, changed)
                self.assertEqual(drawing.states()['HIDDEN'], old['HIDDEN'])

    def test_large_model_guard_falls_back_without_refusal(self):
        with patch('drawing_editor.core.CAD_REPLAY_SOURCE_LIMIT', 1):
            with DrawingDocument(self.path) as drawing:
                drawing.render_bytes(preview=(480, 360))
                self.assertIsNone(drawing._cad_recorder)
                drawing.set_visibility('LAND', False)
                self.assertTrue(drawing.render_bytes(preview=(480, 360)))

    def test_viewport_clip_works_with_replay_and_changed_layer(self):
        with DrawingDocument(self.path) as doc:
            doc.render_bytes(preview=(600, 400))
            rect = doc.page_size()
            clip = (rect[0] * 0.25, rect[1] * 0.25, rect[0] * 0.75, rect[1] * 0.75)
            image = pixels(doc.render_bytes(preview=(600, 400), clip=clip))
            doc.set_visibility('ROAD', False)
            modified = pixels(doc.render_bytes(preview=(600, 400), clip=clip))
            self.assertEqual(image.size, modified.size)
            self.assertIsNotNone(ImageChops.difference(image, modified).getbbox())


if __name__=='__main__':
    unittest.main()
