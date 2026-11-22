"""R03 source-level preview, metadata and state regression; no Qt claim."""
import hashlib
import io
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ezdxf
import fitz
from PIL import Image
from drawing_editor.core import (DrawingDocument, DrawingError, LayerInfo, RenderCancelled,
    preview_snapshot, render_snapshot, source_signature, close_thread_document)
from drawing_editor.cad_catalog import read_ascii_dxf_layers
from drawing_editor import cad_catalog, cad_worker, core
from drawing_editor.state import DrawingState
from drawing_editor.ui_interaction import matching_editable_layers

class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(close_thread_document)
        self.addCleanup(cad_worker.shutdown_all_workers)
        self.root = Path(self.temp.name)
        self.path = self.root/'source.pdf'
        with fitz.open() as pdf:
            self.red = pdf.add_ocg('ROAD', on=True)
            self.blue = pdf.add_ocg('WATER', on=True)
            for i in range(2):
                p=pdf.new_page(width=100,height=100)
                p.draw_rect(fitz.Rect(10,10,40,40),color=None,fill=(1,0,0),oc=self.red)
                p.draw_rect(fitz.Rect(60,60,90,90),color=None,fill=(0,0,1),oc=self.blue)
            pdf.save(self.path)
        self.sig = source_signature(self.path)
        self.states = {self.red: True, self.blue: False}
    def pixel(self, data, where):
        with Image.open(io.BytesIO(data)) as im:return im.convert('RGB').getpixel(where)
    def mutate(self):
        with self.path.open('ab') as f:f.write(b'\n% changed')
    def test_local_preview_and_detail(self):
        before=hashlib.sha256(self.path.read_bytes()).digest()
        data, geometry = preview_snapshot(str(self.path),self.states,0,(100,100),expected_source=self.sig)
        self.assertEqual(geometry,(100,100));self.assertEqual(self.pixel(data,(20,20)),(255,0,0));self.assertEqual(self.pixel(data,(70,70)),(255,255,255))
        result=render_snapshot(str(self.path),self.states,1,(100,100),clip=(0.,0.,50.,50.),expected_source=self.sig)
        self.assertEqual(self.pixel(result,(40,40)),(255,0,0))
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(),before)
    def test_isolated_worker_toggle_and_detail(self):
        before=hashlib.sha256(self.path.read_bytes()).digest()
        data,_=cad_worker.render_isolated('preview',str(self.path),self.states,0,(100,100),expected_source=self.sig)
        self.assertEqual(self.pixel(data,(20,20)),(255,0,0));self.assertEqual(self.pixel(data,(70,70)),(255,255,255))
        session=cad_worker._THREAD.session
        off={self.red:False,self.blue:True}
        data,_=cad_worker.render_isolated('preview',str(self.path),off,1,(100,100),expected_source=self.sig)
        self.assertIs(cad_worker._THREAD.session,session)
        self.assertEqual(self.pixel(data,(20,20)),(255,255,255));self.assertEqual(self.pixel(data,(70,70)),(0,0,255))
        data=cad_worker.render_isolated('detail',str(self.path),off,1,(100,100),clip=(50.,50.,100.,100.),expected_source=self.sig)
        self.assertEqual(self.pixel(data,(40,40)),(0,0,255))
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(),before)
    def test_stale_before_preview_both_paths(self):
        self.mutate()
        for fn in (lambda:preview_snapshot(str(self.path),self.states,0,(100,100),expected_source=self.sig),lambda:cad_worker.render_isolated('preview',str(self.path),self.states,0,(100,100),expected_source=self.sig)):
            with self.assertRaisesRegex(DrawingError,'원본 도면이 변경'):fn()
    def test_stale_during_render(self):
        original=core._render_page
        def render(*args,**kwargs):
            result=original(*args,**kwargs);self.mutate();return result
        with patch.object(core,'_render_page',side_effect=render):
            with self.assertRaisesRegex(DrawingError,'원본 도면이 변경'):
                preview_snapshot(str(self.path),self.states,0,(100,100),expected_source=self.sig)
        self.assertIsNone(getattr(core._cache,'document',None))
    def test_bad_snapshots(self):
        for states,page in (({},0),(self.states,2)):
            with self.assertRaises(DrawingError):preview_snapshot(str(self.path),states,page,(100,100),expected_source=self.sig)
            with self.assertRaises(DrawingError):render_snapshot(str(self.path),states,page,(100,100),expected_source=self.sig)
    def test_isolated_invalid_snapshot_recovery(self):
        with self.assertRaises(DrawingError):cad_worker.render_isolated('preview',str(self.path),{},0,(100,100),expected_source=self.sig)
        self.assertIsNone(cad_worker._THREAD.session)
        data,_=cad_worker.render_isolated('preview',str(self.path),self.states,0,(100,100),expected_source=self.sig)
        self.assertEqual(self.pixel(data,(20,20)),(255,0,0))
    def test_cancel_before_preview(self):
        for fn in (lambda:preview_snapshot(str(self.path),self.states,0,(100,100),cancelled=lambda:True,expected_source=self.sig),lambda:cad_worker.render_isolated('preview',str(self.path),self.states,0,(100,100),cancelled=lambda:True,expected_source=self.sig)):
            with self.assertRaises(RenderCancelled):fn()
    def test_state_counts_and_search(self):
        rng=random.Random(13);state=DrawingState(self.path)
        layers=[LayerInfo(i,f'도로_ROAD_{i}' if i%2 else f'WATER_{i}',i%3==0,i%7==0) for i in range(200)]
        state.load_metadata(layers,2)
        for _ in range(300):
            i=rng.randrange(200)
            if i%7:state.set_visibility(i,rng.choice([True,False]))
            state.apply_snapshot({rng.randrange(200):rng.choice([True,False]),999:True})
            self.assertEqual(state.visible_count,sum(x.visible for x in state.layers()))
            self.assertEqual(state.layer_count,len(layers))
            self.assertEqual(state.matching_editable_keys(' road '),matching_editable_layers(state.layers(),' road '))
        state.set_all(False);self.assertEqual(state.visible_count,sum(x.visible for x in layers if x.locked))
        state.set_all(True);self.assertEqual(state.visible_count,sum(x.visible or not x.locked for x in layers))
        self.assertFalse(state.set_all(True))
    def test_dxf_catalog_authoritative_and_cancel(self):
        path=self.root/'layers.dxf';doc=ezdxf.new('R2013')
        for i in range(800):
            layer=doc.layers.new(f'도로_{i}')
            if i%2:layer.off()
            if i%3==0:layer.freeze()
        doc.saveas(path)
        before=hashlib.sha256(path.read_bytes()).digest()
        with DrawingDocument(path) as parsed:self.assertEqual(read_ascii_dxf_layers(path),parsed.layers())
        checks=iter([False,False,True])
        with self.assertRaises(InterruptedError):read_ascii_dxf_layers(path,cancelled=lambda:next(checks))
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(),before)
    def test_isolated_dxf_visibility(self):
        path=self.root/'drawing.dxf';doc=ezdxf.new('R2013')
        doc.layers.new('ROAD');doc.layers.new('WATER')
        space=doc.modelspace()
        space.add_line((0,0),(100,100),dxfattribs={'layer':'ROAD','color':1})
        space.add_circle((50,50),20,dxfattribs={'layer':'WATER','color':5})
        doc.saveas(path);before=hashlib.sha256(path.read_bytes()).digest()
        with DrawingDocument(path) as parsed:states=parsed.states()
        sig=source_signature(path)
        a,_=cad_worker.render_isolated('preview',str(path),states,0,(200,200),expected_source=sig)
        states['WATER']=False
        b,_=cad_worker.render_isolated('preview',str(path),states,0,(200,200),expected_source=sig)
        with Image.open(io.BytesIO(a)) as im1, Image.open(io.BytesIO(b)) as im2:
            self.assertNotEqual(im1.tobytes(),im2.tobytes())
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(),before)
    def test_replaced_source_same_size_mtime(self):
        import os
        replacement=self.root/'replacement.pdf';replacement.write_bytes(self.path.read_bytes())
        info=self.path.stat();os.utime(replacement,ns=(info.st_atime_ns,info.st_mtime_ns))
        os.replace(replacement,self.path)
        self.assertEqual(self.path.stat().st_size,info.st_size)
        self.assertEqual(self.path.stat().st_mtime_ns,info.st_mtime_ns)
        self.assertNotEqual(source_signature(self.path),self.sig)
        with self.assertRaises(DrawingError):preview_snapshot(str(self.path),self.states,0,(100,100),expected_source=self.sig)
    def test_catalog_byte_budget(self):
        path=self.root/'bad.dxf';path.write_bytes(b'0\n'+b'A'*10000+b'\n')
        with patch.object(cad_catalog,'MAX_CATALOG_SCAN',64):self.assertIsNone(read_ascii_dxf_layers(path))

if __name__=='__main__':unittest.main(verbosity=2)
