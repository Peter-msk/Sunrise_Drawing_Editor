"""First feedback regression: opaque trim must use actual RGB output."""
import tempfile
import unittest
from pathlib import Path
import fitz
from PIL import Image, ImageChops
from drawing_editor.core import DrawingDocument, OutputOptions
from drawing_editor.batch import plan_exports
from drawing_editor.batch_worker import run_batch_exports_isolated


class FourSheetCrop(unittest.TestCase):
    def test_four_distinct_pdfs_rgb_trim_and_ocg(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = []
            try:
                for n in range(4):
                    path = root / f'sheet-{n}.pdf'
                    with fitz.open() as pdf:
                        p = pdf.new_page(width=400, height=400)
                        p.draw_rect(fitz.Rect(1, 1, 399, 399), color=None, fill=(1, 1, 1))
                        main = pdf.add_ocg('Map', on=1)
                        extra = pdf.add_ocg('Hide', on=1)
                        p.draw_rect(fitz.Rect(60+n*10, 70, 300, 310), color=None, fill=(.2, .4, .6), oc=main)
                        p.draw_rect(fitz.Rect(5, 5, 20, 20), color=None, fill=(1, 0, 0), oc=extra)
                        pdf.save(path)
                    doc = DrawingDocument(path)
                    docs.append(doc)
                    doc.set_visibility(next(x.key for x in doc.layers() if x.name == 'Hide'), False)
                original = [d.path.read_bytes() for d in docs]
                opts = OutputOptions('png', 'custom', 3600, 3600, crop_margins=True)
                jobs = plan_exports(docs, root, opts)
                result = run_batch_exports_isolated(jobs, opts)
                self.assertFalse(result.errors)
                self.assertEqual(len(result.completed), 4)
                for n, (doc, job) in enumerate(zip(docs, jobs)):
                    full_path = root / f'full-{n}.png'
                    single_path = root / f'single-{n}.png'
                    doc.export_image(full_path, OutputOptions('png', 'custom', 3600, 3600))
                    doc.export_image(single_path, opts)
                    with Image.open(full_path) as full, Image.open(job.target) as actual, Image.open(single_path) as single:
                        bbox = ImageChops.difference(full, Image.new('RGB', full.size, 'white')).getbbox()
                        self.assertEqual(bbox, ((60+n*10)*9, 630, 2700, 2790))
                        expected = full.crop(bbox)
                        self.assertEqual(actual.size, expected.size)
                        self.assertEqual(actual.tobytes(), expected.tobytes())
                        self.assertEqual(actual.tobytes(), single.tobytes())
                self.assertEqual([d.path.read_bytes() for d in docs], original)
            finally:
                for doc in docs:
                    doc.close()
