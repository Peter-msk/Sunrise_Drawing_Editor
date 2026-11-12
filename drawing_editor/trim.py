"""Conservative white-paper margin detection for optional PNG content export.

This is VISUAL output cropping, not PDF content deletion or geometry editing.
The default API preserves original sheet coordinates and dimensions. Very faint
artwork near a page edge causes a safe no-crop rather than discarded content.
"""
from __future__ import annotations

from math import ceil, floor

import fitz
from PIL import Image, ImageChops


def image_ink_bbox(image):
    """Pixel-exact visible-ink bbox; compositing alpha over white avoids false black margins.

    Only crops an output canvas. Never rewrites white map symbols or source data.
    """
    if image.mode == 'RGBA':
        white = Image.new('RGB', image.size, 'white')
        try:
            white.paste(image, mask=image.getchannel('A'))
            visible = white
            paper = Image.new('RGB', image.size, 'white')
            try:
                bbox = ImageChops.difference(visible, paper).getbbox()
            finally:
                paper.close()
        finally:
            white.close()
    else:
        visible = image.convert('RGB')
        try:
            paper = Image.new('RGB', image.size, 'white')
            try:
                bbox = ImageChops.difference(visible, paper).getbbox()
            finally:
                paper.close()
        finally:
            visible.close()
    if not bbox or bbox == (0, 0, image.width, image.height):
        return None
    if bbox[2] - bbox[0] < image.width * .15 or bbox[3] - bbox[1] < image.height * .15:
        return None
    return bbox


def find_content_crop(page, full_width: int, full_height: int, *, max_preview: int = 768):
    """Return integer full-resolution crop (left, top, right, bottom), or None.

    All non-white pixels, including thin annotations, are preserved. A small
    preview limits memory to <~2 MiB; the 1-pixel preview halo protects content
    at anti-aliased edges. Nonrectangular/ambiguous extents fall back to full page.
    """
    rect = page.rect
    if (rect.is_empty or rect.width <= 0 or rect.height <= 0 or
            full_width <= 0 or full_height <= 0):
        return None
    scale = min(1.0, max_preview / max(full_width, full_height))
    sw = max(1, round(full_width * scale))
    sh = max(1, round(full_height * scale))
    pix = page.get_pixmap(matrix=fitz.Matrix(sw / rect.width, sh / rect.height),
                          colorspace=fitz.csRGB, alpha=False, annots=True)
    image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    try:
        reference = Image.new('RGB', image.size, (255, 255, 255))
        try:
            bbox = ImageChops.difference(image, reference).getbbox()
        finally:
            reference.close()
    finally:
        image.close()
    if bbox is None:
        return None  # blank sheet, leave original size intact
    # Outside the detected rectangle *all* preview pixels are pure white.
    # Deliberately expand the bbox to avoid clipping anti-aliasing or thin lines.
    pad = max(1, ceil(max(full_width / pix.width, full_height / pix.height)))
    x0 = max(0, floor(bbox[0] * full_width / pix.width) - pad)
    y0 = max(0, floor(bbox[1] * full_height / pix.height) - pad)
    x1 = min(full_width, ceil(bbox[2] * full_width / pix.width) + pad)
    y1 = min(full_height, ceil(bbox[3] * full_height / pix.height) + pad)
    if x0 == y0 == 0 and x1 == full_width and y1 == full_height:
        return None
    # A single dot, logo or noise is not a trustworthy rectangular drawing.
    if x1 - x0 < full_width * .15 or y1 - y0 < full_height * .15:
        return None
    return x0, y0, x1, y1
