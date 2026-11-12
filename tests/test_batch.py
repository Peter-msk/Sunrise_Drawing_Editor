"""Integration tests for persisted layer rules and multi-file output."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageChops

from drawing_editor.batch import (
    LayerRule, LayerRuleStore, layer_name_key, apply_rule, plan_exports,
    run_batch_exports,
)
from drawing_editor.core import DrawingDocument, DrawingError, OutputOptions
from test_core import create_pdf, create_dxf


class BatchFeatureTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.pdf_a=self.root/'onmap01.pdf'
        self.pdf_b=self.root/'onmap02.pdf'
        self.dxf=self.root/'plan.dxf'
        create_pdf(self.pdf_a)
        create_pdf(self.pdf_b)
        create_dxf(self.dxf)
        self.out=self.root/'images'
        self.out.mkdir()

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_save_load_rule_and_apply_to_another_pdf(self):
        before={path:self.sha(path) for path in (self.pdf_a,self.pdf_b)}
        with DrawingDocument(self.pdf_a) as source, DrawingDocument(self.pdf_b) as target:
            source.set_visibility(source.layers()[0].key,False)
            source.set_visibility(source.layers()[1].key,True)
            rule=LayerRule.from_document('온맵 기본',source)
            self.assertEqual(len(rule.layers),2)
            store=LayerRuleStore(self.root/'presets'/'layer_rules.json')
            store.save_all({rule.name:rule})
            restored=store.load()[rule.name]
            self.assertEqual(rule,restored)
            self.assertEqual(restored.kind,'pdf')
            target_ids={layer.name:layer.key for layer in target.layers()}
            result=apply_rule(target,restored)
            self.assertEqual((result.matched,result.changed), (2,1))
            self.assertFalse(target.states()[target_ids['하천']])
            self.assertTrue(target.states()[target_ids['도로']])
            result=apply_rule(target,restored)
            self.assertEqual(result.changed,0)
        self.assertEqual({p:self.sha(p) for p in before},before)

    def test_rule_handles_different_ocg_ids(self):
        with DrawingDocument(self.pdf_a) as source, DrawingDocument(self.pdf_b) as target:
            rule=LayerRule.from_document('sample',source)
            # A policy uses names, never source object identifiers.
            self.assertEqual(rule.layers[0][0], '하천')
            self.assertEqual(len(rule.layers[0]),2)
            self.assertIsInstance(rule.layers[0][0],str)
            original=source.layers()[0].key
            self.assertNotIn(str(original), [key for key,visible in rule.layers])
            self.assertEqual(apply_rule(target,rule).matched,2)

    def test_mismatch_does_not_touch_cad(self):
        with DrawingDocument(self.pdf_a) as pdf, DrawingDocument(self.dxf) as cad:
            rule=LayerRule.from_document('PDF 기본',pdf)
            old=cad.states()
            report=apply_rule(cad,rule)
            self.assertFalse(report.matching_kind)
            self.assertEqual(cad.states(),old)

    def test_missing_layers_are_not_turned_off(self):
        with DrawingDocument(self.pdf_a) as doc:
            before=doc.states()
            report=apply_rule(doc,LayerRule('custom','pdf',(('없는 레이어',False),('도로',False))))
            self.assertEqual(report.missing,1)
            self.assertEqual(report.changed,1)
            self.assertEqual(doc.states()[doc.layers()[0].key],before[doc.layers()[0].key])
            self.assertFalse(doc.states()[doc.layers()[1].key])

    def test_name_normalization_and_ambiguous_targets(self):
        self.assertEqual(layer_name_key('  ＲＯＡＤ '),layer_name_key('road'))
        @dataclass
        class FakeLayer:
            key: int
            name: str
            visible: bool = True
            locked: bool = False
        class FakeDocument:
            kind='pdf'
            def __init__(self):
                self._layers=[FakeLayer(1,'도로'),FakeLayer(2,'도로'),
                              FakeLayer(3,'하천'),FakeLayer(4,'잠김',locked=True)]
                self.changes=[]
            def layers(self):return self._layers
            def apply_snapshot(self,d):self.changes.append(d)
        fake=FakeDocument()
        report=apply_rule(fake,LayerRule('test','pdf',(
            ('도로',False),('하천',False),('잠김',False),('없는 이름',True))))
        self.assertEqual((report.changed,report.ambiguous,report.locked,report.missing),(1,1,1,1))
        self.assertEqual(fake.changes,[{3:False}])

    def test_rule_rejects_duplicate_source_names_and_empty(self):
        class MockDoc:
            kind='pdf'
            def layers(self):
                class L:
                    locked=False
                    visible=True
                    name='하천'
                return [L(),L()]
        with self.assertRaises(DrawingError):
            LayerRule.from_document('broken',MockDoc())
        with DrawingDocument(self.pdf_a) as doc:
            with self.assertRaises(DrawingError):
                LayerRule.from_document('  ',doc)

    def test_store_corrupt_file_not_silently_ignored(self):
        path=self.root/'broken.json'
        path.write_text('{invalid',encoding='utf-8')
        with self.assertRaises(DrawingError):
            LayerRuleStore(path).load()
        self.assertEqual(path.read_text(encoding='utf-8'),'{invalid')

    def test_store_bad_duplicate_rules_rejected(self):
        path=self.root/'rules.json'
        path.write_text('{"presets": [{"name": "a", "kind":"pdf", "layers": '
                        '[{"name":"x", "visible":true},{"name":"x","visible":false}]}]}',
                        encoding='utf-8')
        with self.assertRaises(DrawingError):
            LayerRuleStore(path).load()

    def test_plan_unique_output_names_with_duplicate_stems(self):
        folder=self.root/'sub';folder.mkdir()
        copy=folder/'onmap01.pdf';copy.write_bytes(self.pdf_a.read_bytes())
        existing=self.out/'onmap01_레이어적용.png'
        existing.write_bytes(b'EXISTING')
        with DrawingDocument(self.pdf_a) as a, DrawingDocument(copy) as b:
            jobs=plan_exports([a,b],self.out,OutputOptions('png'))
        self.assertEqual([Path(j.target).name for j in jobs],
                         ['onmap01_레이어적용_2.png','onmap01_레이어적용_3.png'])
        self.assertEqual(existing.read_bytes(),b'EXISTING')

    def test_batch_exports_matching_per_file_visibility(self):
        input_digests=[self.sha(self.pdf_a),self.sha(self.pdf_b)]
        with DrawingDocument(self.pdf_a) as a, DrawingDocument(self.pdf_b) as b:
            a.set_visibility(a.layers()[0].key,False)
            b.set_visibility(b.layers()[1].key,False)
            jobs=plan_exports([a,b],self.out,OutputOptions('png'))
            # Snapshots must be frozen at job creation, unaffected by subsequent UI changes.
            a.set_all(True);b.set_all(True)
        seen=[]
        result=run_batch_exports(jobs,OutputOptions('png'),
                                 progress=lambda *args:seen.append(args))
        self.assertEqual(len(result.completed),2)
        self.assertEqual(result.errors,())
        self.assertFalse(result.cancelled)
        self.assertGreater(len(seen),0)
        for filename in result.completed:
            self.assertTrue(Path(filename).is_file())
            with Image.open(filename) as img:
                self.assertEqual(img.format,'PNG')
                self.assertEqual(img.size,(1667,1250))
        with Image.open(result.completed[0]) as aa, Image.open(result.completed[1]) as bb:
            self.assertIsNotNone(ImageChops.difference(aa.convert('RGB'),bb.convert('RGB')).getbbox())
        self.assertEqual([self.sha(self.pdf_a),self.sha(self.pdf_b)],input_digests)

    def test_fourteen_pdf_sheets_same_rule_separate_images(self):
        sheets=[]
        for i in range(14):
            path=self.root/f'onmap_sheet_{i:02d}.pdf'
            path.write_bytes(self.pdf_a.read_bytes())
            sheets.append(path)
        old=[self.sha(p) for p in sheets]
        docs=[DrawingDocument(path) for path in sheets]
        try:
            docs[0].set_visibility(docs[0].layers()[0].key,False)
            rule=LayerRule.from_document('온맵 통합',docs[0])
            results=[apply_rule(doc,rule) for doc in docs]
            self.assertTrue(all(r.matched==2 for r in results))
            self.assertTrue(all(not doc.layers()[0].visible for doc in docs))
            jobs=plan_exports(docs,self.out,OutputOptions('png'))
            result=run_batch_exports(jobs,OutputOptions('png'))
            self.assertEqual(len(result.completed),14)
            self.assertEqual(result.errors,())
            self.assertEqual(len({Path(x).name for x in result.completed}),14)
            for file in result.completed:
                with Image.open(file) as img:
                    self.assertEqual(img.size,(1667,1250))
        finally:
            for doc in docs:doc.close()
        self.assertEqual([self.sha(p) for p in sheets],old)

    def test_batch_continues_after_one_source_fails(self):
        with DrawingDocument(self.pdf_a) as a, DrawingDocument(self.pdf_b) as b:
            jobs=plan_exports([a,b],self.out,OutputOptions('jpg'))
        self.pdf_a.unlink()  # source removed after snapshot - explicit I/O failure.
        result=run_batch_exports(jobs,OutputOptions('jpg'))
        self.assertEqual(len(result.completed),1)
        self.assertEqual(len(result.errors),1)
        self.assertIn('onmap01',result.errors[0][0])
        with Image.open(result.completed[0]) as img:self.assertEqual(img.format,'JPEG')

    def test_batch_cancel_between_files(self):
        with DrawingDocument(self.pdf_a) as a, DrawingDocument(self.pdf_b) as b:
            jobs=plan_exports([a,b],self.out,OutputOptions('png'))
        switched=[False]
        def progress(i,total,fraction,name):
            if i>=1:switched[0]=True
        result=run_batch_exports(jobs,OutputOptions('png'),progress=progress,
                                 cancelled=lambda:switched[0])
        self.assertTrue(result.cancelled)
        self.assertEqual(len(result.completed),1)
        self.assertFalse(Path(jobs[1].target).exists())

    def test_batch_cancel_during_single_export_removes_partial(self):
        with DrawingDocument(self.pdf_a) as a:
            jobs=plan_exports([a],self.out,OutputOptions('png'))
        result=run_batch_exports(jobs,OutputOptions('png'),cancelled=lambda:True)
        self.assertEqual(result.completed,())
        self.assertTrue(result.cancelled)
        self.assertFalse(Path(jobs[0].target).exists())

    def test_no_selection_refused(self):
        with self.assertRaises(DrawingError):
            plan_exports([],self.out,OutputOptions('png'))


if __name__ == '__main__':
    unittest.main()
