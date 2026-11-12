"""Large modelspace viewport pruning: no cropped geometry, no source mutation."""
from __future__ import annotations
import hashlib
import tempfile
import unittest
from pathlib import Path
from io import BytesIO
from unittest.mock import patch

import ezdxf
from PIL import Image, ImageChops
from drawing_editor.core import DrawingDocument, OutputOptions
from drawing_editor.cad_spatial import CADGridIndex, _cheap_box


def big_model(path):
    doc = ezdxf.new('R2013')
    for name in ('GRID', 'FRAMES', 'TEXT', 'OTHER'):
        doc.layers.new(name)
    msp = doc.modelspace()
    for x in range(110):
        for y in range(80):
            xpos = x * 100
            ypos = y * 100
            msp.add_line((xpos, ypos), (xpos+24, ypos+12),
                         dxfattribs={'layer':'GRID', 'color':1})
    msp.add_lwpolyline([(0,0),(10900,0),(10900,7900),(0,7900)],
                       close=True, dxfattribs={'layer':'FRAMES','color':3})
    msp.add_circle((5500,3950),80, dxfattribs={'layer':'OTHER','color':5})
    msp.add_text('STABLE', dxfattribs={'layer':'TEXT','height':140,'insert':(5350,3700)})
    block=doc.blocks.new('B')
    block.add_circle((0,0),40,dxfattribs={'color':2})
    msp.add_blockref('B',(5500,4100),dxfattribs={'layer':'OTHER'})
    doc.saveas(path)


def image_data(data):
    with Image.open(BytesIO(data)) as im:
        return im.convert('RGB')


class CADSpatialTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'big.dxf'
        big_model(self.path)

    def test_unknown_complex_entities_never_pruned(self):
        d=ezdxf.readfile(self.path)
        box=(0.,0.,11000.,8000.)
        index=CADGridIndex(d.modelspace(),box)
        self.assertGreater(index.prunable,8000)
        center=index.visible_handles((5300,3700,5700,4300))
        self.assertLess(len(center),index.prunable // 4)
        complex_entities=[e for e in d.modelspace() if e.dxftype() in ('TEXT','INSERT')]
        self.assertTrue(complex_entities)
        for entity in complex_entities:
            self.assertTrue(index.accept(entity,center))
        self.assertIsNone(_cheap_box(complex_entities[0]))

    def test_viewport_matches_full_renderer_and_preserves_file(self):
        original=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with DrawingDocument(self.path) as fast, DrawingDocument(self.path) as slow:
            # Force large-DXF fallback irrespective of tiny test file size.
            fast._cad_recording_attempted=True
            slow._cad_recording_attempted=True
            overview=fast.render_bytes(preview=(700,510))
            baseline=slow.render_bytes(preview=(700,510))
            self.assertEqual(overview,baseline)
            w,h=fast.page_size()
            clip=(w*.4,h*.35,w*.6,h*.65)
            # Simulate an oversized full PDF which is deliberately not cached.
            fast._cad_pdf_cache.clear(); slow._cad_pdf_cache.clear()
            a=fast.render_bytes(OutputOptions('png'), preview=(800,600),clip=clip)
            self.assertGreater(fast._cad_spatial_runs,0)
            renders=fast._cad_spatial_runs
            self.assertEqual(a,fast.render_bytes(OutputOptions('png'),preview=(800,600),clip=clip))
            self.assertEqual(fast._cad_spatial_runs,renders)
            b=slow.render_bytes(OutputOptions('png'),preview=(800,600),clip=clip)
            self.assertEqual(image_data(a).size,image_data(b).size)
            self.assertIsNone(ImageChops.difference(image_data(a),image_data(b)).getbbox())
            fast.set_visibility('GRID',False)
            slow.set_visibility('GRID',False)
            fast.render_bytes(preview=(700,510))
            slow.render_bytes(preview=(700,510))
            fast._cad_pdf_cache.clear(); slow._cad_pdf_cache.clear()
            a=fast.render_bytes(preview=(800,600),clip=clip)
            b=slow.render_bytes(preview=(800,600),clip=clip)
            self.assertIsNone(ImageChops.difference(image_data(a),image_data(b)).getbbox())
        self.assertEqual(original,hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_no_pruning_if_index_unsupported(self):
        with DrawingDocument(self.path) as doc:
            doc._cad_recording_attempted=True
            doc.render_bytes(preview=(600,450))
            w,h=doc.page_size()
            clip=(w*.3,h*.3,w*.65,h*.65)
            doc._cad_pdf_cache.clear()
            with patch('drawing_editor.core.CADGridIndex',side_effect=ValueError('Budget')):
                result=doc.render_bytes(preview=(640,480),clip=clip)
            self.assertTrue(result.startswith(b'\x89PNG'))
            self.assertEqual(doc._cad_spatial_runs,0)

if __name__=='__main__': unittest.main()
