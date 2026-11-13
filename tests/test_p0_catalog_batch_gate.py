"""P0 candidate tests. Applied directly in the integrated work-branch tests/ directory.

Run: python -m unittest discover -s tests -p "test_p0_catalog_batch_gate.py" -v
These tests validate the batch gate at runtime and the Qt source-generation contract.
They do not prove Windows 421MiB DXF -> PDF handoff.
"""
from pathlib import Path
import ast
import unittest
from unittest.mock import patch

from drawing_editor.batch import ExportJob, run_batch_exports
from drawing_editor.core import OutputOptions


class _Gate:
    def __init__(self, wait_once=False):
        self.held = False
        self.acquires = 0
        self.releases = 0
        self.wait_once = wait_once

    def acquire(self, timeout):
        self.acquires += 1
        if self.wait_once:
            self.wait_once = False
            return False
        assert not self.held
        self.held = True
        return True

    def release(self):
        assert self.held
        self.held = False
        self.releases += 1


class BatchMuPDFGateTest(unittest.TestCase):
    def test_release_between_successive_files(self):
        gate = _Gate()
        observed = []
        jobs = [ExportJob('a.dxf', {}, 0, 'a.png'),
                ExportJob('b.pdf', {}, 0, 'b.png')]
        def save(source, states, page_index, target, options, **kwargs):
            observed.append((source, gate.acquires, gate.releases))
            return target
        with patch('drawing_editor.batch.export_snapshot', side_effect=save):
            result = run_batch_exports(jobs, OutputOptions(), render_gate=gate)
        self.assertEqual(result.completed, ('a.png', 'b.png'))
        self.assertEqual(observed, [('a.dxf', 1, 0), ('b.pdf', 2, 1)])
        self.assertEqual(gate.acquires, gate.releases)
        self.assertFalse(gate.held)

    def test_gate_released_after_failed_file(self):
        gate = _Gate()
        jobs = [ExportJob('bad.dxf', {}, 0, 'a.png'),
                ExportJob('good.pdf', {}, 0, 'b.png')]
        def save(source, states, page_index, target, options, **kwargs):
            if source == 'bad.dxf':
                raise RuntimeError('synthetic export failure')
            return target
        with patch('drawing_editor.batch.export_snapshot', side_effect=save):
            result = run_batch_exports(jobs, OutputOptions(), render_gate=gate)
        self.assertEqual(result.completed, ('b.png',))
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(gate.acquires, gate.releases)

    def test_cancel_while_waiting_for_gate(self):
        gate = _Gate(wait_once=True)
        cancelled = lambda: gate.acquires > 0
        job = ExportJob('a.dxf', {}, 0, 'a.png')
        with patch('drawing_editor.batch.export_snapshot') as save:
            result = run_batch_exports([job], OutputOptions(),
                                       cancelled=cancelled, render_gate=gate)
        self.assertTrue(result.cancelled)
        self.assertEqual(gate.releases, 0)
        save.assert_not_called()


class CatalogGenerationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).resolve().parents[1] /
                      'drawing_editor' / 'window.py').read_text('utf-8')

    def test_success_requires_latest_registration(self):
        self.assertIn('expected_path != path or self._catalog_latest.get(path) != seq',
                      self.source)

    def test_error_requires_latest_registration(self):
        self.assertIn('path is None or self._catalog_latest.get(path) != seq',
                      self.source)

    def test_removed_registration_cancels_queued_catalog(self):
        self.assertIn('event = self._catalog_cancellations.pop(key, None)', self.source)
        self.assertIn('event.set()', self.source)

    def test_pdf_gate_wait_is_cancellable(self):
        self.assertIn('while not _MUPDF_GATE.acquire(timeout=0.15):', self.source)
        self.assertIn("raise InterruptedError('등록 취소')", self.source)


if __name__ == '__main__':
    unittest.main()
