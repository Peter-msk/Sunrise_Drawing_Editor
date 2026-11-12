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


def raster_stripes(page, width, height, *, edge=512, progress=None,
                   cancelled=None, transparent=False):
    """Assemble RGB or RGBA scanline strips from clipped page renders."""
    rect = page.rect
    # Exactly match requested raster dimensions on both axes. A single
    # min() scale causes 1px gaps on fractional or rotated PDF page sizes.
    xscale, yscale = width / rect.width, height / rect.height
    matrix = fitz.Matrix(xscale, yscale)
    base = fitz.IRect((rect * matrix).irect)
    # PyMuPDF DisplayList holds parsed page commands, reusing them for every
    # stripe. It includes annotations at creation, and is deliberately local
    # to this export: OCG visibility must be re-evaluated after a toggle.
    # Custom pages used by test doubles can still use get_pixmap directly.
    display_list = None
    if callable(getattr(page, "get_displaylist", None)):
        try:
            display_list = page.get_displaylist(annots=True)
        except (RuntimeError, ValueError, MemoryError):
            # Optional acceleration: page.get_pixmap remains the safe path.
            display_list = None
    # Render one full-width page band whenever it fits the memory budget.
    # The old implementation rendered a 512px-wide tile for every x position,
    # repeating PDF display-list traversal many times per stripe. For an A3
    # drawing at ~6500px wide this removes ~13x redundant clip renders.
    channels = 4 if transparent else 3
    budget = 12_000_000  # bounded per-render allocation, not output file cap
    halo = 2
    edge_y = max(1, min(edge, budget // max(channels, width * channels) - halo * 2))
    full_width = width * channels * (edge_y + halo * 2) <= budget
    step_x = width if full_width else edge
    for y0 in range(0, height, edge_y):
        _check(cancelled)
        y1 = min(height, y0 + edge_y)
        # Transparent PNG starts with zero alpha. The historical RGB path
        # keeps white page paper, so existing exports remain byte-compatible.
        stripe = bytearray((b'\x00' if transparent else b'\xff') *
                           (width * (y1-y0) * channels))
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
            if display_list is None:
                pix = page.get_pixmap(matrix=matrix, clip=clip, colorspace=fitz.csRGB,
                                      alpha=transparent, annots=True)
            else:
                pix = display_list.get_pixmap(matrix=matrix, clip=clip,
                                              colorspace=fitz.csRGB, alpha=transparent)
            px0, py0 = pix.irect[0] - base.x0, pix.irect[1] - base.y0
            left, right = max(0, px0), min(width, px0 + pix.width)
            top, bottom = max(y0, py0), min(y1, py0 + pix.height)
            if right <= left or bottom <= top:
                continue
            src = pix.samples_mv
            count = (right-left)*channels
            # Most bands now use a single full-width pixmap. Transfer every
            # visible row in one contiguous copy instead of a Python row loop.
            # Require matching RGB stride to avoid padding/offset corruption.
            if (left == 0 and right == width and px0 == 0 and
                    pix.width == width and pix.stride == width * channels):
                start = (top - py0) * pix.stride
                end = start + (bottom - top) * pix.stride
                stripe[(top-y0)*width*channels:(bottom-y0)*width*channels] = src[start:end]
            else:
                for yy in range(top, bottom):
                    i = (yy-py0)*pix.stride + (left-px0)*channels
                    j = ((yy-y0)*width + left)*channels
                    stripe[j:j+count] = src[i:i+count]
            del src
        yield y0, y1, stripe
        if progress: progress(y1 / height)


def _chunk(stream, label, data):
    stream.write(struct.pack('!I', len(data)))
    stream.write(label)
    stream.write(data)
    stream.write(struct.pack('!I', zlib.crc32(data, zlib.crc32(label)) & 0xffffffff))


def save_png_tiled(page, stream, width, height, dpi, *, progress=None,
                   cancelled=None, transparent=False, source_rect=None):
    """Encode RGB or RGBA PNG scanlines without a full-size RAM bitmap."""
    stream.write(b'\x89PNG\r\n\x1a\n')
    _chunk(stream, b'IHDR', struct.pack('!IIBBBBB', width, height, 8,
                                        6 if transparent else 2, 0, 0, 0))
    ppm = round(dpi / .0254)
    _chunk(stream, b'pHYs', struct.pack('!IIB', ppm, ppm, 1))
    # PNG is lossless regardless of deflate level. Level 2 materially lowers
    # CPU cost on large rendered drawings; the trade-off is larger PNG files.
    enc = zlib.compressobj(level=2)
    chunks, buffered = [], 0
    channels = 4 if transparent else 3
    rowbytes = width * channels
    if source_rect is None:
        left = top = 0
        full_width, full_height = width, height
    else:
        left, top, full_width, full_height = source_rect
        if (min(left, top) < 0 or left + width > full_width or
                top + height > full_height or width <= 0 or height <= 0):
            raise ValueError('Invalid content crop region for PNG streaming export.')
    # Render the same full-page stripes as the established legacy exporter,
    # then omit outside rows/columns BEFORE PNG compression. This guarantees
    # byte-for-byte RGB(A) pixel parity, including vector anti-aliasing at tile
    # edges, without allocating a full-page bitmap or editing input geometry.
    stripes = raster_stripes(page, full_width, full_height, progress=progress,
                             cancelled=cancelled, transparent=transparent)
    for y0, y1, stripe in stripes:
        first = max(y0, top)
        last = min(y1, top + height)
        if first >= last:
            continue
        rows = last - first
        encoded_rows = bytearray((rowbytes + 1) * rows)
        for n in range(rows):
            src = ((first + n - y0) * full_width + left) * channels
            dst = n * (rowbytes + 1) + 1
            encoded_rows[dst:dst + rowbytes] = stripe[src:src + rowbytes]
        compressed = enc.compress(encoded_rows)
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
                # No fsync/flush needed: the encoder reads this same mapped
                # memory immediately. The scratch RAW file is removed after
                # JPEG creation, and was never a durable output artifact.
                _check(cancelled)
                img = Image.frombuffer('RGB', (width, height), mm, 'raw', 'RGB', 0, 1)
                try:
                    img.save(destination, format='JPEG', dpi=(dpi,dpi), quality=98, subsampling=0)
                finally:
                    img.close()
                if progress: progress(1.0)
    finally:
        if path: path.unlink(missing_ok=True)
