"""Compare the new single-pass RGB crop with the established two-pass path."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz
from PIL import Image
from drawing_editor import trim
from drawing_editor.tiles import save_png_tiled


class CropSpoolTests(unittest.TestCase):
    def compare(self, page, transparent):
        width = height = 3600
        region = trim.find_content_crop(page, width, height, transparent=transparent)
        old = io.BytesIO()
        w, h = (region[2]-region[0], region[3]-region[1]) if region else (width, height)
        save_png_tiled(page, old, w, h, 300, transparent=transparent,
                       source_rect=(region[0], region[1], width, height) if region else None)
        with tempfile.TemporaryDirectory() as tmp:
            new = io.BytesIO()
            progress = []
            with patch.object(trim, 'raster_stripes', wraps=trim.raster_stripes) as raster:
                trim.save_png_tiled_crop_single_pass(page, new, width, height, 300,
                    scratch_dir=tmp, transparent=transparent, progress=progress.append)
                self.assertEqual(raster.call_count, 1)
            self.assertFalse(list(Path(tmp).iterdir()))
        self.assertEqual(old.getvalue(), new.getvalue())
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(progress[-1], 1.0)
        with Image.open(new) as im:
            self.assertEqual(im.size, (w, h))
            self.assertEqual(im.mode, 'RGBA' if transparent else 'RGB')

    def test_rgb_four_maps(self):
        for n in range(4):
            with self.subTest(sheet=n), fitz.open() as doc:
                page = doc.new_page(width=400, height=400)
                page.draw_rect(fitz.Rect(1, 1, 399, 399), color=None, fill=(1, 1, 1))
                keep = doc.add_ocg('Map', on=1)
                hidden = doc.add_ocg('Hide', on=0)
                page.draw_rect(fitz.Rect(60+n*10, 70, 300, 310), color=None, fill=(0,0,1), oc=keep)
                page.draw_rect(fitz.Rect(5, 5, 20, 20), color=None, fill=(1,0,0), oc=hidden)
                self.compare(page, False)

    def test_rgba_white_ink(self):
        with fitz.open() as doc:
            page = doc.new_page(width=400, height=400)
            page.draw_rect(fitz.Rect(70,70,330,330), color=None, fill=(1,1,1))
            page.draw_line(fitz.Point(50,60), fitz.Point(340,330), color=(1,0,0), width=.35)
            self.compare(page, True)

    def test_blank_preserves_canvas(self):
        with fitz.open() as doc:
            self.compare(doc.new_page(width=400,height=400), False)

    def test_cancel_scan_and_encode(self):
        with fitz.open() as doc, tempfile.TemporaryDirectory() as tmp:
            page = doc.new_page(width=400,height=400)
            for limit in (.1, .6):
                seen = [0.0]
                def mark(value):
                    seen[0] = value
                with self.assertRaises(InterruptedError):
                    trim.save_png_tiled_crop_single_pass(page, io.BytesIO(), 3600, 3600, 300,
                        scratch_dir=tmp, transparent=False, progress=mark,
                        cancelled=lambda: seen[0] >= limit)
                self.assertFalse(list(Path(tmp).iterdir()))


if __name__ == '__main__':
    unittest.main()
