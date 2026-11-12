"""Regression guards for immutable per-layer DXF staging and one-pass CAD rendering."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import ezdxf
from PIL import Image

from drawing_editor import cad_selective
from drawing_editor.cad_selective import VisibleDXFSource, SelectiveDXFUnsupported
from drawing_editor.core import DrawingDocument


def _source(path: Path, *, nested: bool = False) -> Path:
    doc = ezdxf.new("R2013", setup=True)
    doc.layers.new("SHOW", dxfattribs={"color": 1})
    doc.layers.new("HIDE", dxfattribs={"color": 5}).off()
    inner = doc.blocks.new("INNER")
    inner.add_line((0, 0), (3, 4))
    outer = doc.blocks.new("OUTER")
    if nested:
        outer.add_blockref("INNER", (0, 0))
    else:
        outer.add_line((0, 0), (3, 4))
    ms = doc.modelspace()
    for i in range(160):
        ms.add_blockref("OUTER", (i % 20 * 8, i // 20 * 8), dxfattribs={"layer": "SHOW"})
        ms.add_line((i, 200), (i + 1, 201), dxfattribs={"layer": "HIDE"})
    doc.saveas(path)
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    return path


class TestCADNextOptimization(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = _source(self.root / "source.dxf")

    def test_insert_reference_cache_reused_without_rescanning(self):
        source = VisibleDXFSource(self.source)
        first = self.root / "first.dxf"
        second = self.root / "second.dxf"
        source.stage(first, ["SHOW"])
        self.assertEqual(source._insert_blocks_by_layer["show"], frozenset({b"outer"}))
        original_pattern = cad_selective._BLOCK_REF

        class CountSearch:
            calls = 0
            def search(self, *args):
                self.calls += 1
                return original_pattern.search(*args)

        counter = CountSearch()
        with patch.object(cad_selective, "_BLOCK_REF", counter):
            source.stage(second, ["SHOW"])
        self.assertEqual(counter.calls, 0)
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_objects_decision_cache_reused_without_rescanning(self):
        source = VisibleDXFSource(self.source)
        first = self.root / "first.dxf"
        second = self.root / "second.dxf"
        stats = source.stage(first, ["HIDE"])
        self.assertTrue(stats.objects_pruned)
        self.assertTrue(source._objects_safe_by_layer["hide"])
        with patch.object(cad_selective, "_needs_objects", side_effect=AssertionError("rescan")):
            next_stats = source.stage(second, ["HIDE"])
        self.assertTrue(next_stats.objects_pruned)
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_group_code_and_handle_value_are_not_confused(self):
        # 102 as a DXF handle VALUE is not group code 102; actual group 102
        # and XDATA 1005 must still retain OBJECTS conservatively.
        from drawing_editor.cad_selective import _needs_objects
        import mmap
        for payload, need_objects in (
            (b'  0\r\nLINE\r\n  5\r\n102\r\n  8\r\nSHOW\r\n', False),
            (b'  0\r\nLINE\r\n102\r\n{APP\r\n  8\r\nSHOW\r\n', True),
            (b'  0\r\nLINE\r\n1001\r\nAPP\r\n1000\r\ntext\r\n', False),
            (b'  0\r\nLINE\r\n1001\r\nAPP\r\n1005\r\nABCD\r\n', True),
        ):
            with self.subTest(payload=payload):
                tmp = self.root / 'codes.dxf'
                tmp.write_bytes(payload)
                with tmp.open('rb') as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as memory:
                    self.assertEqual(_needs_objects(memory, 0, len(payload)), need_objects)

    def test_alternating_layers_and_nested_dependencies_keep_exact_staged_bytes(self):
        self.source = _source(self.source, nested=True)
        cached = VisibleDXFSource(self.source)
        for names in (["SHOW"], ["HIDE"], ["SHOW", "HIDE"], ["SHOW"]):
            expected = self.root / "expected.dxf"
            actual = self.root / "actual.dxf"
            fresh_stats = VisibleDXFSource(self.source).stage(expected, names)
            cached_stats = cached.stage(actual, names)
            self.assertEqual((fresh_stats.blocks_pruned, fresh_stats.objects_pruned),
                             (cached_stats.blocks_pruned, cached_stats.objects_pruned))
            self.assertEqual(expected.read_bytes(), actual.read_bytes())
        result = ezdxf.readfile(self.root / "actual.dxf")
        self.assertIn("OUTER", result.blocks)
        self.assertIn("INNER", result.blocks)

    def test_selective_renderer_skips_redundant_recorder_and_keeps_pixels(self):
        # Force the selective branch for small test input (normally >=64MiB).
        def forced(doc):
            from drawing_editor.cad_catalog import read_ascii_dxf_layers
            doc._cad_selective = VisibleDXFSource(doc.path)
            for layer in read_ascii_dxf_layers(doc.path):
                doc._states[layer.key] = layer.visible
                doc._names[layer.key] = layer.name

        with patch.object(DrawingDocument, "_read_cad", forced):
            with DrawingDocument(self.source) as doc:
                first = doc.render_bytes(preview=(640, 400))
                self.assertTrue(doc._cad_recording_attempted)
                self.assertIsNone(doc._cad_recorder)
                with Image.open(BytesIO(first)) as image:
                    before = image.convert("RGB").tobytes()
                doc.set_visibility("HIDE", True)
                later = doc.render_bytes(preview=(640, 400))
                self.assertNotEqual(first, later)
                doc.set_visibility("HIDE", False)
                self.assertEqual(before, Image.open(BytesIO(doc.render_bytes(preview=(640, 400)))).convert("RGB").tobytes())

    def test_source_changed_after_cache_is_rejected(self):
        source = VisibleDXFSource(self.source)
        source.stage(self.root / "first.dxf", ["SHOW"])
        with self.source.open("ab") as fp:
            fp.write(b"\n")
        with self.assertRaises(SelectiveDXFUnsupported):
            source.stage(self.root / "second.dxf", ["SHOW"])


if __name__ == "__main__":
    unittest.main()
