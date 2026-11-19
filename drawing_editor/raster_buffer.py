"""Lossless bounded raster-buffer helpers; no geometry or compression changes."""
from PIL import ImageChops


def colored_bbox(image):
    # Invert is exactly 255 - channel, equal to abs(channel - 255).
    # Avoid copying an already RGB image and allocating a white reference.
    rgb = image if image.mode == 'RGB' else image.convert('RGB')
    try:
        inverted = ImageChops.invert(rgb)
        try:
            return inverted.getbbox()
        finally:
            inverted.close()
    finally:
        if rgb is not image:
            rgb.close()


def blank_stripe(size, transparent):
    # Avoid creating an equally large immutable bytes object first.
    return bytearray(size) if transparent else bytearray(b'\xff') * size


def pack_png_rows(stripe, full_width, channels, left, top_offset, rows, rowbytes):
    # Each row starts with the unchanged PNG filter byte 0.
    encoded = bytearray((rowbytes + 1) * rows)
    source = memoryview(stripe)
    target = memoryview(encoded)
    try:
        for n in range(rows):
            src = ((top_offset + n) * full_width + left) * channels
            dst = n * (rowbytes + 1) + 1
            target[dst:dst + rowbytes] = source[src:src + rowbytes]
    finally:
        target.release()
        source.release()
    return encoded
