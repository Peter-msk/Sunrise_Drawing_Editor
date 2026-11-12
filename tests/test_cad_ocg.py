"""Regression: reuse CAD OCG without changing layer visibility, draw order or geometry."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import patch

import ezdxf
from PIL import Image, ImageChops

from drawing_editor.core import DrawingDocument, OutputOptions


def rgb(blob):
    with Image.open(BytesIO(blob)) as image:
        return image.convert('RGB')


def complex_cad(path: Path):
    d = ezdxf.new('R2013')
    for layer in ('GROUND','ROADS','BLOCKS','LABELS','HIDDEN'):
        d.layers.new(layer)
    d.layers.get('HIDDEN').off()
    m = d.modelspace()
    m.add_lwpolyline([(0,0), (150,0), (150,110), (0,110)], close=True,
                     dxfattribs={'layer':'GROUND','color':3})
    m.add_line((0,55), (150,55), dxfattribs={'layer':'ROADS','color':1})
    m.add_arc((75,55), 18, 30, 240, dxfattribs={'layer':'ROADS','color':5})
    hatch = m.add_hatch(color=5, dxfattribs={'layer':'ROADS'})
    hatch.paths.add_polyline_path([(5,5),(40,5),(40,25),(5,25)],is_closed=True)
    block=d.blocks.new('SIGN')
    block.add_line((0,0),(0,14),dxfattribs={'layer':'0','color':4})
    block.add_circle((0,14),5,dxfattribs={'layer':'0','color':1})
    m.add_blockref('SIGN',(30,70),dxfattribs={'layer':'BLOCKS'})
    m.add_blockref('SIGN',(115,70),dxfattribs={'layer':'BLOCKS'})
    m.add_text('Sunrise',dxfattribs={'layer':'LABELS','height':8,'insert':(46,86)})
    m.add_circle((72,38),12,dxfattribs={'layer':'HIDDEN','color':6})
    d.saveas(path)


class NativeCadLayerPdfTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'drawing.dxf'
        complex_cad(self.path)

    def test_native_ocg_matches_full_legacy_for_multiple_layer_combinations(self):
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with DrawingDocument(self.path) as fast, DrawingDocument(self.path) as original:
            original._cad_recording_attempted = True  # independent full rendering
            fast.render_bytes(preview=(540,420))
            self.assertIsNotNone(fast._cad_layered_pdf)
            for hidden in ((),('ROADS',),('GROUND','LABELS'),('ROADS','BLOCKS','LABELS'),('HIDDEN',)):
                changes={name:(name not in hidden) for name in fast.states()}
                fast.apply_snapshot(changes)
                original.apply_snapshot(changes)
                a=rgb(fast.render_bytes(preview=(540,420)))
                b=rgb(original.render_bytes(preview=(540,420)))
                self.assertEqual(a.size,b.size)
                self.assertIsNone(ImageChops.difference(a,b).getbbox(),hidden)
            # Only the boundary-shrinking combination requires one legacy rebuild;
            # all other layer configurations reuse the original OCG PDF.
            self.assertEqual(fast._cad_render_count,2)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)

    def test_zoom_clip_after_toggle_matches_legacy(self):
        with DrawingDocument(self.path) as fast, DrawingDocument(self.path) as original:
            original._cad_recording_attempted = True
            fast.render_bytes(preview=(540,420))
            w,h=fast.page_size()
            clip=(w*.1,h*.1,w*.8,h*.8)
            fast.set_visibility('BLOCKS',False)
            original.set_visibility('BLOCKS',False)
            a=rgb(fast.render_bytes(preview=(640,450),clip=clip))
            b=rgb(original.render_bytes(preview=(640,450),clip=clip))
            self.assertEqual(a.size,b.size)
            self.assertIsNone(ImageChops.difference(a,b).getbbox())
            fast.set_visibility('BLOCKS',True)
            self.assertEqual(fast._cad_render_count,1)

    def test_empty_state_keeps_previous_preview_size_and_can_restore(self):
        with DrawingDocument(self.path) as d:
            original=d.render_bytes(preview=(600,400))
            d.set_all(False)
            blank=rgb(d.render_bytes(preview=(600,400)))
            self.assertEqual(blank.size,(600,400))
            self.assertEqual(blank.getpixel((200,200)),(255,255,255))
            d.set_all(True)
            self.assertNotEqual(rgb(d.render_bytes(preview=(600,400))).tobytes(),blank.tobytes())
            self.assertEqual(d._cad_render_count,1)

    def test_fallback_kept_when_ocg_budget_zero(self):
        with patch('drawing_editor.core.CAD_OCG_PDF_LIMIT',1):
            with DrawingDocument(self.path) as doc:
                first=doc.render_bytes(preview=(500,350))
                self.assertIsNone(doc._cad_layered_pdf)
                doc.set_visibility('ROADS',False)
                second=doc.render_bytes(preview=(500,350))
                self.assertNotEqual(first,second)
                self.assertIsNone(doc._cad_layered_pdf)

    def test_export_respects_latest_layer_states_without_mutating_cad(self):
        source_hash=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            with DrawingDocument(self.path) as doc:
                base=Path(tmp)/'on.png'; off=Path(tmp)/'off.png'
                doc.export_image(base,OutputOptions('png'))
                doc.set_visibility('ROADS',False)
                doc.export_image(off,OutputOptions('png'))
                a,b=rgb(base.read_bytes()),rgb(off.read_bytes())
                self.assertEqual(a.size,b.size)
                self.assertIsNotNone(ImageChops.difference(a,b).getbbox())
                self.assertEqual(doc._cad_render_count,1)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),source_hash)

if __name__=='__main__': unittest.main()
