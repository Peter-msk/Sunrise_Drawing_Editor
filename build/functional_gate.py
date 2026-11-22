"""Require packaged drawing QA evidence for the exact signed executable."""
from __future__ import annotations

import json
from pathlib import Path

STATUS = 'SYNTHETIC_PACKAGED_BATCH_PASS_FULL_QA_PENDING'
REQUIRED = frozenset({'four_pdf_ocg_png_crop_pixel_exact', 'four_pdf_jpg_hidden_ocg',
                      'dxf_batch_layer_toggle', 'pre_cancel_no_output', 'source_sha256_preserved'})


V130_REQUIRED = REQUIRED | {'pdf_region_native_pixels', 'dxf_color_override_pixels'}

V140_REQUIRED = V130_REQUIRED | {'pdf_native_vector_ocg', 'svg_visible_paths', 'dxf_selected_coordinates'}

EXTRACTION_REQUIRED = (V140_REQUIRED - {'dxf_color_override_pixels'}) | {'dxf_original_color_pixels', 'dxf_compound_native'}

def read_functional_qa(path: Path, sha256: str, *, version=None, extraction_only=False) -> dict:
    ver = tuple(map(int, version.split('.'))) if version is not None else (0,0,0)
    required = V140_REQUIRED if ver >= (1,4,0) else V130_REQUIRED if ver >= (1,3,0) else REQUIRED
    try:
        with path.open('rb') as stream:
            body = stream.read(65537)
        if len(body) > 65536:
            raise ValueError('Report too large')
        data = json.loads(body)
        if (not isinstance(data, dict) or type(data.get('schema_version')) is not int
                or data['schema_version'] != 1 or data.get('sha256') != sha256
                or data.get('status') != STATUS):
            raise ValueError('Wrong schema, EXE hash or QA status')
        checks = data.get('checks_passed')
        if extraction_only or ver >= (1,5,0) or (ver >= (1,4,0) and isinstance(checks, list) and 'dxf_original_color_pixels' in checks):
            required = EXTRACTION_REQUIRED
        if (not isinstance(checks, list) or not all(isinstance(s, str) for s in checks)
                or not required.issubset(checks) or len(set(checks)) != len(checks)):
            raise ValueError('Required packaged drawing checks missing or duplicated')
        pending = data.get('not_run')
        if (not isinstance(pending, list) or not all(isinstance(s, str) for s in pending)
                or required.intersection(pending)):
            raise ValueError('Invalid pending checks')
        return data
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f'Packaged functional QA rejected: {path.name}: {exc}') from exc
