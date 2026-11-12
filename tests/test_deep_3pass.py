"""Three-pass optimizations: bounded index, exact geometry, reusable PDF/view."""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ezdxf
from PIL import Image

from drawing_editor import cad_selective, core
from drawing_editor.cad_selective import VisibleDXFSource, SelectiveDXFUnsupported
from drawing_editor.core import DrawingDocument, OutputOptions


def sample(root: Path, *, oversize=False):
    d = ezdxf.new('R2013', setup=True)
    d.layers.new('A', dxfattribs={'color': 1})
    d.layers.new('B', dxfattribs={'color': 3})
    d.layers.new('C', dxfattribs={'color': 5}).off()
    model = d.modelspace()
    if oversize:
        model.add_lwpolyline([(float(i), float(i%41)) for i in range(300)], dxfattribs={'layer': 'A'})
    else:
        for i in range(360):
            model.add_line((i*.3, i*.2),(i*.3+3, i*.2+2),dxfattribs={'layer':'A' if i%3 else 'B'})
    b = d.blocks.new('MARK')
    b.add_line((0,0),(1,2))
    model.add_blockref('MARK',(7,8),dxfattribs={'layer':'C','rotation':30})
    p=root/'case.dxf'
    d.saveas(p)
    content=p.read_bytes().replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
    p.write_bytes(content)
    return p


def rgb(png):
    with Image.open(BytesIO(png)) as i:
        return i.convert('RGB').size,i.convert('RGB').tobytes()


class ThreePassTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_layer_index_preserves_exact_records(self):
        p=sample(self.root)
        src=VisibleDXFSource(p)
        a=src.stage(self.root/'a.dxf',['A','B'])
        self.assertGreater(a.selected_entities,350)
        self.assertEqual(a.selected_entities,360)
        ordered=[x[0] for x in src._index if x[3] in {'a','b'}]
        self.assertEqual(ordered,[x[0] for x in sorted(
            [rec for v in ('a','b') for rec in src._by_layer[v]],key=lambda r:r[0])])
        with DrawingDocument(p) as full, DrawingDocument(self.root/'a.dxf') as staged:
            full.set_visibility('C',False)
            self.assertEqual(rgb(full.render_bytes(preview=(640,480))),
                             rgb(staged.render_bytes(preview=(640,480))))

    def test_large_entity_not_cut_by_indexer(self):
        p=sample(self.root,oversize=True)
        src=VisibleDXFSource(p)
        stats=src.stage(self.root/'large.dxf',['A'])
        self.assertEqual(stats.selected_entities,1)
        with DrawingDocument(p) as original, DrawingDocument(self.root/'large.dxf') as staged:
            self.assertEqual(rgb(original.render_bytes(preview=(320,240))),
                             rgb(staged.render_bytes(preview=(320,240))))

    def test_batch_layer_filter_preserves_interleaved_draw_order(self):
        p=sample(self.root)
        source=VisibleDXFSource(p)
        first=source.stage(self.root/'a.dxf',['A','B'])
        second=source.stage(self.root/'b.dxf',['B','A'])
        self.assertEqual(first.selected_entities,second.selected_entities)
        self.assertEqual((self.root/'a.dxf').read_bytes(),(self.root/'b.dxf').read_bytes())

    def test_live_pdf_reused_then_invalidated_after_layer_switch(self):
        p=sample(self.root)
        def forced(d):
            from drawing_editor.cad_catalog import read_ascii_dxf_layers
            d._cad_selective=VisibleDXFSource(d.path)
            for lay in read_ascii_dxf_layers(d.path):
                d._states[lay.key]=lay.visible;d._names[lay.key]=lay.name
        with patch.object(DrawingDocument,'_read_cad',forced), \
                patch.object(DrawingDocument,'_build_cad_recording',return_value=None):
            with DrawingDocument(p) as doc:
                a=doc.render_bytes(preview=(620,450))
                owner=doc._cad_view_pdf
                self.assertIsNotNone(owner)
                self.assertEqual(rgb(a),rgb(doc.render_bytes(preview=(620,450))))
                _=doc.render_bytes(preview=(200,200),clip=(1.,1.,15.,15.))
                self.assertIs(owner,doc._cad_view_pdf)
                doc.set_visibility('C',True)
                self.assertIsNone(doc._cad_view_pdf)
                b=doc.render_bytes(preview=(620,450))
                self.assertNotEqual(rgb(a),rgb(b))
                doc.set_visibility('C',False)
                self.assertEqual(rgb(a),rgb(doc.render_bytes(preview=(620,450))))

    def test_preview_cache_replacement_does_not_overcount(self):
        p=sample(self.root)
        with DrawingDocument(p) as d:
            d._remember_preview(('one',),b'abc')
            d._remember_preview(('one',),b'xyz789')
            self.assertEqual(d._preview_cache_bytes,6)
            self.assertEqual(len(d._preview_cache),1)

    def test_png_jpg_custom_dpi_dimensions_preserved(self):
        p=sample(self.root)
        with DrawingDocument(p) as d:
            for fmt in ('png','jpg'):
                target=self.root/('img.'+fmt)
                d.export_image(target,OutputOptions(fmt=fmt,resolution='fhd'))
                self.assertTrue(target.exists())
                with Image.open(target) as im:
                    self.assertGreater(im.width,0)
                    self.assertGreater(im.height,0)

if __name__=='__main__':
    unittest.main()
