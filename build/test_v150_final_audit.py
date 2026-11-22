"""R05 -> final source audit: real restart and path-safety regressions."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from drawing_editor.automation import BatchSession, discover_drawings
from drawing_editor.batch import ExportJob, BatchResult, plan_exports
from drawing_editor.core import DrawingError, OutputOptions, source_signature
from drawing_editor.state import DrawingState


class FinalAuditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.src = self.root/'src'; self.src.mkdir()
        self.dst = self.root/'dst'; self.dst.mkdir()
        self.opts = OutputOptions(fmt='png', resolution='custom', width=100, height=100)

    def _job(self, rel):
        source = self.src/'a.pdf'
        source.touch() if not source.exists() else None
        return ExportJob(str(source), {}, 0, str(self.dst/rel), source_signature(source))

    def test_duplicate_basename_legacy_error_is_not_assigned_to_wrong_job(self):
        first, second = self._job('a/drawing.png'), self._job('b/drawing.png')
        Path(first.target).parent.mkdir(parents=True)
        Path(second.target).parent.mkdir(parents=True)
        session = BatchSession((first,second),self.opts)
        session.record((first,second), BatchResult((),(('drawing.png','unknown filename'),),False))
        self.assertFalse(session._errors)
        self.assertEqual(session.report()['jobs'][0]['status'], 'pending')
        self.assertEqual(session.report()['jobs'][1]['status'], 'pending')

    def test_exact_paths_attribute_errors_to_matching_output(self):
        first, second = self._job('a/drawing.png'), self._job('b/drawing.png')
        session = BatchSession((first,second),self.opts)
        session.record((first,second),BatchResult((),((first.target,'first failed'),),False))
        self.assertEqual(session._errors, {first.target:'first failed'})

    def test_persistent_error_reason_retained_after_restart(self):
        job = self._job('out.png')
        session=BatchSession((job,),self.opts)
        session.record((job,),BatchResult((),((job.target,'disk full'),),False))
        checkpoint=self.root/'last.json'
        session.save_checkpoint(checkpoint)
        obj=json.loads(checkpoint.read_text())
        self.assertEqual(obj['schema_version'],3)
        restored=BatchSession.load_checkpoint(checkpoint)
        self.assertEqual(restored.report()['jobs'][0]['status'],'failed')
        self.assertEqual(restored.report()['jobs'][0]['error'],'disk full')

    def test_previous_v2_checkpoint_is_still_readable(self):
        job=self._job('out.png')
        session=BatchSession((job,),self.opts)
        data=session.checkpoint_payload()
        data['schema_version']=2
        del data['errors']
        checkpoint=self.root/'old.json'
        checkpoint.write_text(json.dumps(data))
        self.assertEqual(len(BatchSession.load_checkpoint(checkpoint).retry_plan()[0]),1)

    def test_malicious_v3_error_record_is_rejected(self):
        job=self._job('out.png')
        session=BatchSession((job,),self.opts)
        data=session.checkpoint_payload()
        data['errors']=[[str(self.root/'different'), 'no']]
        checkpoint=self.root/'last.json';checkpoint.write_text(json.dumps(data))
        with self.assertRaises(DrawingError):BatchSession.load_checkpoint(checkpoint)

    def test_folder_search_rejects_symlink_root(self):
        link=self.root/'shortcut'
        try:link.symlink_to(self.src,target_is_directory=True)
        except (OSError,NotImplementedError) as exc:self.skipTest(str(exc))
        with self.assertRaises(DrawingError):discover_drawings(link,recursive=True)

    def test_project_folder_rejects_symlinked_drawing(self):
        target=self.root/'outside.pdf';target.write_bytes(b'%PDF-1.7')
        link=self.src/'link.pdf'
        try:link.symlink_to(target)
        except (OSError,NotImplementedError) as exc:self.skipTest(str(exc))
        doc=DrawingState(link)
        with self.assertRaises(DrawingError):plan_exports([doc],self.dst,self.opts,source_root=self.src)

    def test_project_folder_rejects_symlinked_subfolder(self):
        other=self.root/'other';other.mkdir()
        source=other/'drawing.pdf';source.write_bytes(b'%PDF-1.7')
        link=self.src/'shortcut'
        try:link.symlink_to(other,target_is_directory=True)
        except (OSError,NotImplementedError) as exc:self.skipTest(str(exc))
        doc=DrawingState(link/'drawing.pdf')
        with self.assertRaises(DrawingError):plan_exports([doc],self.dst,self.opts,source_root=self.src)

    def test_no_new_editing_or_color_tools(self):
        core=(Path(__file__).resolve().parents[1]/'drawing_editor'/'layer_tools_ui.py').read_text()
        self.assertNotIn('DXF 레이어 색상 변경',core)


if __name__=='__main__':
    unittest.main()
