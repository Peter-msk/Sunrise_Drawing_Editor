"""Reproducible synthetic DXF record-copy benchmark, no user files required.

Measures only byte-span staging I/O (not whole CAD preview time). Run the
unchanged reference loop and batched helper on identical selected records.
"""
from __future__ import annotations
from io import BytesIO
import hashlib
import json
import mmap
from pathlib import Path
import statistics
import tempfile
import time

from drawing_editor.cad_selective import _write_selected_entities


def _legacy_copy(target, source, selected):
    for start, stop, _, _ in selected:
        target.write(source[start:stop])


def benchmark(n=120000, repeats=5):
    # Grouped visible layer: 8 adjacent entities then 2 hidden. Each group
    # remains adjacent in the source, modeling selective CAD layer blocks.
    one = b'  0\r\nLINE\r\n  8\r\nA\r\n 10\r\n123.456\r\n 20\r\n789.012\r\n'
    records = []
    with tempfile.TemporaryDirectory() as directory:
        source_path = Path(directory) / 'large-entities.bin'
        with source_path.open('wb') as out:
            for i in range(n):
                begin = out.tell()
                out.write(one)
                if i % 10 < 8:
                    records.append((begin, out.tell(), b'LINE', 'a'))
        with source_path.open('rb') as raw, mmap.mmap(raw.fileno(), 0, access=mmap.ACCESS_READ) as source:
            times = {"memory_original": [], "memory_batched": [],
                     "file_original": [], "file_batched": []}
            sha = {}
            for label, fn in [('original', _legacy_copy), ('batched', _write_selected_entities)]:
                for _ in range(repeats):
                    target = BytesIO()
                    tick = time.perf_counter()
                    fn(target, source, records)
                    times['memory_' + label].append(time.perf_counter() - tick)
                    sha[label] = hashlib.sha256(target.getvalue()).hexdigest()
                dest = Path(directory) / ('stage-' + label + '.bin')
                for _ in range(repeats):
                    tick = time.perf_counter()
                    with dest.open('wb', buffering=256 * 1024) as target:
                        fn(target, source, records)
                    times['file_' + label].append(time.perf_counter() - tick)
                if hashlib.sha256(dest.read_bytes()).hexdigest() != sha[label]:
                    raise AssertionError('Memory/file content mismatch')
            if sha['original'] != sha['batched']:
                raise AssertionError('Source-byte mismatch!')
            return {
                'source_bytes': len(source), 'total_records': n,
                'visible_records': len(records), 'repeats': repeats,
                'median_memory_original_s': round(statistics.median(times['memory_original']), 6),
                'median_memory_batched_s': round(statistics.median(times['memory_batched']), 6),
                'median_file_original_s': round(statistics.median(times['file_original']), 6),
                'median_file_batched_s': round(statistics.median(times['file_batched']), 6),
                'sha256_equal': True,
                'output_sha256': sha['batched'],
                'note': 'Synthetic record-copy only, not whole-file DXF render or Windows GUI',
            }


if __name__ == '__main__':
    result = benchmark()
    path = Path('quality/CAD_IO_BATCH_BENCHMARK.json')
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
