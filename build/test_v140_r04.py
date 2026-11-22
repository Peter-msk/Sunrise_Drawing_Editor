"""Extraction-only scope and retained output contracts."""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from drawing_editor import core, drawing_analysis
from drawing_editor.batch_worker import worker_main
from drawing_editor.core import DrawingDocument, DrawingError, OutputOptions
from drawing_editor.drawing_analysis import load_profile, save_profile
from drawing_editor.layer_tools import plan_advanced_exports
from test_v130 import V130Tests

class ExtractionOnly(V130Tests):
    def test_legacy_profile_migration_and_rejection(self):
        p=self.root/'old.sdeprofile'
        body=dict(schema_version=1,options=dict(asdict(self.opts),cad_color=None),mode='current',scope='current',page_range='',groups=[],rules=[])
        p.write_text(json.dumps(body)); old=p.read_bytes()
        opts,data=load_profile(p)
        self.assertEqual(opts,self.opts);self.assertNotIn('cad_color',data['options']);self.assertEqual(old,p.read_bytes())
        fresh=self.root/'new.sdeprofile';save_profile(fresh,opts,mode='current',scope='current',page_range='',groups=[],rules=[])
        self.assertNotIn('cad_color',json.loads(fresh.read_text())['options'])
        body['options']['cad_color']=['ROAD','#00FF00'];p.write_text(json.dumps(body));old=p.read_bytes()
        with self.assertRaisesRegex(DrawingError,'제거'):load_profile(p)
        self.assertEqual(p.read_bytes(),old)
    def test_worker_rejects_removed_option(self):
        d=self.dxf();request=self.root/'request.json';target=self.root/'output.png'
        request.write_text(json.dumps(dict(options=dict(asdict(self.opts),cad_color=['ROAD','#00FF00']),jobs=[dict(source=str(d.path),states=d.states(),page_index=0,target=str(target))])))
        self.assertEqual(worker_main([str(self.root)]),3)
        result=json.loads((self.root/'result.json').read_text());self.assertFalse(result['ok']);self.assertIn('cad_color',result['error']);self.assertFalse(target.exists())
    def test_removed_engine_symbols(self):
        self.assertNotIn('cad_color',asdict(OutputOptions()))
        for symbol in ('compare_structure','compare_pdf_pages','_comparison_overlay'):
            self.assertFalse(hasattr(drawing_analysis,symbol))
        with self.assertRaises(TypeError):OutputOptions(cad_color=('ROAD','#00FF00'))
    def test_original_color_and_visibility(self):
        d=self.dxf();original=self.digest(d.path);a=self.output(d,self.opts)
        d.set_visibility('ROAD',False);b=self.output(d,self.opts)
        d.set_visibility('ROAD',True);c=self.output(d,self.opts)
        with Image.open(a) as x, Image.open(b) as y, Image.open(c) as z:
            def red(im):return any(r>g+80 and r>b+80 for r,g,b in im.convert('RGB').getdata())
            self.assertTrue(red(x));self.assertFalse(red(y));self.assertEqual(x.tobytes(),z.tobytes())
        self.assertEqual(original,self.digest(d.path))
    def test_current_plan_does_not_materialize_layers(self):
        d=self.pdf();states=d.states()
        with patch.object(d,'layers',side_effect=AssertionError('unneeded layers')):
            jobs=plan_advanced_exports([d],self.root,self.opts,mode='current',scope='all')
        self.assertEqual(len(jobs),1);self.assertEqual(jobs[0].states,states)
        self.assertEqual(d.states(),states)
    def test_unchanged_snapshot_skips_copy(self):
        d=self.pdf()
        with DrawingDocument(d.path) as doc:
            states=doc.states()
            with patch.object(doc,'states',side_effect=AssertionError('unneeded copy')):
                doc.apply_snapshot(states)
            delta=dict(states);delta[next(iter(delta))]=False
            doc.apply_snapshot(delta);self.assertEqual(doc.states(),delta)
            doc.apply_snapshot(states);self.assertEqual(doc.states(),states)
    def test_existing_vector_contracts_remain(self):
        d=self.dxf();jobs=plan_advanced_exports([d],self.root,OutputOptions(fmt='dxf'))
        self.assertEqual(len(jobs),1);self.assertEqual(Path(jobs[0].target).suffix,'.dxf')

if __name__=='__main__':
    suite=unittest.TestSuite(ExtractionOnly(name) for name in vars(ExtractionOnly) if name.startswith('test_'))
    sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
