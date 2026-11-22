"""Actual source-worker batch retry and bounded folder discovery tests."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz
from PIL import Image
from drawing_editor.automation import discover_drawings, BatchSession
from drawing_editor.batch import ExportJob, BatchResult, LayerRule, apply_rule, plan_exports
from drawing_editor.batch_worker import run_batch_exports_isolated
from drawing_editor.core import DrawingError, LayerInfo, OutputOptions, source_signature
from drawing_editor.state import DrawingState
from build.functional_gate import read_functional_qa, STATUS, V140_REQUIRED, EXTRACTION_REQUIRED

class AutomationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.opts = OutputOptions(resolution='custom', width=100, height=100)

    def pdf(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with fitz.open() as doc:
            keep = doc.add_ocg('ROAD'); hide = doc.add_ocg('WATER')
            page = doc.new_page(width=100, height=100)
            page.draw_rect(fitz.Rect(10,10,45,90), color=None, fill=(0,0,1), oc=keep)
            page.draw_rect(fitz.Rect(55,10,90,90), color=None, fill=(1,0,0), oc=hide)
            doc.save(path)
        state = DrawingState(path)
        state.load_metadata([LayerInfo(keep,'ROAD',True), LayerInfo(hide,'WATER',True)],1)
        return state

    def test_folder_recursive_sorted_and_filter(self):
        for name in ['b.PDF','a.dxf','sub/c.DWG','sub/skip.txt','sub/deep/D.pdf']:
            p = self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.touch()
        self.assertEqual([Path(x).name for x in discover_drawings(self.root)], ['a.dxf','b.PDF'])
        self.assertEqual([Path(x).relative_to(self.root).as_posix() for x in discover_drawings(self.root,recursive=True)], ['a.dxf','b.PDF','sub/c.DWG','sub/deep/D.pdf'])

    def test_symlink_not_followed(self):
        (self.root/'real').mkdir();(self.root/'real/a.pdf').touch()
        try:
            (self.root/'loop').symlink_to(self.root,target_is_directory=True)
            (self.root/'alias.pdf').symlink_to(self.root/'real/a.pdf')
        except OSError as exc:
            self.skipTest(str(exc))
        self.assertEqual(len(discover_drawings(self.root,recursive=True)),1)

    def test_limit_and_cancel(self):
        for name in ['a.pdf','b.pdf']:(self.root/name).touch()
        with patch('drawing_editor.automation.MAX_FILES',1):
            with self.assertRaises(DrawingError):discover_drawings(self.root)
        with patch('drawing_editor.automation.MAX_ENTRIES',1):
            with self.assertRaises(DrawingError):discover_drawings(self.root)
        with self.assertRaises(InterruptedError):discover_drawings(self.root,cancelled=lambda:True)

    def test_actual_worker_failure_retry_and_pixels(self):
        docs = [self.pdf('site/a.pdf'),self.pdf('site/b.pdf')]
        rule = LayerRule('roads','pdf',(('ROAD',True),('WATER',False)))
        for doc in docs:self.assertEqual(apply_rule(doc,rule).matched,2)
        originals = [hashlib.sha256(d.path.read_bytes()).hexdigest() for d in docs]
        jobs = plan_exports(docs,self.root,self.opts)
        session = BatchSession(tuple(jobs),self.opts)
        collision = Path(jobs[1].target);collision.write_bytes(b'guard')
        result = run_batch_exports_isolated(jobs,self.opts);session.record(jobs,result)
        self.assertEqual(len(result.completed),1);self.assertEqual(len(result.errors),1)
        self.assertEqual(collision.read_bytes(),b'guard')
        self.assertEqual(len(session.retry_plan()[1]),1)
        old_output = Path(jobs[0].target).read_bytes()
        collision.unlink()
        retry,blocked = session.retry_plan();self.assertEqual(retry,(jobs[1],));self.assertFalse(blocked)
        # A subsequent GUI layer toggle cannot change the captured job state.
        docs[1].set_all(True)
        result = run_batch_exports_isolated(retry,session.options);session.record(retry,result)
        self.assertEqual(session.retry_plan(),((),()))
        self.assertEqual(Path(jobs[0].target).read_bytes(),old_output)
        for job in jobs:
            with Image.open(job.target) as im:
                self.assertEqual(im.getpixel((25,50)),(0,0,255));self.assertEqual(im.getpixel((75,50)),(255,255,255))
        self.assertEqual(originals,[hashlib.sha256(d.path.read_bytes()).hexdigest() for d in docs])
        self.assertEqual([j['status'] for j in session.report()['jobs']],['completed','completed'])
        self.assertEqual(session.attempts,2)

    def test_cancel_and_worker_error_dont_infer_success(self):
        doc = self.pdf('a.pdf'); jobs = plan_exports([doc],self.root,self.opts)
        session = BatchSession(tuple(jobs),self.opts)
        result = run_batch_exports_isolated(jobs,self.opts,cancelled=lambda:True)
        session.record(jobs,result);self.assertEqual(session.last_status,'cancelled')
        self.assertEqual(session.retry_plan()[0],tuple(jobs))
        Path(jobs[0].target).write_bytes(b'unknown')
        session.record(jobs,error='worker terminated')
        self.assertEqual(session.report()['jobs'][0]['status'],'blocked')
        self.assertEqual(session.last_status,'worker_error')

    def test_changed_source_and_report_no_overwrite(self):
        doc = self.pdf('a.pdf');jobs=plan_exports([doc],self.root,self.opts)
        session = BatchSession(tuple(jobs),self.opts)
        doc.path.write_bytes(b'changed')
        self.assertEqual(session.retry_plan()[0],())
        report = self.root/'report.json';session.save_report(report)
        saved=report.read_bytes();self.assertEqual(json.loads(saved)['jobs'][0]['status'],'blocked')
        with self.assertRaises(FileExistsError):session.save_report(report)
        self.assertEqual(saved,report.read_bytes());self.assertFalse(list(self.root.glob('.sde-report-*')))

    def test_standard_plan_bounded(self):
        doc=self.pdf('a.pdf')
        with patch('drawing_editor.layer_tools.MAX_JOBS',1):
            with self.assertRaises(DrawingError):plan_exports([doc,doc],self.root,self.opts)
        with patch('drawing_editor.layer_tools.MAX_STATE_ENTRIES',1):
            with self.assertRaises(DrawingError):plan_exports([doc],self.root,self.opts)

    def test_version_gate_requires_current_extraction_only(self):
        path=self.root/'qa.json'; data=dict(schema_version=1,sha256='a'*64,status=STATUS,checks_passed=sorted(V140_REQUIRED),not_run=[])
        path.write_text(json.dumps(data))
        with self.assertRaises(RuntimeError):read_functional_qa(path,'a'*64,version='1.5.0')
        data['checks_passed']=sorted(EXTRACTION_REQUIRED);path.write_text(json.dumps(data))
        self.assertEqual(read_functional_qa(path,'a'*64,version='1.5.0'),data)

if __name__ == '__main__':unittest.main()
