"""R05 rule integrity and no-follow output regression."""
import sys, tempfile, unittest, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fitz
from drawing_editor.batch import LayerRule, LayerRuleStore, ExportJob
from drawing_editor.core import OutputOptions, DrawingError, source_signature, export_snapshot, close_thread_document
from drawing_editor.batch_worker import run_batch_exports_isolated
from drawing_editor.drawing_analysis import save_profile

class R05(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); self.root=Path(t.name); self.addCleanup(close_thread_document)
        self.p=self.root/'rules.json'; self.store=LayerRuleStore(self.p); self.rule=LayerRule('도로','pdf',(('ROAD',True),))
    def test_rule_roundtrip(self):
        self.store.save_all({'도로':self.rule}); self.assertEqual(self.store.load(),{'도로':self.rule})
    def test_invalid_save_preserves_previous(self):
        self.store.save_all({'도로':self.rule}); old=self.p.read_bytes()
        for rule in (LayerRule('bad','pdf',(('A',True),('a',False))),LayerRule('bad','pdf',(('A','false'),)),LayerRule('bad','pdf',(('A'*1025,True),)),LayerRule('bad','pdf',( ('\ud800',True),))):
            with self.assertRaises(DrawingError):self.store.save_all({'bad':rule})
            self.assertEqual(self.p.read_bytes(),old)
    def test_duplicate_json_and_overlimit(self):
        for data in (b'{"presets":[],"presets":[]}', b' '*2_000_001, b'['*2000+b']'*2000):
            self.p.write_bytes(data)
            with self.assertRaises(DrawingError):self.store.load()
    def fixture(self):
        p=self.root/'source.pdf'
        with fitz.open() as doc:
            k=doc.add_ocg('ROAD'); page=doc.new_page(width=100,height=100);page.draw_rect(fitz.Rect(10,10,80,80),fill=(1,0,0),oc=k);doc.save(p)
        return p,k
    def test_worker_rejects_inexact_states_and_page(self):
        p,k=self.fixture()
        for v,page in [('false',0),(True,False),(1,0)]:
            dest=self.root/'out.png';r=run_batch_exports_isolated([ExportJob(str(p),{k:v},page,str(dest),source_signature(p))],OutputOptions());self.assertEqual(len(r.errors),1);self.assertFalse(dest.exists())
    def test_dangling_symlink_output_and_profile(self):
        p,k=self.fixture();outside=self.root/'missing.png';dest=self.root/'out.png'
        try:dest.symlink_to(outside)
        except OSError:self.skipTest('symlink unavailable')
        with self.assertRaises(DrawingError):export_snapshot(str(p),{k:True},0,str(dest),OutputOptions(),expected_source=source_signature(p))
        self.assertFalse(outside.exists());self.assertTrue(dest.is_symlink())
        profile=self.root/'a.sdeprofile';missing=self.root/'missing.sdeprofile';profile.symlink_to(missing)
        with self.assertRaises(DrawingError):save_profile(profile,OutputOptions(),mode='current',scope='current',page_range='',groups=[],rules=[])
        self.assertFalse(missing.exists())
if __name__=='__main__':unittest.main(verbosity=2)
