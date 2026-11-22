"""v1.5.0 completion: restart-safe batch, folder structure and failure isolation."""
from pathlib import Path
import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz
from PIL import Image
from drawing_editor.automation import BatchSession
from drawing_editor.batch import plan_exports, prepare_output_folders
from drawing_editor.batch_worker import run_batch_exports_isolated
from drawing_editor.core import DrawingError, OutputOptions, LayerInfo
from drawing_editor.state import DrawingState


class FinishTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.src=self.root/'source';self.src.mkdir()
        self.output=self.root/'results';self.output.mkdir()
        self.opts=OutputOptions(fmt='png',resolution='custom',width=100,height=100)
        self.checkpoint=self.root/'session.json'

    def pdf(self, rel):
        path=self.src/rel;path.parent.mkdir(parents=True,exist_ok=True)
        with fitz.open() as doc:
            visible=doc.add_ocg('ROAD');invisible=doc.add_ocg('WATER')
            pg=doc.new_page(width=100,height=100)
            pg.draw_rect(fitz.Rect(10,10,45,90),fill=(0,0,1),color=None,oc=visible)
            pg.draw_rect(fitz.Rect(55,10,90,90),fill=(1,0,0),color=None,oc=invisible)
            doc.save(path)
        state=DrawingState(path)
        state.load_metadata([LayerInfo(visible,'ROAD',True),LayerInfo(invisible,'WATER',True)],1)
        state.set_visibility(invisible,False)
        return state

    def test_restart_real_output_and_retry_uses_original_states(self):
        docs=[self.pdf('a/drawing.pdf'),self.pdf('b/drawing.pdf')]
        before=[hashlib.sha256(d.path.read_bytes()).hexdigest() for d in docs]
        jobs=plan_exports(docs,self.output,self.opts,source_root=self.src)
        self.assertEqual(len({j.target for j in jobs}),2)
        self.assertEqual([Path(j.target).parent.name for j in jobs],['a','b'])
        prepare_output_folders(jobs,self.output)
        session=BatchSession(tuple(jobs),self.opts)
        session.save_checkpoint(self.checkpoint)
        # Crash simulation: a completed file exists but no result acknowledgement.
        collision=Path(jobs[1].target);collision.write_bytes(b'not a valid image')
        response=run_batch_exports_isolated(jobs,self.opts)
        self.assertEqual(len(response.completed),1)
        self.assertEqual(len(response.errors),1)
        session.record(jobs,response)
        old=Path(jobs[0].target).read_bytes()
        session.save_checkpoint(self.checkpoint)
        restored=BatchSession.load_checkpoint(self.checkpoint)
        self.assertEqual(len(restored.retry_plan()[1]),1)
        collision.unlink()
        remaining,blocked=restored.retry_plan()
        self.assertFalse(blocked)
        self.assertEqual(tuple(j.target for j in remaining),(jobs[1].target,))
        docs[1].set_all(True)
        response=run_batch_exports_isolated(remaining,restored.options)
        restored.record(remaining,response)
        self.assertEqual(restored.retry_plan(),((),()))
        self.assertEqual(Path(jobs[0].target).read_bytes(),old)
        for job in jobs:
            with Image.open(job.target) as pic:
                self.assertEqual(pic.getpixel((25,50)),(0,0,255))
                self.assertEqual(pic.getpixel((75,50)),(255,255,255))
        self.assertEqual(before,[hashlib.sha256(d.path.read_bytes()).hexdigest() for d in docs])

    def test_unacknowledged_output_never_marked_success_after_restore(self):
        doc=self.pdf('a.pdf');jobs=plan_exports([doc],self.output,self.opts)
        session=BatchSession(tuple(jobs),self.opts)
        session.save_checkpoint(self.checkpoint)
        Path(jobs[0].target).write_bytes(b'unknown after crash')
        recovered=BatchSession.load_checkpoint(self.checkpoint)
        self.assertEqual(recovered.retry_plan()[0],())
        self.assertEqual(len(recovered.retry_plan()[1]),1)
        self.assertEqual(recovered.report()['jobs'][0]['status'],'blocked')

    def test_completed_deleted_does_not_auto_reexport(self):
        doc=self.pdf('a.pdf');jobs=plan_exports([doc],self.output,self.opts)
        session=BatchSession(tuple(jobs),self.opts)
        result=run_batch_exports_isolated(jobs,self.opts);session.record(jobs,result)
        session.save_checkpoint(self.checkpoint)
        Path(jobs[0].target).unlink()
        recovered=BatchSession.load_checkpoint(self.checkpoint)
        self.assertEqual(recovered.retry_plan(),((),()))

    def test_tampered_keys_and_bools_rejected(self):
        doc=self.pdf('a.pdf'); jobs=plan_exports([doc],self.output,self.opts)
        BatchSession(tuple(jobs),self.opts).save_checkpoint(self.checkpoint)
        original=self.checkpoint.read_text()
        self.checkpoint.write_text(original.replace('"schema_version":3', '"schema_version":3,"schema_version":3'))
        with self.assertRaises(DrawingError):BatchSession.load_checkpoint(self.checkpoint)
        data=json.loads(original)
        data['jobs'][0]['states'][0][1]='false'
        self.checkpoint.write_text(json.dumps(data))
        with self.assertRaises(DrawingError):BatchSession.load_checkpoint(self.checkpoint)

    def test_tampered_source_and_options_rejected(self):
        doc=self.pdf('a.pdf');jobs=plan_exports([doc],self.output,self.opts)
        BatchSession(tuple(jobs),self.opts).save_checkpoint(self.checkpoint)
        original=json.loads(self.checkpoint.read_text())
        data=dict(original);data['jobs']=[dict(original['jobs'][0],source='relative.pdf')]
        self.checkpoint.write_text(json.dumps(data))
        with self.assertRaises(DrawingError):BatchSession.load_checkpoint(self.checkpoint)
        data=dict(original);data['options']=dict(original['options'],fmt='exe')
        self.checkpoint.write_text(json.dumps(data))
        with self.assertRaises(DrawingError):BatchSession.load_checkpoint(self.checkpoint)

    def test_duplicate_targets_rejected_but_same_basename_in_other_folders_allowed(self):
        docs=[self.pdf('a/drawing.pdf'),self.pdf('b/drawing.pdf')]
        jobs=plan_exports(docs,self.output,self.opts,source_root=self.src)
        self.assertEqual(len(BatchSession(tuple(jobs),self.opts).jobs),2)
        with self.assertRaises(DrawingError):BatchSession((jobs[0], jobs[0]),self.opts)

    def test_source_outside_explicit_project_folder_rejected(self):
        doc=self.pdf('a.pdf'); outsider=self.root/'other';outsider.mkdir()
        with self.assertRaises(DrawingError):plan_exports([doc],self.output,self.opts,source_root=outsider)

    def test_symlink_parent_is_not_followed(self):
        doc=self.pdf('sub/a.pdf');jobs=plan_exports([doc],self.output,self.opts,source_root=self.src)
        outside=self.root/'other';outside.mkdir()
        try:(self.output/'sub').symlink_to(outside,target_is_directory=True)
        except OSError as exc:self.skipTest(str(exc))
        with self.assertRaises(DrawingError):prepare_output_folders(jobs,self.output)
        self.assertFalse(list(outside.iterdir()))

    def test_target_parent_escape_rejected(self):
        doc=self.pdf('sub/a.pdf');jobs=plan_exports([doc],self.output,self.opts,source_root=self.src)
        with self.assertRaises(DrawingError):prepare_output_folders(jobs,self.src)

    def test_atomic_checkpoint_over_symlink_preserves_target(self):
        doc=self.pdf('a.pdf');jobs=plan_exports([doc],self.output,self.opts)
        other=self.root/'protected.json';other.write_bytes(b'keep')
        try:self.checkpoint.symlink_to(other)
        except OSError as exc:self.skipTest(str(exc))
        BatchSession(tuple(jobs),self.opts).save_checkpoint(self.checkpoint)
        self.assertEqual(other.read_bytes(),b'keep')
        self.assertFalse(self.checkpoint.is_symlink())
        self.assertEqual(BatchSession.load_checkpoint(self.checkpoint).attempts,0)

    def test_checkpoint_limit_does_not_damage_previous(self):
        doc=self.pdf('a.pdf');jobs=plan_exports([doc],self.output,self.opts)
        session=BatchSession(tuple(jobs),self.opts)
        session.save_checkpoint(self.checkpoint)
        old=self.checkpoint.read_bytes()
        with patch('drawing_editor.automation.MAX_CHECKPOINT_BYTES',100):
            with self.assertRaises(DrawingError):session.save_checkpoint(self.checkpoint)
        self.assertEqual(self.checkpoint.read_bytes(),old)

    def test_checkpoint_bad_completed_list_rejected(self):
        doc=self.pdf('a.pdf');jobs=plan_exports([doc],self.output,self.opts)
        session=BatchSession(tuple(jobs),self.opts)
        data=session.checkpoint_payload();data['completed']=[str(self.root/'random.png')]
        self.checkpoint.write_text(json.dumps(data))
        with self.assertRaises(DrawingError):BatchSession.load_checkpoint(self.checkpoint)

# Separate class for the independent release trust contract.
class ReleaseTrustPolicy(unittest.TestCase):
    def test_v150_official_activation_rejects_selfsigned_even_with_matching_hash(self):
        from build.approve_update import approved_metadata
        with self.assertRaisesRegex(ValueError, '신뢰 서명'):
            approved_metadata({}, {}, version='1.5.0', old_version='1.4.0',
                              sha='a'*64, size=1,
                              signature_trust='SELF_SIGNED_UNTRUSTED_TEST_ONLY')

    def test_legacy_trust_contract_not_silently_rewritten(self):
        from build.approve_update import approved_metadata
        with self.assertRaises(ValueError) as cm:
            approved_metadata({}, {}, version='1.1.0', old_version='1.0.0',
                              sha='a'*64, size=1,
                              signature_trust='SELF_SIGNED_UNTRUSTED_TEST_ONLY')
        self.assertNotIn('신뢰 서명',str(cm.exception))


if __name__ == "__main__":
    unittest.main()
