"""R13: unexpected child failure, output path protection, recovery state."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import fitz
from drawing_editor import batch_worker
from drawing_editor.automation import BatchSession
from drawing_editor.batch import ExportJob, run_batch_exports
from drawing_editor.core import OutputOptions, source_signature, close_thread_document

ROOT = Path(__file__).resolve().parents[1]


class UnexpectedRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.addCleanup(close_thread_document)
        self.root = Path(tmp.name).resolve()
        self.source = self.root / 'source.pdf'
        with fitz.open() as pdf:
            page = pdf.new_page(width=100, height=100)
            page.draw_rect(fitz.Rect(10, 10, 90, 90), fill=(1, 0, 0))
            pdf.save(self.source)
        self.digest = hashlib.sha256(self.source.read_bytes()).digest()
        self.opts = OutputOptions(resolution='custom', width=100, height=100)
        self.jobs = tuple(ExportJob(str(self.source), {}, 0, str(self.root / f'{i}.png'),
                                    source_signature(self.source)) for i in range(3))

    def test_unexpected_exit_recovers_confirmed_jobs_and_reports_failure(self):
        # A real first export, then abrupt process death (not user cancellation).
        script = '''import os, sys\nfrom pathlib import Path\nfrom drawing_editor import batch, batch_worker\noriginal = batch.export_snapshot\ndef crash(*args, **kwargs):\n    if Path(args[3]).name == '1.png':\n        Path(args[3]).write_bytes(b'unknown')\n        Path(args[3]).with_name(f'.drawing-{os.getpid()}-partial.png').write_bytes(b'partial')\n        os._exit(17)\n    return original(*args, **kwargs)\nbatch.export_snapshot = crash\nraise SystemExit(batch_worker.worker_main([sys.argv[1]]))\n'''
        def command(folder):
            return [sys.executable, '-c', script, str(folder)], {'cwd': str(ROOT)}
        with patch.object(batch_worker, '_command', command):
            result = batch_worker.run_batch_exports_isolated(self.jobs, self.opts)
        self.assertFalse(result.cancelled)
        self.assertIn('17', result.worker_error)
        self.assertEqual(result.completed, (self.jobs[0].target,))
        self.assertEqual(Path(self.jobs[1].target).read_bytes(), b'unknown')
        self.assertFalse(list(self.root.glob('.drawing-*-partial.png')))
        session = BatchSession(self.jobs, self.opts); session.record(self.jobs, result)
        checkpoint = self.root / 'checkpoint.json'; session.save_checkpoint(checkpoint)
        restored = BatchSession.load_checkpoint(checkpoint)
        self.assertEqual(restored.last_status, 'worker_error')
        self.assertEqual(restored.worker_error, result.worker_error)
        eligible, blocked = restored.retry_plan()
        self.assertEqual(eligible, (self.jobs[2],))
        self.assertEqual([x[0] for x in blocked], [self.jobs[1].target])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), self.digest)

    def test_worker_error_response_after_receipt_is_not_full_success(self):
        script = '''import sys\nfrom pathlib import Path\nfrom drawing_editor import batch, batch_worker\noriginal = batch.run_batch_exports\ndef fail(*args, **kwargs):\n    original(args[0][:1], args[1], **kwargs)\n    raise RuntimeError('simulated worker fault')\nbatch.run_batch_exports = fail\nraise SystemExit(batch_worker.worker_main([sys.argv[1]]))\n'''
        def command(folder):
            return [sys.executable, '-c', script, str(folder)], {'cwd': str(ROOT)}
        with patch.object(batch_worker, '_command', command):
            result = batch_worker.run_batch_exports_isolated(self.jobs, self.opts)
        self.assertEqual(result.completed, (self.jobs[0].target,))
        self.assertFalse(result.cancelled)
        self.assertIn('simulated worker fault', result.worker_error)

    def test_changed_output_parent_is_not_followed(self):
        dest = self.root / 'planned'; dest.mkdir()
        elsewhere = self.root / 'elsewhere'; elsewhere.mkdir()
        job = ExportJob(str(self.source), {}, 0, str(dest/'out.png'), source_signature(self.source))
        dest.rmdir()
        try:
            dest.symlink_to(elsewhere, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f'symlink unavailable: {exc}')
        result = run_batch_exports((job, self.jobs[0]), self.opts)
        self.assertEqual(result.completed, (self.jobs[0].target,))
        self.assertEqual(result.errors[0][0], job.target)
        self.assertFalse((elsewhere/'out.png').exists())

    def test_changed_parent_receipt_is_not_recovered(self):
        dest = self.root / 'planned'; dest.mkdir()
        elsewhere = self.root / 'elsewhere'; elsewhere.mkdir()
        job = ExportJob(str(self.source), {}, 0, str(dest/'out.png'), source_signature(self.source))
        folder = self.root / 'ipc'; folder.mkdir()
        (folder/'receipt-0.json').write_text(json.dumps({'completed': job.target}))
        (elsewhere/'out.png').write_bytes(b'unrelated')
        dest.rmdir()
        try:
            dest.symlink_to(elsewhere, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f'symlink unavailable: {exc}')
        result = batch_worker._cancelled_result(folder, (job,))
        self.assertFalse(result.completed)
        self.assertEqual((elsewhere/'out.png').read_bytes(), b'unrelated')

if __name__ == '__main__': unittest.main()
