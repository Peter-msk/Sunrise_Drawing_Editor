"""Large PNG/JPG exports: page tiles, bounded rendering RAM, no artificial pixel cap."""
from __future__ import annotations
import mmap
import struct
import tempfile
import zlib
from pathlib import Path
from typing import Callable
import fitz
from PIL import Image


def _check(cancelled):
    if cancelled and cancelled():
        raise InterruptedError('이미지 추출이 취소되었습니다.')


def raster_stripes(page, width, height, *, edge=512, progress=None, cancelled=None):
    """Assemble RGB scanline strips from <=512x512 clipped page renders."""
    rect = page.rect
    # Exactly match requested raster dimensions on both axes. A single
    # min() scale causes 1px gaps on fractional or rotated PDF page sizes.
    xscale, yscale = width / rect.width, height / rect.height
    matrix = fitz.Matrix(xscale, yscale)
    base = fitz.IRect((rect * matrix).irect)
    # Render one full-width page band whenever it fits the memory budget.
    # The old implementation rendered a 512px-wide tile for every x position,
    # repeating PDF display-list traversal many times per stripe. For an A3
    # drawing at ~6500px wide this removes ~13x redundant clip renders.
    budget = 12_000_000  # bounded per-render RGB allocation, not output file cap
    halo = 2
    edge_y = max(1, min(edge, budget // max(3, width * 3) - halo * 2))
    full_width = width * 3 * (edge_y + halo * 2) <= budget
    step_x = width if full_width else edge
    for y0 in range(0, height, edge_y):
        _check(cancelled)
        y1 = min(height, y0 + edge_y)
        stripe = bytearray(b'\xff' * (width * (y1-y0) * 3))
        for x0 in range(0, width, step_x):
            _check(cancelled)
            x1 = min(width, x0 + step_x)
            # Expand the render window beyond the copied pixels so vector
            # anti-aliasing at a tile boundary sees neighboring geometry.
            # Without this halo, boundary pixels can differ subtly from a
            # full-page render even when the output size is exact.
            cx0, cy0 = max(0, x0-halo), max(0, y0-halo)
            cx1, cy1 = min(width, x1+halo), min(height, y1+halo)
            clip = fitz.Rect(rect.x0 + cx0/xscale, rect.y0 + cy0/yscale,
                             rect.x0 + cx1/xscale, rect.y0 + cy1/yscale)
            pix = page.get_pixmap(matrix=matrix, clip=clip, colorspace=fitz.csRGB,
                                  alpha=False, annots=True)
            px0, py0 = pix.irect[0] - base.x0, pix.irect[1] - base.y0
            left, right = max(0, px0), min(width, px0 + pix.width)
            top, bottom = max(y0, py0), min(y1, py0 + pix.height)
            if right <= left or bottom <= top:
                continue
            src = pix.samples_mv
            count = (right-left)*3
            for yy in range(top, bottom):
                i = ((yy-py0)*pix.width + left-px0)*3
                j = ((yy-y0)*width + left)*3
                stripe[j:j+count] = src[i:i+count]
            del src
        yield y0, y1, stripe
        if progress: progress(y1 / height)


def _chunk(stream, label, data):
    stream.write(struct.pack('!I', len(data)))
    stream.write(label)
    stream.write(data)
    stream.write(struct.pack('!I', zlib.crc32(data, zlib.crc32(label)) & 0xffffffff))


def save_png_tiled(page, stream, width, height, dpi, *, progress=None, cancelled=None):
    """Encode PNG scanlines incrementally without holding final RGB image in RAM."""
    stream.write(b'\x89PNG\r\n\x1a\n')
    _chunk(stream, b'IHDR', struct.pack('!IIBBBBB', width, height, 8, 2, 0, 0, 0))
    ppm = round(dpi / .0254)
    _chunk(stream, b'pHYs', struct.pack('!IIB', ppm, ppm, 1))
    enc = zlib.compressobj(level=4)
    chunks, buffered = [], 0
    rowbytes = width*3
    for y0, y1, stripe in raster_stripes(page, width, height, progress=progress, cancelled=cancelled):
        for n in range(y1-y0):
            start = n*rowbytes
            compressed = enc.compress(b'\x00'+stripe[start:start+rowbytes])
            if compressed:
                chunks.append(compressed)
                buffered += len(compressed)
            if buffered >= 256_000:
                _chunk(stream, b'IDAT', b''.join(chunks))
                chunks.clear(); buffered=0
    chunks.append(enc.flush())
    if chunks: _chunk(stream, b'IDAT', b''.join(chunks))
    _chunk(stream, b'IEND', b'')


def save_jpg_tiled(page, destination: Path, width, height, dpi, *, progress=None, cancelled=None):
    """Tile-render to temporary disk-backed RGB, then encode JPEG with Pillow.

    PNG is truly streaming; JPEG's Pillow encoder may allocate addressable image
    memory after staged tile rendering. No arbitrary output pixel cap is used.
    """
    path = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.drawing-rgb-', suffix='.raw',
                                         dir=destination.parent, delete=False) as fp:
            path = Path(fp.name)
            fp.truncate(width*height*3)
        with open(path, 'r+b') as raw:
            with mmap.mmap(raw.fileno(), 0, access=mmap.ACCESS_WRITE) as mm:
                fwd = (lambda p: progress(.93*p)) if progress else None
                for y0, _, stripe in raster_stripes(page, width, height, progress=fwd, cancelled=cancelled):
                    offset = y0*width*3
                    mm[offset:offset+len(stripe)] = stripe
                mm.flush()
                _check(cancelled)
                img = Image.frombuffer('RGB', (width, height), mm, 'raw', 'RGB', 0, 1)
                try:
                    img.save(destination, format='JPEG', dpi=(dpi,dpi), quality=98, subsampling=0)
                finally:
                    img.close()
                if progress: progress(1.0)
    finally:
        if path: path.unlink(missing_ok=True)
