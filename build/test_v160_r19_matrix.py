"""v1.6.0: multiple independent source fixtures and combined extraction paths.
No Windows, native Qt, DWG converter, or real NGII evidence is claimed here.
"""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

import ezdxf
import fitz
from PIL import Image

from drawing_editor.automation import BatchSession, discover_drawings
from drawing_editor.batch import (LayerRule, LayerRuleStore, apply_rule, plan_exports,
                                  prepare_output_folders, run_batch_exports)
from drawing_editor.batch_worker import run_batch_exports_isolated
from drawing_editor.core import (DrawingDocument, DrawingError, OutputOptions,
                                 close_thread_document, render_snapshot)
from drawing_editor.drawing_analysis import save_profile, load_profile
from drawing_editor.layer_tools import (common_layers, apply_common_layers,
                                        plan_advanced_exports)
from drawing_editor.state import DrawingState


class FinalMatrix(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(close_thread_document)
        self.root = Path(tmp.name)
        self.src = self.root/'사업'; self.src.mkdir()
        self.out = self.root/'출력'; self.out.mkdir()
        self.hashes = {}
        self.opts = OutputOptions(resolution='custom', width=240, height=240)

    def register(self, p):
        self.hashes[p] = sha256(p.read_bytes()).hexdigest()
        state = DrawingState(p)
        with DrawingDocument(p) as d:
            state.load_metadata(d.layers(), d.pages)
        return state

    def pdf(self, rel, dims=(120, 120), rotate=0, pages=2):
        p = self.src/rel; p.parent.mkdir(parents=True, exist_ok=True)
        w, h = dims
        with fitz.open() as doc:
            road = doc.add_ocg('ROAD', on=True)
            water = doc.add_ocg('WATER', on=True)
            for i in range(pages):
                page = doc.new_page(width=w, height=h)
                page.draw_rect(fitz.Rect(w*.12, h*.16, w*.40, h*.40), color=None, fill=(1,0,0), oc=road)
                page.draw_rect(fitz.Rect(w*.60, h*.60, w*.88, h*.84), color=None, fill=(0,0,1), oc=water)
                if i: page.draw_rect(fitz.Rect(w*.15,h*.45,w*.25,h*.50),color=None,fill=(1,0,0),oc=road)
                page.set_rotation(rotate)
            doc.save(p)
        return self.register(p)

    def dxf(self, rel, geometry):
        p = self.src/rel; p.parent.mkdir(parents=True, exist_ok=True)
        d = ezdxf.new('R2013')
        for name in ('ROAD','WATER'): d.layers.new(name)
        m = d.modelspace()
        m.add_lwpolyline([(0,0),(100,0),(100,100),(0,100)],close=True,dxfattribs={'layer':'ROAD','color':1})
        if geometry == 'circle': m.add_circle((50,50),45,dxfattribs={'layer':'WATER','color':5})
        elif geometry == 'arc': m.add_arc((50,50),45,0,300,dxfattribs={'layer':'WATER','color':5})
        elif geometry == 'line': m.add_line((0,100),(100,0),dxfattribs={'layer':'WATER','color':5})
        d.saveas(p)
        return self.register(p)

    def folder(self, name):
        p=self.out/name; p.mkdir(); return p

    def verify_sources(self):
        for p,digest in self.hashes.items(): self.assertEqual(sha256(p.read_bytes()).hexdigest(),digest)

    def run_jobs(self, jobs, opts, isolated=False):
        result=(run_batch_exports_isolated if isolated else run_batch_exports)(jobs,opts)
        self.assertEqual(result.errors,(),result)
        self.assertFalse(result.cancelled)
        self.assertEqual(len(result.completed),len(jobs))
        self.verify_sources()
        return result

    def colors(self, path):
        with Image.open(path) as im:
            rgb=im.convert('RGB')
            px=list(rgb.get_flattened_data()) if hasattr(rgb, "get_flattened_data") else list(rgb.getdata())
            return (any(r>180 and r>g+70 and r>b+70 for r,g,b in px),
                    any(b>180 and b>r+70 and b>g+70 for r,g,b in px))

    def test_pdf_multi_document_layer_group_rule_and_page_matrix(self):
        docs=[self.pdf('a/도면.pdf'),self.pdf('b/도면.pdf',(180,100)),self.pdf('c/회전.pdf',(100,180),90)]
        self.assertEqual(len(discover_drawings(self.src,recursive=True)),3)
        self.assertEqual(set(common_layers(docs)),{'road','water'})
        rule=LayerRule('도로만','pdf',(('ROAD',True),('WATER',False)))
        store=LayerRuleStore(self.root/'규칙.json');store.save_all({rule.name:rule})
        loaded=store.load()[rule.name]
        self.assertEqual(loaded,rule)
        self.assertEqual(apply_common_layers(docs,['water'],False),3)
        for d in docs:
            self.assertTrue(apply_rule(d,loaded).matching_kind)
            d.set_all(True)
        original=[d.states() for d in docs]
        for mode,kwargs,count in [('layers',{},12),('groups',{'groups':('도로','수계')},12),('rules',{'rules':(loaded,)},6)]:
            with self.subTest(mode=mode):
                opts=replace(self.opts,background='transparent',crop_margins=(mode=='groups'))
                jobs=plan_advanced_exports(docs,self.folder(mode),opts,mode=mode,scope='range',page_range='1-2',**kwargs)
                self.assertEqual(len(jobs),count)
                self.assertEqual(len({j.target.casefold() for j in jobs}),count)
                self.run_jobs(jobs,opts,isolated=(mode=='rules'))
                for j in jobs:
                    with Image.open(j.target) as im:
                        self.assertEqual(im.mode,'RGBA')
                        self.assertLessEqual(max(im.size),240)
                        self.assertGreater(min(im.size),0)
                    self.assertEqual(self.colors(j.target).count(True),1)
                self.assertEqual([d.states() for d in docs],original)
        profile=self.root/'출력.sdeprofile'
        save_profile(profile,self.opts,mode='groups',scope='range',page_range='1-2',groups=['도로'],rules=[])
        restored,data=load_profile(profile)
        self.assertEqual(restored,self.opts);self.assertEqual(data['page_range'],'1-2')

    def test_pdf_regions_raster_vector_and_preview_matrix(self):
        docs=[self.pdf('square.pdf'),self.pdf('portrait.pdf',(100,180)),self.pdf('rotated.pdf',(180,100),90)]
        for i,d in enumerate(docs):
            d.set_visibility(next(x.key for x in d.layers() if x.name=='WATER'),False)
            d.page_index=1
            # Compare repeated previews, including page rotation and frozen source stamp.
            args=(str(d.path),d.states(),d.page_index,(180,180))
            a=render_snapshot(*args,expected_source=d.source_signature)
            self.assertEqual(a,render_snapshot(*args,expected_source=d.source_signature))
            for fmt in ('png','jpg','pdf','svg'):
                with self.subTest(sheet=i,fmt=fmt):
                    opts=(OutputOptions(fmt=fmt) if fmt in ('pdf','svg') else
                          replace(self.opts,fmt=fmt,region=(0,0,1,.55)))
                    jobs=plan_advanced_exports([d],self.folder(f'{i}-{fmt}'),opts,scope='current')
                    self.run_jobs(jobs,opts)
                    p=Path(jobs[0].target)
                    if fmt=='pdf':
                        with fitz.open(p) as f:
                            self.assertEqual(f.page_count,1)
                            self.assertEqual({k:bool(v['on']) for k,v in f.get_ocgs().items()},d.states())
                    elif fmt=='svg': self.assertIn('<svg',p.read_text(encoding='utf-8'))
                    else:
                        with Image.open(p) as im:
                            self.assertLessEqual(max(im.size),240)
                            self.assertEqual(im.mode,'RGB')
                            self.assertFalse(self.colors(p)[1])
                            if i < 2: self.assertTrue(self.colors(p)[0])
                            # Compare actual clip dimensions to the displayed page, not raw media orientation.
                            with fitz.open(d.path) as pdf:
                                r=pdf[d.page_index].rect
                                scale=min(240/r.width,240/(r.height*.55))
                                self.assertEqual(im.size,(round(r.width*scale),round(r.height*.55*scale)))
        self.verify_sources()

    def test_cad_multiple_geometries_group_and_vector_matrix(self):
        docs=[self.dxf(f'{kind}.dxf',kind) for kind in ('circle','arc','line')]
        for fmt in ('png','jpg','dxf'):
            with self.subTest(fmt=fmt):
                opts=OutputOptions(fmt='dxf') if fmt=='dxf' else replace(self.opts,fmt=fmt)
                jobs=plan_advanced_exports(docs,self.folder(fmt),opts,mode='groups',groups=('도로','수계'))
                self.assertEqual(len(jobs),6)
                self.run_jobs(jobs,opts,isolated=(fmt=='png'))
                for i,j in enumerate(jobs):
                    if fmt=='dxf':
                        cad=ezdxf.readfile(j.target)
                        self.assertEqual({e.dxf.layer for e in cad.modelspace()},{'ROAD' if i%2==0 else 'WATER'})
                    else:
                        self.assertEqual(self.colors(j.target),(True,False) if i%2==0 else (False,True))
        self.verify_sources()

    def test_project_mixed_batch_collision_cancel_checkpoint_retry(self):
        docs=[self.pdf('a/동일.pdf'), self.pdf('b/동일.pdf',(180,100)),self.dxf('c/동일.dxf','arc')]
        jobs=plan_exports(docs,self.out,self.opts,source_root=self.src)
        prepare_output_folders(jobs,self.out)
        self.assertEqual([Path(j.target).parent.name for j in jobs],['a','b','c'])
        session=BatchSession(tuple(jobs),self.opts)
        pre=run_batch_exports_isolated(jobs,self.opts,cancelled=lambda:True)
        self.assertTrue(pre.cancelled);self.assertEqual(pre.completed,())
        collision=Path(jobs[1].target);collision.write_bytes(b'user data')
        result=run_batch_exports_isolated(jobs,self.opts)
        self.assertEqual(len(result.completed),2);self.assertEqual(len(result.errors),1)
        self.assertEqual(collision.read_bytes(),b'user data')
        session.record(jobs,result)
        path=self.root/'checkpoint.json'; session.save_checkpoint(path)
        restored=BatchSession.load_checkpoint(path)
        self.assertEqual(len(restored.retry_plan()[1]),1)
        collision.unlink(); retry,blocked=restored.retry_plan()
        self.assertEqual(len(retry),1);self.assertFalse(blocked)
        restored.record(retry,self.run_jobs(retry,self.opts))
        self.assertEqual(restored.retry_plan(),((),()))
        self.verify_sources()

    def test_standard_plan_rejects_unloaded_and_mixed_pdf_region_before_any_output(self):
        a=self.pdf('pdf.pdf'); b=self.dxf('cad.dxf','circle')
        with self.assertRaises(DrawingError):
            plan_exports([a,DrawingState(a.path)],self.out,self.opts)
        for docs in ([b],[a,b],[b,a]):
            with self.subTest(kinds=[d.kind for d in docs]),self.assertRaises(DrawingError):
                plan_exports(docs,self.out,replace(self.opts,region=(.1,.1,.9,.9)))
        self.assertEqual(list(self.out.iterdir()),[])
        self.verify_sources()


if __name__=='__main__': unittest.main()
