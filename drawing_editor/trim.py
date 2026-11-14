"""Pixel-exact detection of optional PNG content bounds.

Only the *output canvas* is cropped. PDF, CAD objects, and rendered pixels are
never edited. Ambiguous and very small content falls back to the full page.
"""
from __future__ import annotations

import tempfile

from PIL import Image, ImageChops

from .tiles import raster_stripes, save_png_tiled


def _colored_bbox(image):
    """Find non-white RGB pixels, regardless of whether white ink was painted."""
    rgb = image.convert('RGB')
    try:
        white = Image.new('RGB', rgb.size, 'white')
        try:
            return ImageChops.difference(rgb, white).getbbox()
        finally:
            white.close()
    finally:
        rgb.close()


def image_ink_bbox(image):
    """Visible content bbox: preserve white ink on a transparent canvas.

    If some pixels are transparent, alpha distinguishes opaque white artwork
    from empty paper. For a fully painted (opaque) white page, color difference
    is required instead, so the surrounding white sheet can still be cropped.
    """
    if image.mode == 'RGBA':
        alpha = image.getchannel('A')
        try:
            partially_clear = alpha.getextrema()[0] < 255
            bbox = alpha.getbbox() if partially_clear else _colored_bbox(image)
        finally:
            alpha.close()
    else:
        bbox = _colored_bbox(image)
    if not bbox or bbox == (0, 0, image.width, image.height):
        return None
    if bbox[2] - bbox[0] < image.width * .15 or bbox[3] - bbox[1] < image.height * .15:
        return None
    return bbox


def _union(existing, incoming, y_offset):
    if incoming is None:
        return existing
    a, b, c, d = incoming
    incoming = (a, b + y_offset, c, d + y_offset)
    if existing is None:
        return incoming
    return (min(existing[0], incoming[0]), min(existing[1], incoming[1]),
            max(existing[2], incoming[2]), max(existing[3], incoming[3]))


def find_content_crop(page, full_width: int, full_height: int, *,
                      progress=None, cancelled=None):
    """Detect the exact bbox from full-resolution, bounded-memory scanlines.

    A small downsampled preview can miss hairline art, fine annotations or
    barely visible labels that belong to the drawing. Reuse the established
    tiled rasterizer for both the scan and export. This costs an additional
    render pass *only when large-PNG cropping is enabled*, but means no ink
    pixel can be discarded by sampling. Existing blank/ambiguous fallbacks
    remain unchanged. Progress and cancellation cover the scan as well.
    """
    rect = page.rect
    if (rect.is_empty or rect.width <= 0 or rect.height <= 0 or
            full_width <= 0 or full_height <= 0):
        return None
    alpha_bbox = color_bbox = None
    partially_clear = False
    for y0, y1, stripe in raster_stripes(page, full_width, full_height,
                                         transparent=True, progress=progress,
                                         cancelled=cancelled):
        image = Image.frombytes('RGBA', (full_width, y1-y0), stripe)
        try:
            alpha = image.getchannel('A')
            try:
                if alpha.getextrema()[0] < 255:
                    partially_clear = True
                alpha_bbox = _union(alpha_bbox, alpha.getbbox(), y0)
            finally:
                alpha.close()
            color_bbox = _union(color_bbox, _colored_bbox(image), y0)
        finally:
            image.close()
    bbox = alpha_bbox if partially_clear else color_bbox
    if not bbox or bbox == (0, 0, full_width, full_height):
        return None
    if bbox[2] - bbox[0] < full_width * .15 or bbox[3] - bbox[1] < full_height * .15:
        return None
    return bbox


def save_png_tiled_crop_single_pass(page, stream, full_width: int,
                                    full_height: int, dpi: int, *,
                                    scratch_dir, progress=None, cancelled=None):
    """Render once, detect exact content bounds, then encode cached RGBA rows.

    For large transparent PNGs the previous exact-trim path traversed the
    expensive full-resolution PDF twice. Keep one temporary disk-backed row
    spool (never the entire bitmap in RAM), scan those RGBA rows for the
    original alpha/color bbox, and feed the unmodified bytes to the existing
    PNG stripe encoder. The scratch file is deleted on normal/error/cancel.
    """
    if full_width <= 0 or full_height <= 0:
        raise ValueError('Invalid transparent source dimensions')
    alpha_bbox = color_bbox = None
    partially_clear = False
    parts = []
    with tempfile.TemporaryFile(mode='w+b', prefix='.drawing-rgba-',
                                dir=scratch_dir) as raw:
        # Scanning RGBA must follow the exact legacy content-bound rules.
        scan_progress = (lambda p: progress(p * .5)) if progress else None
        for y0, y1, stripe in raster_stripes(
                page, full_width, full_height, transparent=True,
                progress=scan_progress, cancelled=cancelled):
            if cancelled and cancelled():
                raise InterruptedError('이미지 추출이 취소되었습니다.')
            raw.write(stripe)
            parts.append((y0, y1, len(stripe)))
            image = Image.frombytes('RGBA', (full_width, y1-y0), stripe)
            try:
                alpha = image.getchannel('A')
                try:
                    if alpha.getextrema()[0] < 255:
                        partially_clear = True
                    alpha_bbox = _union(alpha_bbox, alpha.getbbox(), y0)
                finally:
                    alpha.close()
                color_bbox = _union(color_bbox, _colored_bbox(image), y0)
            finally:
                image.close()
        bbox = alpha_bbox if partially_clear else color_bbox
        if (not bbox or bbox == (0, 0, full_width, full_height)
                or bbox[2]-bbox[0] < full_width * .15
                or bbox[3]-bbox[1] < full_height * .15):
            bbox = None
        if bbox is None:
            left = top = 0
            width, height = full_width, full_height
            selection = None
        else:
            left, top, right, bottom = bbox
            width, height = right-left, bottom-top
            selection = (left, top, full_width, full_height)
        raw.seek(0)

        def saved_stripes():
            for y0, y1, size in parts:
                if cancelled and cancelled():
                    raise InterruptedError('이미지 추출이 취소되었습니다.')
                data = raw.read(size)
                if len(data) != size:
                    raise OSError('Temporary PNG stripe data was truncated')
                yield y0, y1, data

        encode_progress = (lambda p: progress(.5 + p*.5)) if progress else None
        save_png_tiled(page, stream, width, height, dpi, progress=encode_progress,
                       cancelled=cancelled, transparent=True,
                       source_rect=selection, cached_stripes=saved_stripes())
