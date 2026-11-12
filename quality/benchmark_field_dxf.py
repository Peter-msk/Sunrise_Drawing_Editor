"""Reproducible real-file DXF profiling without redistributing user drawings.

Usage (CMD): python quality/benchmark_field_dxf.py "D:\\drawings\\large.dxf"
No PowerShell, no virtual environment, no input mutation. Writes a JSON report
next to the provided --report path; source DXF is NEVER copied to the project.
"""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import time

try:
    import psutil  # optional: only for extended RSS measurements
except ImportError:
    psutil = None
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drawing_editor.core import DrawingDocument, OutputOptions


def file_hash(path: Path) -> str:
    state = hashlib.sha256()
    with path.open('rb') as file:
        for piece in iter(lambda: file.read(4 * 1024 * 1024), b''):
            state.update(piece)
    return state.hexdigest()


def measure(path: Path, enabled_layer: str | None = None) -> dict:
    start = time.perf_counter()
    rss = lambda: (round(psutil.Process().memory_info().rss / 1024**2, 2)
                   if psutil is not None else None)
    results = {'source_bytes': path.stat().st_size, 'source_sha256_before': file_hash(path)}
    catalog_started = time.perf_counter()
    with DrawingDocument(path) as d:
        results['catalog_seconds'] = round(time.perf_counter() - catalog_started, 4)
        results['layer_count'] = len(d.layers())
        results['initially_enabled_layers'] = sum(layer.visible for layer in d.layers())
        t = time.perf_counter()
        data = d.render_bytes(preview=(1000, 700))
        img = Image.open(BytesIO(data)).convert('RGB')
        results['first_preview_seconds'] = round(time.perf_counter() - t, 4)
        results['first_preview_pixel_sha256'] = hashlib.sha256(img.tobytes()).hexdigest()
        results['first_preview_pixels'] = img.size
        results['rss_after_first_preview_mib'] = rss()
        if d._cad_selective_last_stats is not None:
            r = d._cad_selective_last_stats
            results['selective'] = {
                'total_records': r.total_entities, 'selected_records': r.selected_entities,
                'staged_bytes': r.staged_bytes, 'blocks_pruned': r.blocks_pruned,
                'stage_seconds': round(r.elapsed_seconds, 4),
            }
        t = time.perf_counter()
        same = d.render_bytes(preview=(1000, 700))
        results['repeated_preview_seconds'] = round(time.perf_counter() - t, 6)
        results['repeated_preview_equal'] = same == data
        if enabled_layer is not None:
            if enabled_layer not in d.states():
                raise ValueError(f'Unknown layer: {enabled_layer}')
            t = time.perf_counter()
            d.set_visibility(enabled_layer, True)
            updated = d.render_bytes(preview=(1000, 700))
            results['added_layer'] = {
                'layer': enabled_layer, 'seconds': round(time.perf_counter() - t, 4),
                'pixel_changed': updated != data, 'rss_mib': rss(),
            }
            if d._cad_selective_last_stats is not None:
                r = d._cad_selective_last_stats
                results['added_layer']['selected_records'] = r.selected_entities
                results['added_layer']['staged_bytes'] = r.staged_bytes
                results['added_layer']['blocks_pruned'] = r.blocks_pruned
            t = time.perf_counter()
            d.set_visibility(enabled_layer, False)
            restored = d.render_bytes(preview=(1000, 700))
            results['added_layer_restore'] = {
                'seconds': round(time.perf_counter() - t, 4),
                'pixel_identical': restored == data,
            }
    results['source_sha256_after'] = file_hash(path)
    results['source_unchanged'] = results['source_sha256_after'] == results['source_sha256_before']
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('dxf')
    parser.add_argument('--layer', default=None)
    parser.add_argument('--report', default='field_benchmark.json')
    args = parser.parse_args()
    result = measure(Path(args.dxf), args.layer)
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
