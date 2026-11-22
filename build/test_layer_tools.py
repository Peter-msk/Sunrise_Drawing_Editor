"""Targeted planner and real source-worker regression for v1.2.0."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from drawing_editor.core import LayerInfo, DrawingError, OutputOptions
from drawing_editor.state import DrawingState
from drawing_editor.batch import LayerRule
from drawing_editor.layer_tools import (classify, group_layers, common_layers, apply_common_layers,
    apply_group, page_indices, plan_advanced_exports)
from drawing_editor.batch_worker import run_batch_exports_isolated

class LayerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.opts=OutputOptions(fmt='png',resolution='custom',width=200,height=200)
    def doc(self,name,layers,pages=1):
        p=self.root/name;p.touch();d=DrawingState(p);d.load_metadata(layers,pages);return d
    def sample(self):
        return self.doc('sheet.pdf',[LayerInfo(1,'A-ROAD-001',True),LayerInfo(2,'WATER',True),LayerInfo(3,'OTHER',False)],3)
    def test_classify_conservative(self):
        for name,expected in [('A-ROAD-001','도로'),('도로','도로'),('Bldg_1','건축물'),('ROAD-WATER','미분류'),('BROAD','미분류'),('수계','수계'),('도로경계','미분류')]:
            self.assertEqual(classify(name),expected)
    def test_group_apply_locked_and_other_preserved(self):
        d=self.doc('a.pdf',[LayerInfo(1,'ROAD',True),LayerInfo(2,'ROAD-2',True,True),LayerInfo(3,'WATER',True)])
        self.assertEqual(len(group_layers(d.layers())['도로']),2)
        self.assertEqual(apply_group(d,'도로',False),1);self.assertEqual(d.states(),{1:False,2:True,3:True})
    def test_common_only_unique_unlocked(self):
        a=self.doc('a.pdf',[LayerInfo(1,'ROAD',True),LayerInfo(2,'Water',True),LayerInfo(3,'TEXT',True),LayerInfo(4,'BOUNDARY',True)])
        b=self.doc('b.pdf',[LayerInfo(10,' road ',True),LayerInfo(20,'WATER',True),LayerInfo(21,'water',True),LayerInfo(30,'TEXT',True,True)])
        self.assertEqual(common_layers([a,b]),{'road':'ROAD'})
        self.assertEqual(apply_common_layers([a,b],['road'],False),2);self.assertFalse(a.states()[1]);self.assertFalse(b.states()[10]);self.assertTrue(b.states()[30])
        with self.assertRaises(DrawingError):apply_common_layers([a,b],['water'],False)
    def test_pages_range_and_cad(self):
        d=self.sample();d.page_index=1
        self.assertEqual(page_indices(d,'current'),(1,));self.assertEqual(page_indices(d,'all'),(0,1,2));self.assertEqual(page_indices(d,'range','2-3'),(1,2))
        for bad in ('0','3-1','1-4','1,2',''):
            with self.assertRaises(DrawingError):page_indices(d,'range',bad)
        cad=self.doc('c.dxf',[LayerInfo('A','ROAD',True)]);self.assertEqual(page_indices(cad,'all'),(0,))
    def test_individual_layer_outputs_nonmutating(self):
        d=self.sample();old=d.states();jobs=plan_advanced_exports([d],self.root,self.opts,mode='layers',scope='all')
        self.assertEqual(len(jobs),6);self.assertEqual(jobs[0].states,{1:True,2:False,3:False});self.assertEqual(jobs[3].states,{1:False,2:True,3:False});self.assertEqual(d.states(),old);self.assertEqual(d.page_index,0)
    def test_group_output_and_missing(self):
        d=self.sample();jobs=plan_advanced_exports([d],self.root,self.opts,mode='groups',groups=['수계','도로'])
        self.assertEqual(len(jobs),2);self.assertEqual(jobs[0].states,{1:False,2:True,3:False})
        with self.assertRaises(DrawingError):plan_advanced_exports([d],self.root,self.opts,mode='groups',groups=['식생'])
    def test_rules_isolated_and_mismatch(self):
        d=self.sample();a=LayerRule('road','pdf',(('A-ROAD-001',True),));b=LayerRule('water','pdf',(('Water',True),));jobs=plan_advanced_exports([d],self.root,self.opts,mode='rules',rules=[a,b])
        self.assertEqual([j.states for j in jobs],[{1:True,2:False,3:False},{1:False,2:True,3:False}])
        for invalid in [LayerRule('bad','dxf',a.layers),LayerRule('bad','pdf',(('missing',True),)),LayerRule('bad','pdf',(('WATER',False),))]:
            with self.assertRaises(DrawingError):plan_advanced_exports([d],self.root,self.opts,mode='rules',rules=[invalid])
    def test_locked_visible_blocks_false_isolation(self):
        d=self.doc('a.pdf',[LayerInfo(1,'ROAD',True),LayerInfo(2,'WATER',True,True)])
        with self.assertRaises(DrawingError):plan_advanced_exports([d],self.root,self.opts,mode='layers')
    def test_collision_and_filename_safety(self):
        d=self.sample();a=LayerRule('a/b','pdf',(('WATER',True),));b=LayerRule('a:b','pdf',(('WATER',True),));
        (self.root/'SHEET_P0001_A_B.PNG').touch();jobs=plan_advanced_exports([d],self.root,self.opts,mode='rules',rules=[a,b]);names=[Path(j.target).name for j in jobs]
        self.assertEqual(len(set(n.casefold() for n in names)),2);self.assertNotIn('sheet_p0001_a_b.png',[x.casefold() for x in names]);self.assertTrue(all(Path(j.target).parent==self.root for j in jobs))
    def test_job_limit(self):
        d=self.sample()
        with patch('drawing_editor.layer_tools.MAX_JOBS',2),self.assertRaises(DrawingError):plan_advanced_exports([d],self.root,self.opts,scope='all')
        with patch('drawing_editor.layer_tools.MAX_STATE_ENTRIES',2),self.assertRaises(DrawingError):plan_advanced_exports([d],self.root,self.opts)
    def test_real_pdf_worker_page_and_layer_pixels(self):
        import fitz
        from PIL import Image
        path=self.root/'source.pdf'
        with fitz.open() as pdf:
            red=pdf.add_ocg('ROAD',on=1);blue=pdf.add_ocg('WATER',on=1)
            for i in range(2):
                page=pdf.new_page(width=100,height=100)
                page.draw_rect(fitz.Rect(10+i*10,10,40+i*10,40),color=None,fill=(1,0,0),oc=red)
                page.draw_rect(fitz.Rect(60,60,90,90),color=None,fill=(0,0,1),oc=blue)
            pdf.save(path)
        digest=lambda:hashlib.sha256(path.read_bytes()).hexdigest()
        before=digest();doc=DrawingState(path);doc.load_metadata([LayerInfo(red,'ROAD',True),LayerInfo(blue,'WATER',True)],2)
        jobs=plan_advanced_exports([doc],self.root,self.opts,mode='layers',scope='all')
        result=run_batch_exports_isolated(jobs,self.opts)
        self.assertEqual(len(result.completed),4);self.assertFalse(result.errors)
        for i,job in enumerate(jobs):
            with Image.open(job.target) as image:
                rgb=image.convert('RGB');self.assertEqual(rgb.size,(200,200));self.assertEqual(rgb.getpixel((70 if i%2 else 30,30)),(255,0,0) if i<2 else (255,255,255));self.assertEqual(rgb.getpixel((150,150)),(255,255,255) if i<2 else (0,0,255))
        self.assertEqual(digest(),before);self.assertEqual(doc.states(),{red:True,blue:True})

    def test_real_dxf_worker_group_export(self):
        import ezdxf
        from PIL import Image, ImageChops
        from drawing_editor.core import DrawingDocument
        path=self.root/'source.dxf'
        cad=ezdxf.new('R2013');cad.layers.new('ROAD');cad.layers.new('WATER')
        model=cad.modelspace()
        model.add_lwpolyline([(0,0),(100,0),(100,100),(0,100)],close=True,dxfattribs={'layer':'ROAD','color':1})
        model.add_circle((50,50),50,dxfattribs={'layer':'WATER','color':5})
        cad.saveas(path);before=hashlib.sha256(path.read_bytes()).hexdigest()
        state=DrawingState(path)
        with DrawingDocument(path) as doc:state.load_metadata(doc.layers(),doc.pages)
        old=state.states();jobs=plan_advanced_exports([state],self.root,self.opts,mode='groups',groups=['도로','수계'])
        result=run_batch_exports_isolated(jobs,self.opts)
        self.assertEqual(len(result.completed),2);self.assertFalse(result.errors)
        with Image.open(jobs[0].target) as road,Image.open(jobs[1].target) as water:
            a,b=road.convert('RGB'),water.convert('RGB')
            self.assertEqual(a.size,b.size);self.assertIsNotNone(ImageChops.difference(a,b).getbbox())
            self.assertTrue(any(r>g+30 and r>b+30 for _,(r,g,b) in a.getcolors(a.width*a.height)))
            self.assertTrue(any(b>r+30 and b>g+30 for _,(r,g,b) in b.getcolors(b.width*b.height)))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before);self.assertEqual(state.states(),old)

    def test_real_pdf_rule_variants_and_cancel(self):
        import fitz
        from PIL import Image
        path=self.root/'rules.pdf'
        with fitz.open() as pdf:
            page=pdf.new_page(width=100,height=100)
            a=pdf.add_ocg('ROAD',on=1);b=pdf.add_ocg('WATER',on=1)
            page.draw_rect(fitz.Rect(10,10,30,30),color=None,fill=(1,0,0),oc=a)
            page.draw_rect(fitz.Rect(60,60,80,80),color=None,fill=(0,0,1),oc=b)
            pdf.save(path)
        state=DrawingState(path);state.load_metadata([LayerInfo(a,'ROAD',True),LayerInfo(b,'WATER',True)],1)
        rules=[LayerRule('road','pdf',(('ROAD',True),)),LayerRule('water','pdf',(('WATER',True),))]
        jobs=plan_advanced_exports([state],self.root,self.opts,mode='rules',rules=rules)
        cancelled=run_batch_exports_isolated(jobs,self.opts,cancelled=lambda:True)
        self.assertTrue(cancelled.cancelled);self.assertFalse(any(Path(j.target).exists() for j in jobs))
        result=run_batch_exports_isolated(jobs,self.opts);self.assertEqual(len(result.completed),2);self.assertFalse(result.errors)
        with Image.open(jobs[0].target) as x,Image.open(jobs[1].target) as y:
            self.assertEqual(x.convert('RGB').getpixel((40,40)),(255,0,0));self.assertEqual(x.convert('RGB').getpixel((140,140)),(255,255,255))
            self.assertEqual(y.convert('RGB').getpixel((40,40)),(255,255,255));self.assertEqual(y.convert('RGB').getpixel((140,140)),(0,0,255))

if __name__=='__main__':unittest.main(verbosity=2)
