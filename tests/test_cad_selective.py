"""Safe selected-layer DXF staging; synthetic regression cases only."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch

import ezdxf
from PIL import Image

from drawing_editor.cad_selective import VisibleDXFSource, SelectiveDXFUnsupported
from drawing_editor.core import DrawingDocument


def _save_doc(doc, target: Path) -> None:
    doc.saveas(str(target))
    # The selective path targets canonical, AutoCAD-generated CRLF ASCII DXF.
    data = target.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    target.write_bytes(data)


def _pixels(path: Path, *, states=None):
    with DrawingDocument(path) as d:
        if states:
            d.apply_snapshot(states)
        png = d.render_bytes(preview=(710, 480))
        image = Image.open(BytesIO(png)).convert('RGB')
        return image.size, image.tobytes()


class TestSelectedDXF(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _source(self, block=False, polyline=False):
        d = ezdxf.new('R2013', setup=True)
        d.layers.new('VISIBLE', dxfattribs={'color': 1})
        d.layers.new('OFF', dxfattribs={'color': 3}).off()
        ms = d.modelspace()
        ms.add_lwpolyline([(5, 5), (100, 12), (97, 60), (5, 5)],
                          dxfattribs={'layer': 'VISIBLE'})
        ms.add_lwpolyline([(999, 999), (1100, 999)],
                          dxfattribs={'layer': 'OFF'})
        if polyline:
            ms.add_polyline2d([(0, 0), (40, 20), (80, 40)],
                              dxfattribs={'layer': 'VISIBLE'})
        if block:
            b = d.blocks.new(name='VISIBLE_BLOCK')
            b.add_line((0, 0), (45, 55), dxfattribs={'layer': '0'})
            ms.add_blockref('VISIBLE_BLOCK', (20, 15), dxfattribs={'layer': 'VISIBLE'})
        p = self.root / 'source.dxf'
        _save_doc(d, p)
        return p

    def test_primitive_only_prunes_blocks_and_preserves_pixels(self):
        p = self._source()
        origin = p.read_bytes()
        stage = self.root / 'filtered.dxf'
        stats = VisibleDXFSource(p).stage(stage, ['VISIBLE'])
        self.assertTrue(stats.blocks_pruned)
        self.assertTrue(stats.objects_pruned)
        self.assertEqual(stats.selected_entities, 1)
        self.assertLess(stage.stat().st_size, p.stat().st_size)
        self.assertEqual(_pixels(p), _pixels(stage))
        self.assertEqual(p.read_bytes(), origin)

    def test_insert_keeps_blocks_and_original_draw_order(self):
        p = self._source(block=True)
        stage = self.root / 'filtered.dxf'
        stats = VisibleDXFSource(p).stage(stage, ['VISIBLE'])
        self.assertTrue(stats.blocks_pruned)
        self.assertTrue(stats.objects_pruned)  # simple local INSERT -> plain lines
        self.assertEqual(stats.selected_entities, 2)
        self.assertEqual(_pixels(p), _pixels(stage))

    def test_linked_polyline_vertices_are_not_dropped(self):
        p = self._source(polyline=True)
        stage = self.root / 'filtered.dxf'
        stats = VisibleDXFSource(p).stage(stage, ['VISIBLE'])
        self.assertFalse(stats.blocks_pruned)  # POLYLINE + VERTEX dependency
        self.assertFalse(stats.objects_pruned)
        result = ezdxf.readfile(stage)
        self.assertEqual([x.dxftype() for x in result.modelspace()],
                         ['LWPOLYLINE', 'POLYLINE'])
        self.assertEqual(_pixels(p), _pixels(stage))

    def test_layer_switch_loads_new_entities_and_restores_image(self):
        p = self._source()
        original = _pixels(p)
        # Source threshold patched down so the ordinary synthetic DXF uses
        # the same lazy path as a >400MB production document.
        from drawing_editor import core
        def forced(self):
            from drawing_editor.cad_catalog import read_ascii_dxf_layers
            catalog = read_ascii_dxf_layers(self.path)
            self._cad_selective = VisibleDXFSource(self.path)
            for item in catalog:
                self._states[item.key] = item.visible
                self._names[item.key] = item.name
        with patch.object(core.DrawingDocument, '_read_cad', forced):
            with DrawingDocument(p) as d:
                self.assertIsNone(d._cad)
                first = d.render_bytes(preview=(710, 480))
                self.assertEqual(Image.open(BytesIO(first)).convert('RGB').tobytes(), original[1])
                d.set_visibility('OFF', True)
                changed = d.render_bytes(preview=(710, 480))
                self.assertNotEqual(first, changed)
                d.set_visibility('OFF', False)
                restored = d.render_bytes(preview=(710, 480))
                self.assertEqual(first, restored)

    def test_nested_insert_closure_preserves_blocks(self):
        d = ezdxf.new('R2013', setup=True)
        d.layers.new('VISIBLE', dxfattribs={'color': 1})
        d.layers.new('OFF', dxfattribs={'color': 2}).off()
        child = d.blocks.new(name='CHILD')
        child.add_circle((2, 2), 9)
        outer = d.blocks.new(name='OUTER')
        outer.add_blockref('CHILD', (10, 10))
        d.modelspace().add_blockref('OUTER', (100, 100), dxfattribs={'layer': 'VISIBLE'})
        d.modelspace().add_circle((1000, 1000), 200, dxfattribs={'layer': 'OFF'})
        source = self.root / 'source.dxf'
        _save_doc(d, source)
        stage = self.root / 'filtered.dxf'
        stats = VisibleDXFSource(source).stage(stage, ['VISIBLE'])
        self.assertTrue(stats.blocks_pruned)
        reduced = ezdxf.readfile(stage)
        self.assertFalse(stats.objects_pruned)  # nested INSERT: safe fallback
        self.assertIn('OUTER', reduced.blocks)
        self.assertIn('CHILD', reduced.blocks)
        self.assertEqual(_pixels(source), _pixels(stage))

    def test_hatch_falls_back_to_full_blocks(self):
        p = self._source()
        d = ezdxf.readfile(p)
        hatch = d.modelspace().add_hatch(color=4, dxfattribs={'layer': 'VISIBLE'})
        hatch.paths.add_polyline_path([(25, 25), (38, 25), (38, 38), (25, 38)], is_closed=True)
        _save_doc(d, p)
        stage = self.root / 'filtered.dxf'
        stats = VisibleDXFSource(p).stage(stage, ['VISIBLE'])
        self.assertFalse(stats.blocks_pruned)
        self.assertFalse(stats.objects_pruned)
        self.assertEqual(_pixels(p), _pixels(stage))

    def test_primitive_without_indirect_objects_is_identical_to_full_metadata(self):
        p = self._source()
        stage = self.root / 'fast.dxf'
        stats = VisibleDXFSource(p).stage(stage, ['VISIBLE'])
        self.assertTrue(stats.objects_pruned)
        blob = p.read_bytes()
        header = b'  0\r\nSECTION\r\n  2\r\nOBJECTS\r\n'
        self.assertIn(header, blob)
        self.assertNotIn(header, stage.read_bytes())
        self.assertEqual(_pixels(p), _pixels(stage))

    def test_text_requires_original_object_dictionaries(self):
        p = self._source()
        d = ezdxf.readfile(p)
        d.modelspace().add_text('HELLO', dxfattribs={'layer': 'VISIBLE', 'height': 3})
        _save_doc(d, p)
        stage = self.root / 'text.dxf'
        stats = VisibleDXFSource(p).stage(stage, ['VISIBLE'])
        self.assertFalse(stats.objects_pruned)
        self.assertIn(b'  2\r\nOBJECTS\r\n', stage.read_bytes())
        self.assertEqual(_pixels(p), _pixels(stage))

    def test_block_with_text_keeps_object_dictionaries(self):
        p = self._source(block=True)
        d = ezdxf.readfile(p)
        d.blocks.get('VISIBLE_BLOCK').add_text('TEXT', dxfattribs={'height': 2})
        _save_doc(d, p)
        stage = self.root / 'textblock.dxf'
        stats = VisibleDXFSource(p).stage(stage, ['VISIBLE'])
        self.assertFalse(stats.objects_pruned)
        self.assertEqual(_pixels(p), _pixels(stage))

    def test_inline_string_xdata_does_not_require_objects(self):
        p = self._source()
        d = ezdxf.readfile(p)
        d.appids.new('SPECIAL_TAG')
        e = list(d.modelspace())[0]
        e.set_xdata('SPECIAL_TAG', [(1000, 'extra')])
        _save_doc(d, p)
        stage = self.root / 'xdata.dxf'
        stats = VisibleDXFSource(p).stage(stage, ['VISIBLE'])
        self.assertTrue(stats.objects_pruned)
        self.assertEqual(_pixels(p), _pixels(stage))
        rendered = ezdxf.readfile(stage)
        self.assertEqual(rendered.modelspace()[0].get_xdata('SPECIAL_TAG'),
                         d.modelspace()[0].get_xdata('SPECIAL_TAG'))

    def test_xdata_handle_reference_keeps_objects(self):
        p = self._source()
        d = ezdxf.readfile(p)
        d.appids.new('SPECIAL_TAG')
        e = list(d.modelspace())[0]
        e.set_xdata('SPECIAL_TAG', [(1005, 'ABCD')])
        _save_doc(d, p)
        stage = self.root / 'handle.dxf'
        stats = VisibleDXFSource(p).stage(stage, ['VISIBLE'])
        self.assertFalse(stats.objects_pruned)
        self.assertIn(b'  2\r\nOBJECTS\r\n', stage.read_bytes())

    def test_xdata_numeric_reference_uses_conservative_fallback(self):
        p = self._source()
        d = ezdxf.readfile(p)
        d.appids.new('SPECIAL_TAG')
        e = list(d.modelspace())[0]
        e.set_xdata('SPECIAL_TAG', [(1070, 12)])
        _save_doc(d, p)
        stats = VisibleDXFSource(p).stage(self.root / 'numbers.dxf', ['VISIBLE'])
        self.assertFalse(stats.objects_pruned)

    def test_long_layer_name_preserves_exact_identity(self):
        d = ezdxf.new('R2013')
        name = 'LONG_' + 'ABC'*30
        d.layers.new(name)
        d.modelspace().add_line((0, 0), (100, 100), dxfattribs={'layer': name})
        p = self.root / 'long.dxf'
        _save_doc(d, p)
        src = VisibleDXFSource(p)
        stat = src.stage(self.root / 'long_stage.dxf', [name])
        self.assertEqual(stat.selected_entities, 1)
        self.assertEqual(_pixels(p), _pixels(self.root / 'long_stage.dxf'))

    def test_changed_source_cannot_reuse_stale_ranges(self):
        p = self._source()
        source = VisibleDXFSource(p)
        p.write_bytes(p.read_bytes() + b'\n')
        with self.assertRaises(SelectiveDXFUnsupported):
            source.stage(self.root / 'stage.dxf', ['VISIBLE'])

    def test_repeated_stage_reuses_index(self):
        p = self._source()
        source = VisibleDXFSource(p)
        a = source.stage(self.root / 'a.dxf', ['VISIBLE'])
        index_id = id(source._index)
        b = source.stage(self.root / 'b.dxf', ['VISIBLE'])
        self.assertEqual(index_id, id(source._index))
        self.assertEqual(a.selected_entities, b.selected_entities)
        self.assertEqual((self.root / 'a.dxf').read_bytes(),
                         (self.root / 'b.dxf').read_bytes())


if __name__ == '__main__':
    unittest.main()
