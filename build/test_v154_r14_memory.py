"""R14 isolated CAD batch resource lifetime; real DXF fixture."""
import gc
import json
import tempfile
import unittest
import weakref
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import ezdxf
import fitz
from drawing_editor import batch, batch_worker, core


class CadWorkerLifetimeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(core.close_thread_document)
        self.root = Path(tmp.name).resolve()
        self.cad = self.root / 'cad.dxf'
        self.pdf = self.root / 'map.pdf'
        drawing = ezdxf.new('R2013')
        drawing.modelspace().add_line((0, 0), (20, 20))
        drawing.saveas(self.cad)
        with fitz.open() as doc:
            doc.new_page(width=100, height=100).draw_line((0, 0), (90, 90))
            doc.save(self.pdf)
        self.options = core.OutputOptions(resolution='custom', width=100, height=100)

    def prepare(self, sources):
        jobs = []
        for i, source in enumerate(sources):
            with core.DrawingDocument(source) as doc:
                states = doc.states()
            jobs.append(dict(source=str(source), states=states, page_index=0,
                             target=str(self.root / f'{i}.png'),
                             source_signature=core.source_signature(source)))
        (self.root / 'request.json').write_text(json.dumps(dict(options=asdict(self.options), jobs=jobs)))
        return jobs

    def test_cad_cycle_reclaimed_before_next_source_and_same_source_reused(self):
        jobs = self.prepare([self.cad, self.cad, self.pdf])
        original = batch.export_snapshot
        references = []
        gc.collect()
        was_enabled = gc.isenabled()
        gc.disable()  # deterministic reproduction: no automatic cyclic collection
        def observed(*args, **kwargs):
            if len(references) == 2:
                self.assertTrue((self.root / 'receipt-1.json').is_file())
                self.assertIsNone(references[0](), 'retired CAD graph survived source boundary')
            result = original(*args, **kwargs)
            if Path(args[0]) == self.cad:
                references.append(weakref.ref(core._cache.document._cad))
                if len(references) == 2:
                    self.assertIs(references[0](), references[1]())
                    self.assertIsNotNone(references[0]())
            return result
        try:
            with patch.object(batch, 'export_snapshot', observed):
                self.assertEqual(batch_worker.worker_main([str(self.root)]), 0)
            payload = json.loads((self.root / 'result.json').read_text())['result']
            self.assertEqual(payload['completed'], [j['target'] for j in jobs], payload)
            self.assertFalse(payload['errors'], payload)
        finally:
            if was_enabled:
                gc.enable()
            core.close_thread_document()
            gc.collect()

    def test_last_cad_job_releases_graph_after_receipt(self):
        self.prepare([self.cad])
        original = batch.export_snapshot
        references = []
        def observed(*args, **kwargs):
            result = original(*args, **kwargs)
            references.append(weakref.ref(core._cache.document._cad))
            return result
        with patch.object(batch, 'export_snapshot', observed):
            self.assertEqual(batch_worker.worker_main([str(self.root)]), 0)
        self.assertTrue((self.root / 'receipt-0.json').is_file())
        self.assertIsNone(references[0]())
        self.assertIsNone(getattr(core._cache, 'document', None))


if __name__ == '__main__':
    unittest.main()
