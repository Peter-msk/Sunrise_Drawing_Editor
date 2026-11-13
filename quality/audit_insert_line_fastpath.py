"""Synthetic 9,533-INSERT x2-LINE audit of stock vs ThreePass CAD PDF commands.

No user DXF is bundled or benchmarked by this script. This verifies the
unmodified ThreePass fast backend still makes byte- and pixel-identical PDF
paint content, and samples PDF generation time on this machine.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ezdxf
import fitz
from ezdxf.addons.drawing import Frontend, RenderContext, layout, pymupdf
from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy
from drawing_editor.cad_render_fast import FastPyMuPdfBackend


def create_drawing(n):
    cad = ezdxf.new('R2013')
    cad.layers.new('INSERT_LINES', dxfattribs={'color': 5})
    block = cad.blocks.new('TOWER_BLOCK')
    block.add_line((0, 0), (4, 10))
    block.add_line((4, 10), (8, 0))
    for index in range(n):
        cad.modelspace().add_blockref('TOWER_BLOCK',
                ((index % 120) * 10, (index // 120) * 13),
                dxfattribs={'layer': 'INSERT_LINES', 'rotation': (index % 7) * 3.0})
    return cad


def one_render(cad, backend_cls):
    start = time.perf_counter()
    renderer = backend_cls()
    Frontend(RenderContext(cad), renderer, config=Configuration(
        background_policy=BackgroundPolicy.OFF,
        color_policy=ColorPolicy.COLOR)).draw_layout(cad.modelspace())
    geom = renderer.player().bbox()
    pdf = renderer.get_pdf_bytes(layout.Page(0, 0), render_box=geom)
    elapsed = time.perf_counter() - start
    with fitz.open(stream=pdf, filetype='pdf') as doc:
        data = b''.join(doc.xref_stream(x) for x in doc[0].get_contents())
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(.8, .8), alpha=False)
        return {'seconds': round(elapsed, 5), 'stream_sha256': hashlib.sha256(data).hexdigest(),
                'pixel_sha256': hashlib.sha256(pix.samples).hexdigest(),
                'pdf_bytes': len(pdf)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inserts', type=int, default=9533)
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    if not 1 <= args.inserts <= 20_000 or not 3 <= args.runs <= 10:
        parser.error('inserts=1..20000, runs=3..10')
    cad = create_drawing(args.inserts)
    rows=[]
    for idx in range(args.runs):
        order = ('stock','threepass') if idx % 2 == 0 else ('threepass','stock')
        pair={}
        for name in order:
            pair[name] = one_render(cad, pymupdf.PyMuPdfBackend if name=='stock' else FastPyMuPdfBackend)
        pair['stream_equal'] = pair['stock']['stream_sha256'] == pair['threepass']['stream_sha256']
        pair['pixels_equal'] = pair['stock']['pixel_sha256'] == pair['threepass']['pixel_sha256']
        rows.append(pair)
    stock=statistics.median(r['stock']['seconds'] for r in rows)
    fast=statistics.median(r['threepass']['seconds'] for r in rows)
    result={'input_type':'synthetic_only','inserts':args.inserts,
            'expanded_lines':args.inserts*2,'runs':rows,
            'all_stream_equal':all(r['stream_equal'] for r in rows),
            'all_pixels_equal':all(r['pixels_equal'] for r in rows),
            'stock_median_seconds':round(stock,5),'threepass_median_seconds':round(fast,5),
            'speedup_ratio':round(stock/max(fast,1e-12),3),
            'field_402mib_dxf':'NOT RUN'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('all_stream_equal','all_pixels_equal',
        'stock_median_seconds','threepass_median_seconds','speedup_ratio')},ensure_ascii=False))

if __name__=='__main__':
    main()
