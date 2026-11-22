"""R02 real-worker and profile regression tests."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_v130 import V130Tests
from drawing_editor import core, cad_worker
from drawing_editor.core import DrawingError, export_snapshot
from drawing_editor.drawing_analysis import checked_profile, load_profile
from drawing_editor.layer_tools import parse_page_range

class Stability(V130Tests):
    def test_worker_inspect_and_recover(self):
        p,states,page,sig=self.snap(self.pdf())
        reply=cad_worker.render_isolated('inspect',p,states,page,(1,1),expected_source=sig)
        self.assertEqual(reply['OCG 레이어'],2)
        with self.assertRaises(DrawingError):cad_worker.render_isolated('inspect',p,states,99,(1,1),expected_source=sig)
        self.assertEqual(cad_worker.render_isolated('inspect',p,states,page,(1,1),expected_source=sig),reply)
        p,states,page,sig=self.snap(self.dxf());reply=cad_worker.render_isolated('inspect',p,states,page,(1,1),expected_source=sig)
        self.assertEqual(reply['객체 유형별'],{'CIRCLE':1,'LINE':1})
        cad_worker.close_thread_worker();self.assertIsNone(cad_worker._THREAD.session)
    def test_inspect_cancel_and_stale(self):
        p,states,page,sig=self.snap(self.pdf())
        with self.assertRaises(DrawingError):cad_worker.render_isolated('inspect',p,states,page,(1,1),expected_source=sig,cancelled=lambda:True)
        with open(p,'ab') as f:f.write(b'\n% changed')
        with self.assertRaises(DrawingError):cad_worker.render_isolated('inspect',p,states,page,(1,1),expected_source=sig)
    def payload(self):
        return dict(schema_version=1,options=asdict(self.opts),mode='current',scope='range',page_range='1-3',groups=[],rules=[])
    def test_profile_validation(self):
        for v in ('','0','4-2','1-1001','a-b'):
            with self.assertRaises(DrawingError):checked_profile(dict(self.payload(),page_range=v))
        for key,v in [('fmt',[]),('dpi',True),('width',False),('background',{}),('resolution',[]),('cad_color',['\ud800','#00FF00'])]:
            body=self.payload();body['options'][key]=v
            with self.assertRaises(DrawingError):checked_profile(body)
        self.assertEqual(parse_page_range(' 1 - 3 '),(1,3));checked_profile(self.payload())
    def test_duplicate_json_keys_profile(self):
        p=self.root/'p.sdeprofile';raw=json.dumps(self.payload());p.write_text(raw.replace('"schema_version": 1','"schema_version": 1, "schema_version": 1'))
        with self.assertRaises(DrawingError):load_profile(p)
        p.write_text(raw.replace('"fmt": "png"','"fmt": "png", "fmt": "jpg"'))
        with self.assertRaises(DrawingError):load_profile(p)

if __name__=='__main__':
    # Run the seven added cases; R01 cases are run separately by the existing suite.
    suite=unittest.TestSuite(Stability(name) for name in vars(Stability) if name.startswith('test_'))
    sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
