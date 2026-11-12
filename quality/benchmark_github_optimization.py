"""Before/after engine benchmark. Run: python quality/benchmark_github_optimization.py

The bundled quality/baseline_tiles.py is a frozen copy of the previous tile
writer, for fair comparison. This script is never imported by the application.
All numbers are synthetic-source measurements, not 100MB DWG claims.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
import platform
import statistics
import tempfile
from time import perf_counter

import fitz
from PIL import Image, ImageChops
from drawing_editor.core import DrawingDocument, _render_page
from drawing_editor.tiles import save_png_tiled, save_jpg_tiled
from baseline_tiles import save_png_tiled as old_png, save_jpg_tiled as old_jpg


def med(times):
    return round(statistics.median(times), 6)


def create_pdf(path):
    with fitz.open() as doc:
        page = doc.new_page(width=600, height=850)
        # One dense vector content stream keeps the synthetic reference stable.
        ocg = doc.add_ocg('VECTOR_ROAD')
        sh = page.new_shape()
        for i in range(3800):
            x = 14 + (i * 37) % 540
            y = 20 + (i * 67) % 800
            sh.draw_line((x, y), (min(x + 28, 590), min(y + 21, 838)))
        sh.finish(color=(0.2, 0.3, 0.5), width=.4, oc=ocg)
        sh.commit()
        annotation = page.add_rect_annot(fitz.Rect(200, 250, 280, 325))
        annotation.set_colors(stroke=(0.7, 0.2, 0.15))
        annotation.update()
        doc.save(path)


def run_bench(path, dest):
    result = {
        'input': 'generated vector PDF, 3800 lines, one OCG, one annotation',
        'platform': platform.platform(),
        'fitz': fitz.VersionBind,
        'export_png_pixels': [3000, 4250],
        'export_jpg_pixels': [2500, 3400],
        'runs_each': 3,
        'png': {}, 'jpg': {}, 'preview': {},
    }
    initial_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    with fitz.open(str(path)) as pdf:
        page = pdf[0]
        methods = [('before', old_png), ('after', save_png_tiled)]
        times = {'before': [], 'after': []}
        blobs = {}
        for repeat in range(3):
            if repeat % 2:
                methods.reverse()
            for title, method in methods:
                data = BytesIO()
                t = perf_counter()
                method(page, data, 3000, 4250, 300)
                times[title].append(perf_counter() - t)
                blobs[title] = data.getvalue()
        for key in times:
            result['png'][key] = {
                'seconds': list(map(lambda x: round(x, 5), times[key])),
                'median_seconds': med(times[key]),
                'file_bytes': len(blobs[key]),
            }
        with Image.open(BytesIO(blobs['before'])) as a, Image.open(BytesIO(blobs['after'])) as b:
            result['png']['pixels_identical'] = (
                a.size == b.size and ImageChops.difference(a.convert('RGB'), b.convert('RGB')).getbbox() is None
            )

        jpg_times = {'before': [], 'after': []}
        jpg_data = {}
        jpg_methods = [('before', old_jpg), ('after', save_jpg_tiled)]
        for repeat in range(3):
            if repeat % 2:
                jpg_methods.reverse()
            for title, method in jpg_methods:
                file = dest / (title + '.jpg')
                t = perf_counter()
                method(page, file, 2500, 3400, 300)
                jpg_times[title].append(perf_counter() - t)
                jpg_data[title] = file.read_bytes()
        for key in jpg_times:
            result['jpg'][key] = {'seconds': list(map(lambda x: round(x, 5), jpg_times[key])),
                                  'median_seconds': med(jpg_times[key]),
                                  'file_bytes': len(jpg_data[key])}
        with Image.open(BytesIO(jpg_data['before'])) as a, Image.open(BytesIO(jpg_data['after'])) as b:
            result['jpg']['pixels_identical'] = (a.size == b.size and
                ImageChops.difference(a.convert('RGB'), b.convert('RGB')).getbbox() is None)

    # Compare the engine's previous Page.get_pixmap path to cached list
    # rendering over a sequence of distinct clip windows (no exact PNG cache).
    clips = [(5 + (i * 13) % 250, 15 + (i * 11) % 350,
              210 + (i * 13) % 250, 240 + (i * 11) % 350) for i in range(25)]
    repeats = 3
    before, after = [], []
    all_equal = True
    with DrawingDocument(path) as drawing:
        page = drawing._pdf[0]
        for repeat in range(repeats):
            t = perf_counter()
            original = [_render_page(page, 'png', (550, 450), clip=c) for c in clips]
            before.append(perf_counter() - t)
            # Force list first, but account for its preparation in this timing.
            drawing._preview_display_list = None
            drawing._preview_display_key = None
            drawing._preview_cache.clear()
            drawing._preview_cache_bytes = 0
            t = perf_counter()
            accelerated = [drawing.render_bytes(preview=(550, 450), clip=c) for c in clips]
            after.append(perf_counter() - t)
            all_equal = all_equal and original == accelerated
    result['preview'] = {
        'regions_per_run': len(clips),
        'before_seconds': [round(v, 5) for v in before],
        'after_seconds': [round(v, 5) for v in after],
        'before_median_seconds': med(before),
        'after_median_seconds': med(after),
        'png_bytes_identical': all_equal,
    }
    result['source_file_unchanged'] = hashlib.sha256(path.read_bytes()).hexdigest() == initial_hash
    return result


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='drawing-gh-qa-') as temp:
        folder = Path(temp)
        source = folder / 'vector_test.pdf'
        create_pdf(source)
        result = run_bench(source, folder)
    output = Path(__file__).with_name('GITHUB_OPTIMIZATION_BENCHMARK.json')
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
