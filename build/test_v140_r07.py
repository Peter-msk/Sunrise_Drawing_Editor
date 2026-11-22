"""R07 source guards, worker completion/cancellation and actual DXF preservation."""
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ezdxf
import fitz
from PIL import Image
from drawing_editor import batch_worker, cad_worker, core
from drawing_editor.batch import ExportJob, run_batch_exports
from drawing_editor.cad_selective import VisibleDXFSource
from drawing_editor.core import DrawingError, OutputOptions, source_signature
from drawing_editor.vector_export import export_vector_snapshot


class R07Stability(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.addCleanup(core.close_thread_document)
        self.root = Path(folder.name)
        self.source = self.root / 'source.pdf'
        with fitz.open() as doc:
            self.key = doc.add_ocg('ROAD')
            page = doc.new_page(width=100, height=100)
            page.draw_rect(fitz.Rect(10, 10, 90, 90), color=None, fill=(1, 0, 0), oc=self.key)
            doc.save(self.source)
        self.options = OutputOptions(resolution='custom', width=100, height=100)

    def job(self, states=None, target='out.png'):
        return ExportJob(str(self.source), {self.key: False} if states is None else states,
                         0, str(self.root / target), source_signature(self.source))

    def test_normalized_duplicate_pdf_keys_fail_closed_and_recover(self):
        states = {str(self.key): True, '0' + str(self.key): False}
        with self.assertRaisesRegex(DrawingError, 'Duplicate PDF layer key'):
            batch_worker.run_batch_exports_isolated([self.job(states)], self.options)
        self.assertFalse((self.root / 'out.png').exists())
        old = hashlib.sha256(self.source.read_bytes()).digest()
        result = batch_worker.run_batch_exports_isolated([self.job()], self.options)
        self.assertEqual(len(result.completed), 1)
        with Image.open(result.completed[0]) as image:
            self.assertEqual(image.getpixel((50, 50)), (255, 255, 255))
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), old)

    def test_duplicate_raw_json_key_rejected_before_any_output(self):
        ipc = self.root / 'ipc'; ipc.mkdir()
        data = json.dumps({'jobs': [asdict(self.job())], 'options': asdict(self.options)})
        key = '"' + str(self.key) + '": false'
        data = data.replace(key, key + ', ' + key.replace('false', 'true'))
        self.assertEqual(data.count('"' + str(self.key) + '":'), 2)
        (ipc / 'request.json').write_text(data, encoding='utf-8')
        proc = subprocess.run([sys.executable, '-m', 'drawing_editor.batch_worker', str(ipc)],
                              cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=20)
        self.assertEqual(proc.returncode, 3)
        self.assertIn('Duplicate batch request JSON key', (ipc/'result.json').read_text())
        self.assertFalse((self.root / 'out.png').exists())

    def test_batch_result_wins_exit_poll_race(self):
        class Exited:
            pid = 99999999
            def poll(self):
                # Publish exactly after the parent's initial existence check.
                if not (folder/'result.json').exists():
                    batch_worker._atomic_json(folder/'result.json', {'ok': True, 'result': {
                        'completed': [], 'errors': [], 'cancelled': True}})
                return 0
            def wait(self, timeout=None): return 0
        def start(cmd, **kwargs):
            nonlocal folder
            folder = Path(cmd[-1]); return Exited()
        folder = None
        with patch.object(batch_worker.subprocess, 'Popen', side_effect=start):
            result = batch_worker.run_batch_exports_isolated([self.job()], self.options)
        self.assertTrue(result.cancelled)
        self.assertFalse((self.root/'out.png').exists())

    def test_preview_result_wins_exit_poll_race(self):
        # Use the real session transaction but supply a deterministic exit race.
        session = cad_worker._CADSession.__new__(cad_worker._CADSession)
        session.folder = self.root; session.seq = 0; session.closed = False
        class Exited:
            calls = 0
            def poll(self):
                self.calls += 1
                if self.calls == 1: return None
                (session.folder/'response-000000001.json').write_text(json.dumps({'ok': True, 'report': {'pages': 1}}))
                return 0
        session.proc = Exited()
        with patch.object(session, 'close') as close:
            report = session.render('inspect', str(self.source), {self.key: False}, 0, (1, 1), None, None)
            close.assert_not_called()
        self.assertEqual(report, {'pages': 1})
        self.assertFalse(list(self.root.glob('request-*')))
        self.assertFalse(list(self.root.glob('response-*')))

    def test_export_without_registration_stamp_detects_mutation(self):
        target = self.root / 'out.png'
        def change(_):
            with self.source.open('ab') as f: f.write(b'\n% changed')
        with self.assertRaisesRegex(DrawingError, '원본 도면이 변경'):
            core.export_snapshot(str(self.source), {self.key: True}, 0, str(target), self.options, progress=change)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('.drawing-*')))

    def test_cad_preparation_receives_cancel_and_next_output_recovers(self):
        path = self.root/'source.dxf'
        drawing = ezdxf.new('R2013'); drawing.layers.new('ROAD')
        drawing.modelspace().add_line((0,0), (10,10), dxfattribs={'layer':'ROAD'})
        drawing.saveas(path)
        before = hashlib.sha256(path.read_bytes()).digest()
        doc = core._thread_document(str(path)); states = doc.states()
        # Same production selective stage, forced for a small deterministic fixture.
        doc._cad_selective = VisibleDXFSource(path); doc._cad = None
        stop = False
        stage = VisibleDXFSource.stage
        observed = []
        def cancel_at_stage(instance, destination, visible_layers, *, cancelled=None):
            nonlocal stop
            stop = True; observed.append(cancelled)
            return stage(instance, destination, visible_layers, cancelled=cancelled)
        job = ExportJob(str(path), states, 0, str(self.root/'cad.png'), source_signature(path))
        with patch.object(VisibleDXFSource, 'stage', cancel_at_stage):
            result = run_batch_exports([job], self.options, cancelled=lambda: stop)
        self.assertEqual(len(observed), 1); self.assertIsNotNone(observed[0])
        self.assertTrue(result.cancelled); self.assertFalse(result.errors); self.assertFalse(result.completed)
        self.assertFalse(Path(job.target).exists())
        self.assertIsNone(getattr(core._cache, 'document', None))
        result = run_batch_exports([job], self.options)
        self.assertEqual(result.completed, (job.target,)); self.assertFalse(result.errors)
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)
        self.assertFalse(list(self.root.glob('.drawing-*')))

    def test_cancel_exception_is_not_file_failure(self):
        with patch('drawing_editor.batch.export_snapshot', side_effect=InterruptedError('cancelled')):
            result = run_batch_exports([self.job()], self.options)
        self.assertTrue(result.cancelled); self.assertFalse(result.errors); self.assertFalse(result.completed)

    def test_modelspace_geometry_corruption_rejected(self):
        from ezdxf.addons import Importer
        path = self.root/'source.dxf'
        drawing = ezdxf.new('R2013'); drawing.layers.new('ROAD')
        drawing.modelspace().add_line((123456, 432100, 7), (123460, 432105, 8), dxfattribs={'layer':'ROAD'})
        drawing.saveas(path)
        before = hashlib.sha256(path.read_bytes()).digest()
        states = {layer.dxf.name: True for layer in drawing.layers}
        target = self.root/'out.dxf'
        original = Importer.import_entity
        def corrupt(importer, entity, target_layout=None):
            original(importer, entity, target_layout)
            if entity.dxftype() == 'LINE': target_layout[-1].dxf.end = (99,99,0)
        with patch.object(Importer, 'import_entity', corrupt):
            with self.assertRaisesRegex(DrawingError, '객체 데이터 불일치'):
                export_vector_snapshot(path, states, 0, target, OutputOptions(fmt='dxf'))
        self.assertFalse(target.exists()); self.assertFalse(list(self.root.glob('.drawing-*')))
        export_vector_snapshot(path, states, 0, target, OutputOptions(fmt='dxf'))
        output = ezdxf.readfile(target)
        self.assertEqual(tuple(output.modelspace()[0].dxf.end), (123460,432105,8))
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)


if __name__ == '__main__': unittest.main(verbosity=2)
