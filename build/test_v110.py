"""Focused build regression for v1.1.0 export navigation and raster buffers."""
from pathlib import Path
import random
import tempfile
import unittest
from PIL import Image, ImageChops
from drawing_editor.output_location import completed_folder
from drawing_editor.raster_buffer import colored_bbox, blank_stripe, pack_png_rows


class ExportLocationTests(unittest.TestCase):
    def test_single_and_batch_unicode_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / '온맵 결과'
            folder.mkdir()
            paths = [folder / n for n in ('도면 1.png', '도면 2.jpg')]
            for p in paths:
                p.write_bytes(b'test')
            self.assertEqual(completed_folder(paths[:1]), folder.resolve())
            self.assertEqual(completed_folder(tuple(map(str, paths))), folder.resolve())
            self.assertIsNone(completed_folder(paths, cancelled=True))
            self.assertIsNone(completed_folder(paths, errors=(('bad', 'error'),)))

    def test_invalid_or_different_locations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / 'a.png'
            a.touch()
            sub = root / 'sub'
            sub.mkdir()
            b = sub / 'b.png'
            b.touch()
            for paths in ([], [root], [root / 'missing.png'], ['relative.png'], [a, b]):
                self.assertIsNone(completed_folder(paths))


class RasterBufferTests(unittest.TestCase):
    def test_bbox_exact_rgb_rgba_and_other_modes(self):
        rng = random.Random(42)
        for mode in ('RGB', 'RGBA', 'L', 'CMYK'):
            for shape in ((1, 1), (47, 53), (640, 513)):
                for variant in ('white', 'sparse', 'random'):
                    im = Image.new('RGB', shape, 'white')
                    if variant == 'sparse':
                        im.putpixel((shape[0]-1, shape[1]-1), (255, 254, 255))
                    if variant == 'random':
                        im.frombytes(rng.randbytes(shape[0]*shape[1]*3))
                    with im.convert(mode) as image, image.convert('RGB') as rgb, Image.new('RGB', shape, 'white') as white:
                        with ImageChops.difference(rgb, white) as old:
                            self.assertEqual(colored_bbox(image), old.getbbox())
                    im.close()

    def test_blank_stripe_exact(self):
        for size in (0, 1, 512, 12000000):
            for transparent in (False, True):
                self.assertEqual(blank_stripe(size, transparent), bytearray((b'\x00' if transparent else b'\xff') * size))

    def test_png_rows_exact_crop_and_alpha(self):
        rng = random.Random(5)
        for channels in (3, 4):
            width, height = 73, 29
            stripe = bytearray(rng.randbytes(width*height*channels))
            for left, top, w, rows in ((0, 0, width, height), (5, 7, 51, 11), (72, 28, 1, 1)):
                rowbytes = w*channels
                old = bytearray((rowbytes+1)*rows)
                for n in range(rows):
                    src = ((top+n)*width+left)*channels
                    dst = n*(rowbytes+1)+1
                    old[dst:dst+rowbytes] = stripe[src:src+rowbytes]
                self.assertEqual(pack_png_rows(stripe, width, channels, left, top, rows, rowbytes), old)


if __name__ == '__main__':
    unittest.main()
