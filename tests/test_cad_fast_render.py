"""Fast PDF LINE emission must retain the exact original PDF paint program."""
from __future__ import annotations
import hashlib
import unittest
from unittest.mock import patch
from io import BytesIO

import ezdxf
import fitz
from ezdxf.addons.drawing import Frontend, RenderContext, layout, pymupdf
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
from drawing_editor.cad_render_fast import FastPyMuPdfBackend, _ExactLineBackend


class FastLineBackendTests(unittest.TestCase):
    def _pdf(self, d, cls):
        backend = cls()
        Frontend(RenderContext(d), backend, config=Configuration(
            background_policy=BackgroundPolicy.OFF,
            color_policy=ColorPolicy.COLOR)).draw_layout(d.modelspace())
        pdf = backend.get_pdf_bytes(layout.Page(0, 0),
                                    render_box=backend.player().bbox())
        with fitz.open(stream=pdf, filetype='pdf') as output:
            content = b''.join(output.xref_stream(x) for x in output[0].get_contents())
            pixels = output[0].get_pixmap(matrix=fitz.Matrix(.8, .8), alpha=False).samples
            layer_names = [v['name'] for v in output.get_ocgs().values()]
            return content, bytes(pixels), layer_names

    def _drawing(self):
        d = ezdxf.new('R2013')
        d.layers.new('BLUE', dxfattribs={'color': 5})
        d.layers.new('RED', dxfattribs={'color': 1})
        block = d.blocks.new('POLE')
        block.add_line((0, -10), (0, 10))
        block.add_line((-10, 0), (10, 0))
        ms = d.modelspace()
        for x in range(30):
            ms.add_blockref('POLE', (x * 42, x * 11), dxfattribs={
                'layer': 'BLUE' if x % 2 else 'RED',
                'rotation': float(x % 5) * 7.5,
                'xscale': .1 + x * .002,
                'yscale': .1 + x * .002,
            })
        ms.add_lwpolyline([(0, 200), (800, 240), (300, 210)],
                          dxfattribs={'layer': 'BLUE', 'color': 2})
        return d

    def test_multi_insert_styles_rotation_scale_and_ocg_are_byte_exact(self):
        d = self._drawing()
        old = self._pdf(d, pymupdf.PyMuPdfBackend)
        new = self._pdf(d, FastPyMuPdfBackend)
        self.assertEqual(new, old)
        self.assertTrue(old[2])

    def test_repeated_inserts_use_validated_fast_line_path(self):
        d = self._drawing()
        backend = FastPyMuPdfBackend()
        Frontend(RenderContext(d), backend, config=Configuration(
            background_policy=BackgroundPolicy.OFF,
            color_policy=ColorPolicy.COLOR)).draw_layout(d.modelspace())
        render = backend.get_replay(layout.Page(0, 0),
                                   render_box=backend.player().bbox())
        self.assertIsInstance(render, _ExactLineBackend)
        self.assertGreater(render.fast_line_count, 20)
        self.assertTrue(render.get_pdf_bytes().startswith(b'%PDF'))

    def test_repeated_circle_block_paths_have_identical_pdf_stream_and_pixels(self):
        drawing = ezdxf.new('R2013')
        drawing.layers.new('CIRCLES', dxfattribs={'color': 5})
        block = drawing.blocks.new('CIRCLE_ARRAY')
        for i in range(78):
            block.add_circle((i % 13 * 5, i // 13 * 5), 1.4)
        for i in range(10):
            drawing.modelspace().add_blockref(
                'CIRCLE_ARRAY', (i * 70, (i % 3) * 20),
                dxfattribs={'layer':'CIRCLES','rotation':float(i)*3.0})
        expected = self._pdf(drawing, pymupdf.PyMuPdfBackend)
        actual = self._pdf(drawing, FastPyMuPdfBackend)
        self.assertEqual(actual, expected)

    def test_transparent_strokes_fall_back_with_identical_pdf(self):
        d = self._drawing()
        # Transparency means separate paint passes cannot be approximated.
        for entity in d.modelspace().query('INSERT'):
            entity.dxf.transparency = 0x02000080
        self.assertEqual(self._pdf(d, pymupdf.PyMuPdfBackend),
                         self._pdf(d, FastPyMuPdfBackend))

    def test_fast_style_validation_failure_falls_back_exactly(self):
        d = self._drawing()
        with patch.object(_ExactLineBackend, '_exact_style', return_value=None):
            self.assertEqual(self._pdf(d, pymupdf.PyMuPdfBackend),
                             self._pdf(d, FastPyMuPdfBackend))

    def test_mixed_hatch_paths_and_blocks_are_identical(self):
        d = self._drawing()
        ms = d.modelspace()
        ms.add_circle((300, 180), 15)
        h = ms.add_hatch(color=4)
        h.paths.add_polyline_path([(0, 70), (100, 70), (100, 90), (0, 90)], is_closed=True)
        self.assertEqual(self._pdf(d, pymupdf.PyMuPdfBackend),
                         self._pdf(d, FastPyMuPdfBackend))


if __name__ == '__main__':
    unittest.main()
