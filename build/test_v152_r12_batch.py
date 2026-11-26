"""R12: real child cancellation, completion receipts and checkpoint bounds."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import fitz
from drawing_editor import batch_worker
from drawing_editor.automation import BatchSession
from drawing_editor.batch import ExportJob
from drawing_editor.core import OutputOptions, source_signature

ROOT = Path(__file__).resolve().parents[1]

class BatchRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / 'source.pdf'
        with fitz.open() as pdf:
            page = pdf.new_page(width=100, height=100)
            page.draw_rect(fitz.Rect(10,10,90,90), fill=(1,0,0))
            pdf.save(self.source)
        self.digest = hashlib.sha256(self.source.read_bytes()).digest()
        self.opts = OutputOptions(resolution='custom', width=100, height=100)
        self.jobs = tuple(ExportJob(str(self.source), {}, 0, str(self.root / f'{i}.png'),
                                    source_signature(self.source)) for i in range(3))

    def test_forced_cancel_recovers_only_acknowledged_outputs(self):
        # Real subprocess and real first export. The second job simulates a
        # native call that does not respond to cancellation, plus an unknown
        # target and a PID-tagged partial. Parent must reap and clean up.
        script = '''import os, sys, time\nfrom pathlib import Path\nfrom drawing_editor import batch, batch_worker\noriginal = batch.export_snapshot\ndef slow(*args, **kwargs):\n    if Path(args[3]).name == '1.png':\n        Path(args[3]).write_bytes(b'unknown')\n        Path(args[3]).with_name(f'.drawing-{os.getpid()}-partial.png').write_bytes(b'partial')\n        Path(args[3]).with_name('ready').touch()\n        time.sleep(60)\n    return original(*args, **kwargs)\nbatch.export_snapshot = slow\nraise SystemExit(batch_worker.worker_main([sys.argv[1]]))\n'''
        def command(folder):
            return [sys.executable, '-c', script, str(folder)], {'cwd': str(ROOT)}
        started = time.monotonic()
        with patch.object(batch_worker, '_command', command), patch.object(batch_worker, '_CANCEL_GRACE_SECONDS', .2):
            result = batch_worker.run_batch_exports_isolated(self.jobs, self.opts,
                cancelled=lambda: (self.root/'ready').exists() or time.monotonic()-started > 8)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.completed, (self.jobs[0].target,))
        self.assertEqual(Path(self.jobs[1].target).read_bytes(), b'unknown')
        self.assertFalse(list(self.root.glob('.drawing-*-partial.png')))
        session = BatchSession(self.jobs, self.opts); session.record(self.jobs, result)
        checkpoint = self.root/'checkpoint.json'; session.save_checkpoint(checkpoint)
        restored = BatchSession.load_checkpoint(checkpoint)
        eligible, blocked = restored.retry_plan()
        self.assertEqual(eligible, (self.jobs[2],))
        self.assertEqual([x[0] for x in blocked], [self.jobs[1].target])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), self.digest)

    def test_worker_error_record_is_reloadable(self):
        session = BatchSession(self.jobs, self.opts)
        session.record(self.jobs, error='x'*21000)
        checkpoint = self.root/'checkpoint.json'; session.save_checkpoint(checkpoint)
        self.assertEqual(len(BatchSession.load_checkpoint(checkpoint).worker_error), 20000)

    def test_receipts_are_bound_to_planned_job_and_shape(self):
        folder = self.root/'ipc'; folder.mkdir()
        Path(self.jobs[1].target).write_bytes(b'confirmed')
        (folder/'receipt-0.json').write_text(json.dumps({'completed': self.jobs[1].target}))
        (folder/'receipt-1.json').write_text(json.dumps({'completed': self.jobs[1].target}))
        (folder/'receipt-2.json').write_text(json.dumps({'error': 'broken'}))
        (folder/'receipt-99.json').write_text(json.dumps({'completed': 'unknown'}))
        result = batch_worker._cancelled_result(folder, self.jobs)
        self.assertEqual(result.completed, (self.jobs[1].target,))
        self.assertEqual(result.errors, ((self.jobs[2].target, 'broken'),))
        self.assertTrue(result.cancelled)

if __name__ == '__main__': unittest.main()
