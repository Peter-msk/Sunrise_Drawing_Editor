"""Require packaged drawing QA evidence for the exact signed executable."""
from __future__ import annotations

import json
from pathlib import Path

STATUS = 'SYNTHETIC_PACKAGED_BATCH_PASS_FULL_QA_PENDING'
REQUIRED = frozenset({'four_pdf_ocg_png_crop_pixel_exact', 'four_pdf_jpg_hidden_ocg',
                      'dxf_batch_layer_toggle', 'pre_cancel_no_output', 'source_sha256_preserved'})


def read_functional_qa(path: Path, sha256: str) -> dict:
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
        if (not isinstance(checks, list) or not all(isinstance(s, str) for s in checks)
                or not REQUIRED.issubset(checks) or len(set(checks)) != len(checks)):
            raise ValueError('Required packaged drawing checks missing or duplicated')
        pending = data.get('not_run')
        if (not isinstance(pending, list) or not all(isinstance(s, str) for s in pending)
                or REQUIRED.intersection(pending)):
            raise ValueError('Invalid pending checks')
        return data
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f'Packaged functional QA rejected: {path.name}: {exc}') from exc
