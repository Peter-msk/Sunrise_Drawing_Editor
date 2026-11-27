"""Recognize the supplied OnMap logo and expose it as a native PDF OCG.

The registered input is never saved. Only the exact decoded RGB image AND
soft-mask fingerprint authorize the addition; unknown logos remain untouched.
"""
from hashlib import sha256

LAYER_NAME = '워터마크 · 국토교통부 국토지리정보원'
_RGB_SHA256 = 'ef6c4cdb2a25c4348793bfd99827211b17473969ebc60282b2b5a8d3bbef588b'
_MASK_SHA256 = '15d2b1dc2cf9a9faee7d7b8cfd5938b4df3dc5a2b11fb1a8c9dbdb66c29b6e08'
_WIDTH, _HEIGHT = 1280, 385


def _image_matches(pdf, xref, colorspace, channels, fingerprint):
    for key, expected in (
        ('Subtype', ('name', '/Image')),
        ('Width', ('int', str(_WIDTH))),
        ('Height', ('int', str(_HEIGHT))),
        ('BitsPerComponent', ('int', '8')),
        ('ColorSpace', ('name', colorspace)),
    ):
        if pdf.xref_get_key(xref, key) != expected:
            return False
    data = pdf.xref_stream(xref)
    return (data is not None and len(data) == _WIDTH * _HEIGHT * channels
            and sha256(data).hexdigest() == fingerprint)


def separate_watermark(pdf):
    """Return the new OCG xref, or None when no verified unlayered logo exists.

    Called only when loading an original PDF, before reading layer metadata.
    Existing OCG/OCMD associations are never overwritten. Xref order and the
    resulting layer key are deterministic for the same unchanged source.
    """
    if not pdf.is_pdf or pdf.needs_pass or not pdf.page_count:
        return None
    # Only inspect page image resources (including nested Form XObjects), not
    # every xref in a large map. Repeated placements share a single xref.
    candidates = sorted({entry[0] for page in range(pdf.page_count)
                         for entry in pdf.get_page_images(page, full=True)
                         if entry[0] > 0})
    matches = []
    for xref in candidates:
        try:
            if not _image_matches(pdf, xref, '/DeviceRGB', 3, _RGB_SHA256):
                continue
            if pdf.get_oc(xref):
                continue
            kind, ref = pdf.xref_get_key(xref, 'SMask')
            if kind != 'xref':
                continue
            mask = int(ref.split()[0])
            if not 0 < mask < pdf.xref_length():
                continue
            if not _image_matches(pdf, mask, '/DeviceGray', 1, _MASK_SHA256):
                continue
            matches.append(xref)
        except (ValueError, RuntimeError, IndexError):
            # An unreadable candidate is not a verified watermark.
            continue
    if not matches:
        return None
    # Do not attach to a pre-existing, possibly unrelated or locked group
    # merely because it happens to have the same display name.
    names = {entry.get('name') for entry in (pdf.get_ocgs() or {}).values()}
    name = LAYER_NAME
    suffix = 2
    while name in names:
        name = f'{LAYER_NAME} ({suffix})'
        suffix += 1
    ocg = pdf.add_ocg(name, on=True)
    for xref in matches:
        pdf.set_oc(xref, ocg)
    return ocg
