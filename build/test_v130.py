"""v1.3.0 focused real PDF/DXF worker and profile tests (no Qt claim)."""
from dataclasses import replace, asdict
from pathlib import Path
import hashlib
import io
import json
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fitz
import ezdxf
from PIL import Image
from drawing_editor.core import (DrawingDocument, DrawingError, OutputOptions, LayerInfo,
    source_signature, export_snapshot, close_thread_document)
from drawing_editor.state import DrawingState
from drawing_editor.layer_tools import plan_advanced_exports
from drawing_editor.batch_worker import run_batch_exports_isolated
from drawing_editor.drawing_analysis import (structure_report, inspect_source,
    save_profile, load_profile, checked_profile)
from drawing_editor.cad_worker import shutdown_all_workers

class V130Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.addCleanup(close_thread_document); self.addCleanup(shutdown_all_workers)
        self.root=Path(self.tmp.name)
        self.opts=OutputOptions(resolution='custom',width=400,height=400)
    def pdf(self,name='source.pdf',rotation=0,offset=0,size=100):
        path=self.root/name
        with fitz.open() as pdf:
            red=pdf.add_ocg('ROAD',on=True);blue=pdf.add_ocg('WATER',on=True)
            p=pdf.new_page(width=size,height=100)
            p.draw_rect(fitz.Rect(0,0,50,100),color=None,fill=(1,0,0),fill_opacity=.5,oc=red)
            p.draw_rect(fitz.Rect(50+offset,0,100,100),color=None,fill=(0,0,1),oc=blue)
            p.set_rotation(rotation);pdf.save(path)
        return self.state(path)
    def dxf(self):
        path=self.root/'a.dxf';d=ezdxf.new('R2013');d.layers.new('ROAD');d.layers.new('WATER')
        m=d.modelspace();m.add_circle((0,0),10,dxfattribs={'layer':'ROAD','color':1});m.add_line((-10,-10),(10,-10),dxfattribs={'layer':'WATER','color':5});d.saveas(path)
        return self.state(path)
    def state(self,path):
        s=DrawingState(path)
        with DrawingDocument(path) as d:s.load_metadata(d.layers(),d.pages)
        return s
    def snap(self,d):return str(d.path),d.states(),d.page_index,d.source_signature
    def digest(self,p):return hashlib.sha256(p.read_bytes()).hexdigest()
    def output(self,d,o):
        jobs=plan_advanced_exports([d],self.root,o)
        r=run_batch_exports_isolated(jobs,o);self.assertFalse(r.errors);self.assertEqual(len(r.completed),1)
        return Path(r.completed[0])
    def test_region_rotated_transparent_small_and_tiled(self):
        d=self.pdf(rotation=90);before=self.digest(d.path)
        for n in (600,4000):
            opts=replace(self.opts,width=n,height=n,region=(.1,.1,.9,.9),background='transparent')
            p=self.output(d,opts)
            with Image.open(p) as im:
                self.assertEqual(im.size,(n,n));self.assertEqual(im.getpixel((n//2,n//4)),(255,0,0,126));self.assertEqual(im.getpixel((n//2,3*n//4)),(0,0,255,255))
        self.assertEqual(self.digest(d.path),before)
    def test_region_fractional_jpeg_and_dpi(self):
        d=self.pdf(size=101.32);opts=OutputOptions(fmt='jpg',resolution='dpi',dpi=144,region=(.1,.2,.4,.8))
        p=self.output(d,opts)
        with Image.open(p) as im:
            self.assertEqual(im.size,(61,120));self.assertGreater(im.getpixel((30,60))[0],245);self.assertTrue(115<=im.getpixel((30,60))[1]<=145)
        with DrawingDocument(d.path) as doc:self.assertEqual(doc.export_dimensions(opts),(61,120,144))
    def test_region_visibility_and_original_dpi(self):
        d=self.pdf();d.set_visibility(d.layers()[0].key,False)
        p=self.output(d,OutputOptions(region=(0,0,.5,1)))
        with Image.open(p) as im:self.assertEqual(im.size,(208,417));self.assertEqual(im.getpixel((50,50)),(255,255,255))
    def test_invalid_region_and_mode(self):
        for r in [(0,0,0,1),(-1,0,1,1),(0,0,float('nan'),1),(0,0,True,1),(0,0,1e-10,1),(0,0,1,2)]:
            with self.assertRaises(DrawingError):replace(self.opts,region=r).checked()
        with self.assertRaises(DrawingError):replace(self.opts,region=(0,0,1,1),crop_margins=True).checked()
        d=self.dxf()
        with self.assertRaises(DrawingError):plan_advanced_exports([d],self.root,replace(self.opts,region=(0,0,1,1)))
    def test_structure_report(self):
        a=self.pdf()
        report=structure_report(a);self.assertEqual(report['layers'],2);self.assertEqual(report['groups'],{'도로':1,'수계':1})
    def test_inspect_actual_sources(self):
        p=self.pdf(rotation=90);d=self.dxf()
        r=inspect_source(self.snap(p));self.assertEqual(r['페이지 회전 (도)'],90);self.assertEqual(r['OCG 레이어'],2)
        r=inspect_source(self.snap(d));self.assertEqual(r['객체 유형별'],{'CIRCLE':1,'LINE':1});self.assertEqual(r['레이어별 최상위 객체 수'],{'ROAD':1,'WATER':1})
    def test_stale_and_cancelled_analysis(self):
        a=self.pdf();b=self.pdf('b.pdf');s=self.snap(a)
        with a.path.open('ab') as f:f.write(b'\n% modified')
        for fn in (lambda:structure_report(a),lambda:inspect_source(s)):
            with self.assertRaises(DrawingError):fn()
        with self.assertRaises(DrawingError):inspect_source(self.snap(b),lambda:True)
    def test_profile_roundtrip_and_protect_existing(self):
        p=self.root/'a.sdeprofile';o=replace(self.opts,region=(.1,.2,.8,.9))
        params=dict(mode='groups',scope='all',page_range='',groups=['도로'],rules=[])
        save_profile(p,o,**params);old=p.read_bytes();loaded,data=load_profile(p)
        self.assertEqual(tuple(loaded.region),o.region);self.assertEqual(data['groups'],params['groups']);self.assertEqual(loaded.width,400)
        self.assertNotIn('source',data)
        with self.assertRaises(DrawingError):save_profile(p,o,**params)
        self.assertEqual(p.read_bytes(),old)
    def test_invalid_profiles(self):
        payload=dict(schema_version=1,options=asdict(self.opts),mode='current',scope='current',page_range='',groups=[],rules=[])
        for bad in [dict(payload,schema_version=True),dict(payload,groups=['도로']),dict(payload,options={'fmt':'png'}),dict(payload,rules=['x']),dict(payload,scope='x')]:
            with self.assertRaises(DrawingError):checked_profile(bad)
        p=self.root/'large.sdeprofile';p.write_bytes(b' '*65537)
        with self.assertRaises(DrawingError):load_profile(p)

if __name__=='__main__': unittest.main(verbosity=2)
