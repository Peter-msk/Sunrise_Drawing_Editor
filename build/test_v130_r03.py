"""R03 native viewport export and profile boundary contracts."""
from dataclasses import asdict, replace
from io import BytesIO
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageChops
from drawing_editor.core import DrawingError, OutputOptions
from drawing_editor.drawing_analysis import load_profile
from drawing_editor.ui_interaction import viewport_region, analysis_snapshot_is_current
from drawing_editor import cad_worker
from test_v130 import V130Tests


class Bands(unittest.TestCase):
    def test_viewport_clamp_and_invalid(self):
        self.assertEqual(viewport_region((200,100),(-5,20,150,120)),(0.,.2,.75,1.))
        self.assertEqual(viewport_region((200,100),(0,0,200,100)),(0.,0.,1.,1.))
        for size,clip in [((0,100),(0,0,1,1)),((200,100),None),((200,100),(201,0,220,10)),((200,100),(10,5,10,6)),((200,100),(float('nan'),0,30,40))]:
            self.assertIsNone(viewport_region(size,clip))
    def test_profile_encoding(self):
        body=dict(schema_version=1,options=asdict(OutputOptions()),mode='current',scope='current',page_range='',groups=[],rules=[])
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'input.sdeprofile'; raw=json.dumps(body)
            for enc in ('utf-8','utf-8-sig'):
                p.write_bytes(raw.encode(enc));self.assertEqual(load_profile(p)[1],body)
            for enc in ('utf-16','utf-32'):
                p.write_bytes(raw.encode(enc))
                with self.assertRaises(DrawingError):load_profile(p)

class WorkerCases(V130Tests):
    def test_viewport_native_rotated_pdf(self):
        d=self.pdf(rotation=90); original=self.digest(d.path)
        region=viewport_region((100,100),(0,0,100,50))
        out=self.output(d,replace(self.opts,width=800,height=800,region=region,background='transparent'))
        with Image.open(out) as im:
            self.assertEqual(im.size,(800,400));self.assertEqual(im.getpixel((400,200)),(255,0,0,126))
        self.assertEqual(self.digest(d.path),original)
    def test_analysis_registration_and_state_identity(self):
        d=self.pdf(); s=self.snap(d); registry={str(d.path):d}
        self.assertTrue(analysis_snapshot_is_current(d,s,registry))
        self.assertFalse(analysis_snapshot_is_current(d,s,{}))
        self.assertFalse(analysis_snapshot_is_current(d,s,{str(d.path):self.state(d.path)}))
        d.set_visibility(d.layers()[0].key,False)
        self.assertFalse(analysis_snapshot_is_current(d,s,registry))
        d.set_visibility(d.layers()[0].key,True);d.page_index=1
        self.assertFalse(analysis_snapshot_is_current(d,s,registry))
if __name__=='__main__':
    suite=unittest.TestLoader().loadTestsFromTestCase(Bands)
    suite.addTests(WorkerCases(name) for name in vars(WorkerCases) if name.startswith('test_'))
    sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
