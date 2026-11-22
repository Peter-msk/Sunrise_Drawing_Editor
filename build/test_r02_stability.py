"""Targeted R02 regression tests with real PDF output and offline worker faults."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz
from PIL import Image, ImageChops
from drawing_editor import batch_worker, trim, tiles
from drawing_editor.batch import plan_exports, run_batch_exports
from drawing_editor.core import DrawingDocument, DrawingError, OutputOptions, export_snapshot, source_signature, close_thread_document
from drawing_editor.layer_tools import plan_advanced_exports, classify
from drawing_editor.state import DrawingState


class StabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(close_thread_document)
        self.root = Path(self.temp.name)
        self.path = self.root / 'source.pdf'
        self.opts = OutputOptions(resolution='custom', width=200, height=200)
        self.make_pdf(self.path)

    def make_pdf(self, path):
        with fitz.open() as doc:
            layer = doc.add_ocg('ROAD')
            for i in range(2):
                page = doc.new_page(width=100, height=100)
                page.draw_rect(fitz.Rect(10+i, 10, 80, 80), color=None, fill=(1,0,0), oc=layer)
            doc.save(path)

    def state(self):
        state = DrawingState(self.path)
        with DrawingDocument(self.path) as doc:
            state.load_metadata(doc.layers(), doc.pages)
        return state

    def test_stale_catalog_rejects_both_planners(self):
        state = self.state()
        with self.path.open('ab') as f: f.write(b'\n% changed')
        for planner in (plan_exports, plan_advanced_exports):
            with self.assertRaisesRegex(DrawingError, '원본 도면이 변경'):
                planner([state], self.root, self.opts)

    def test_change_after_plan_isolated_worker_no_output(self):
        jobs = plan_advanced_exports([self.state()], self.root, self.opts, scope='all')
        with self.path.open('ab') as f: f.write(b'\n% changed')
        result = batch_worker.run_batch_exports_isolated(jobs, self.opts)
        self.assertEqual(len(result.errors), 2)
        self.assertFalse(result.completed)
        self.assertFalse(any(Path(j.target).exists() for j in jobs))

    def test_change_during_render_prevents_publication(self):
        job = plan_advanced_exports([self.state()], self.root, self.opts)[0]
        def mutate(_):
            with self.path.open('ab') as f: f.write(b'\n% changed')
        with self.assertRaisesRegex(DrawingError, '원본 도면이 변경'):
            export_snapshot(job.source, job.states, job.page_index, job.target,
                            self.opts, progress=mutate, expected_source=job.source_signature)
        self.assertFalse(Path(job.target).exists())
        self.assertFalse(list(self.root.glob('.drawing-*')))

    def test_invalid_snapshot_and_page_no_output(self):
        target = self.root/'bad.png'
        stamp = source_signature(self.path)
        for states, page in (({}, 0), (self.state().states(), 2)):
            with self.assertRaises(DrawingError):
                export_snapshot(str(self.path), states, page, str(target), self.opts, expected_source=stamp)
            self.assertFalse(target.exists())

    def test_collision_after_plan_preserved_and_other_job_completes(self):
        jobs = plan_advanced_exports([self.state()], self.root, self.opts, scope='all')
        target = Path(jobs[0].target);target.write_bytes(b'user data')
        result = run_batch_exports(jobs, self.opts)
        self.assertEqual(target.read_bytes(), b'user data')
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.completed, (jobs[1].target,))

    def test_progress_failure_nonfatal(self):
        folder = self.root/'work';folder.mkdir()
        jobs = plan_advanced_exports([self.state()], self.root, self.opts, scope='all')
        from dataclasses import asdict
        (folder/'request.json').write_text(json.dumps({'jobs':[asdict(j) for j in jobs], 'options':asdict(self.opts)}))
        atomic = batch_worker._atomic_json
        def fail_progress(path, payload):
            if path.name == 'progress.json': raise PermissionError('simulated sharing violation')
            return atomic(path,payload)
        with patch.object(batch_worker, '_atomic_json', side_effect=fail_progress):
            self.assertEqual(batch_worker.worker_main([str(folder)]), 0)
        result = json.loads((folder/'result.json').read_text())['result']
        self.assertEqual(len(result['completed']),2)
        self.assertFalse(result['errors'])

    def test_number_allocator_keeps_sparse_collision_order(self):
        state = self.state()
        for suffix in ('', '_2', '_4'):
            (self.root/f'SOURCE_P0001{suffix}.PNG').touch()
        jobs = plan_advanced_exports([state]*3, self.root, self.opts)
        self.assertEqual([Path(j.target).name for j in jobs],
                         ['source_p0001_3.png','source_p0001_5.png','source_p0001_6.png'])

    def test_transparency_crop_matches_reference_and_skips_color(self):
        with fitz.open() as pdf:
            page = pdf.new_page(width=100,height=100)
            page.draw_rect(fitz.Rect(20,20,80,80), color=None, fill=(1,0,0))
            with patch.object(trim,'_colored_bbox', wraps=trim._colored_bbox) as color:
                bbox = trim.find_content_crop(page, 600, 600, transparent=True)
                self.assertEqual(bbox,(120,120,480,480));self.assertEqual(color.call_count,0)
                output=io.BytesIO()
                trim.save_png_tiled_crop_single_pass(page,output,600,600,300,scratch_dir=self.root,transparent=True)
                self.assertEqual(color.call_count,0)
            with Image.open(io.BytesIO(output.getvalue())) as image:
                self.assertEqual(image.size,(360,360));self.assertEqual(image.getpixel((100,100)),(255,0,0,255))
            # Opaque white-painted page still uses color bounds, including RGBA.
            page2=pdf.new_page(width=100,height=100)
            page2.draw_rect(page2.rect,color=None,fill=(1,1,1))
            page2.draw_rect(fitz.Rect(20,20,80,80),color=None,fill=(1,0,0))
            self.assertEqual(trim.find_content_crop(page2,600,600,transparent=True),(120,120,480,480))

    def test_classification_all_tokens_and_conflict(self):
        from drawing_editor.layer_tools import GROUPS, UNKNOWN
        for group, tokens in GROUPS.items():
            for token in tokens:
                self.assertEqual(classify(f'A_{token}_01'), group)
        self.assertEqual(classify('ROAD_TREE'), UNKNOWN)
        self.assertEqual(classify('BROADER'), UNKNOWN)

    def test_cancel_after_first_preserves_completed_only(self):
        jobs=plan_advanced_exports([self.state()],self.root,self.opts,scope='all')
        result=run_batch_exports(jobs,self.opts,cancelled=lambda:Path(jobs[0].target).exists())
        self.assertTrue(result.cancelled);self.assertEqual(result.completed,(jobs[0].target,))
        self.assertFalse(Path(jobs[1].target).exists())

    def test_translucent_png_straight_alpha(self):
        with fitz.open() as pdf:
            page=pdf.new_page(width=100,height=100)
            page.draw_rect(fitz.Rect(10,10,90,90),color=None,fill=(1,0,0),fill_opacity=.5)
            page.draw_circle(fitz.Point(50,50),20,color=None,fill=(.3,.7,.4),fill_opacity=.6)
            native=Image.open(io.BytesIO(page.get_pixmap(alpha=True).tobytes('png')))
            output=io.BytesIO();tiles.save_png_tiled(page,output,100,100,72,transparent=True)
            with native, Image.open(io.BytesIO(output.getvalue())) as tiled:
                self.assertEqual(tiled.getpixel((20,20)),(255,0,0,126))
                self.assertEqual(ImageChops.difference(native,tiled).getextrema()[3],(0,0))
                self.assertTrue(all(high <= 1 for _, high in ImageChops.difference(native,tiled).getextrema()))

    def test_tiled_memory_and_jpeg_disk_preflight(self):
        with fitz.open() as pdf:
            page=pdf.new_page(width=100,height=100)
            with self.assertRaisesRegex(ValueError,'행 메모리'):
                next(tiles.raster_stripes(page,4_000_001,1))
            with self.assertRaisesRegex(ValueError,'65,500'):
                tiles.save_jpg_tiled(page,self.root/'huge.jpg',65501,100,300)
            from types import SimpleNamespace
            with patch.object(tiles.shutil,'disk_usage',return_value=SimpleNamespace(free=100)):
                with self.assertRaisesRegex(OSError,'저장 공간'):
                    tiles.save_jpg_tiled(page,self.root/'low.jpg',100,100,300)
            self.assertFalse(list(self.root.glob('.drawing-*')))
            self.assertFalse((self.root/'huge.jpg').exists())
            self.assertFalse((self.root/'low.jpg').exists())

    def test_actual_large_png_jpg_export(self):
        path=self.root/'alpha.pdf'
        with fitz.open() as pdf:
            page=pdf.new_page(width=100,height=100)
            page.draw_rect(fitz.Rect(10,10,90,90),color=None,fill=(1,0,0),fill_opacity=.5)
            pdf.save(path)
        before=hashlib.sha256(path.read_bytes()).hexdigest()
        with DrawingDocument(path) as doc:
            for fmt in ('png','jpg'):
                target=self.root/f'large.{fmt}'
                opts=OutputOptions(fmt=fmt,resolution='custom',width=3600,height=3600,
                                   background='transparent' if fmt=='png' else 'opaque')
                doc.export_image(target,opts)
                with Image.open(target) as im:
                    self.assertEqual(im.size,(3600,3600))
                    if fmt=='png':self.assertEqual(im.getpixel((1800,1800)),(255,0,0,126))
                    else:
                        r,g,b=im.getpixel((1800,1800));self.assertGreater(r,245)
                        self.assertTrue(120<=g<=140 and 120<=b<=140)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
        self.assertFalse(list(self.root.glob('.drawing-*')))

if __name__=='__main__':unittest.main(verbosity=2)
