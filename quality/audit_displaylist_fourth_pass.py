"""Measure one CAD state directly against a bounded native DisplayList.

This is a read-only audit of ThreePass' optional rasterization accelerator,
NOT permission to enable it in normal Windows GUI or publish a release.

Examples:
  python quality/audit_displaylist_fourth_pass.py --synthetic-arcs --output quality/ARC_SYNTHETIC.json
  python quality/audit_displaylist_fourth_pass.py "D:\\CAD\\3구간 최종 철탑.dxf" --layer G0022322 --output QA_ARC.json
  python quality/audit_displaylist_fourth_pass.py "D:\\CAD\\3구간 최종 철탑.dxf" --layer C0285311 --layer G0022322 --output QA_COMBINED.json

Synthetic data only reproduces repeated-path density; it is NOT the 402MiB
field DXF and cannot authorize promotion of a large-DXF optimization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ezdxf
import fitz
from ezdxf.addons.drawing import Frontend, RenderContext, layout, pymupdf
from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy
from drawing_editor.core import DrawingDocument
from drawing_editor.cad_render_fast import FastPyMuPdfBackend

try:
    import psutil
except ImportError:
    psutil = None


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def rss_mib() -> float | None:
    if psutil is None:
        return None
    return round(psutil.Process().memory_info().rss / (1024 * 1024), 2)


def synthetic_arc_pdf() -> tuple[bytes, dict]:
    """214 INSERT * 78 circles; conservative, reproducible substitute only."""
    cad = ezdxf.new('R2013')
    cad.layers.new('ARC_BLOCKS', dxfattribs={'color': 5})
    block = cad.blocks.new('STRESS_CIRCLES')
    for index in range(78):
        block.add_circle(((index % 13) * 3.5, (index // 13) * 3.5), 0.9)
    for index in range(214):
        cad.modelspace().add_blockref(
            'STRESS_CIRCLES', ((index % 15) * 55, (index // 15) * 35),
            dxfattribs={'layer': 'ARC_BLOCKS', 'rotation': (index % 5) * 5.0})
    start = time.perf_counter()
    backend = FastPyMuPdfBackend()
    Frontend(RenderContext(cad), backend,
             config=Configuration(background_policy=BackgroundPolicy.OFF,
                                  color_policy=ColorPolicy.COLOR)).draw_layout(cad.modelspace())
    pdf = backend.get_pdf_bytes(layout.Page(0, 0), render_box=backend.player().bbox())
    return pdf, {'insert_count': 214, 'circle_paths': 214 * 78,
                 'cad_to_pdf_seconds': round(time.perf_counter()-start, 4),
                 'pdf_bytes': len(pdf)}


def _view_clips(page: fitz.Page, n: int) -> list[fitz.Rect]:
    bounds = page.rect
    # Distinct 40% viewport rectangles: no preview-image cache hits.
    clips = []
    for index in range(n):
        x0 = bounds.width * (index % 5) * 0.12
        y0 = bounds.height * ((index // 5) % 5) * 0.12
        clips.append(fitz.Rect(bounds.x0 + x0, bounds.y0 + y0,
                               bounds.x0 + x0 + bounds.width * .4,
                               bounds.y0 + y0 + bounds.height * .4) & bounds)
    return clips


def _pix(page_or_list, clip: fitz.Rect, *, alpha: bool) -> tuple[str, int]:
    matrix = fitz.Matrix(800 / clip.width, 600 / clip.height)
    if isinstance(page_or_list, fitz.DisplayList):
        pix = page_or_list.get_pixmap(matrix=matrix, clip=clip,
                                      colorspace=fitz.csRGB, alpha=alpha)
    else:
        pix = page_or_list.get_pixmap(matrix=matrix, clip=clip,
                                      colorspace=fitz.csRGB, alpha=alpha, annots=True)
    return hashlib.sha256(pix.samples).hexdigest(), pix.width * pix.height


def compare(page: fitz.Page, display: fitz.DisplayList, *, trials: int = 3,
            views: int = 25) -> dict:
    clips = _view_clips(page, views)
    measurements = []
    hashes_match = True
    pixel_sizes_match = True
    for iteration in range(trials):
        # Alternate execution order to reduce warming/order bias.
        modes = ('direct', 'displaylist') if iteration % 2 == 0 else ('displaylist', 'direct')
        result = {}
        for mode in modes:
            target = page if mode == 'direct' else display
            start = time.perf_counter()
            hashes = []
            # Verify alpha and solid backgrounds on identical clip sets.
            for clip in clips:
                hashes.append((_pix(target, clip, alpha=False), _pix(target, clip, alpha=True)))
            result[mode] = {
                'total_seconds': round(time.perf_counter() - start, 5),
                'hashes': hashes,
            }
        left = result['direct']['hashes']
        right = result['displaylist']['hashes']
        hashes_match &= all(a[0][0] == b[0][0] and a[1][0] == b[1][0]
                            for a, b in zip(left, right))
        pixel_sizes_match &= all(a[0][1] == b[0][1] and a[1][1] == b[1][1]
                                 for a, b in zip(left, right))
        measurements.append({
            'trial': iteration + 1,
            'direct_seconds': result['direct']['total_seconds'],
            'displaylist_seconds': result['displaylist']['total_seconds'],
        })
    direct_median = statistics.median(i['direct_seconds'] for i in measurements)
    list_median = statistics.median(i['displaylist_seconds'] for i in measurements)
    return {
        'viewport_count': views, 'backgrounds': ['opaque', 'transparent'],
        'trials': measurements, 'direct_median_seconds': round(direct_median, 5),
        'displaylist_median_seconds': round(list_median, 5),
        'render_speedup_ratio': round(direct_median / max(list_median, 1e-12), 3),
        'all_pixel_hashes_equal': bool(hashes_match),
        'all_pixel_sizes_equal': bool(pixel_sizes_match),
    }


def audit(path: Path | None, layers: list[str], *, trials: int, views: int) -> dict:
    meta = {
        'source_type': 'synthetic' if path is None else 'real_file',
        'source_path_basename': path.name if path else None,
        'source_size_bytes': path.stat().st_size if path else None,
        'source_sha256_before': file_hash(path) if path else None,
        'enabled_layers': layers,
        'environment': {'system': platform.system(), 'python': platform.python_version(),
                        'pymupdf': fitz.VersionBind, 'ezdxf': ezdxf.__version__,
                        'psutil_rss_available': psutil is not None},
    }
    doc = None
    temp = None
    try:
        if path is None:
            pdf_bytes, fixture = synthetic_arc_pdf()
            meta['synthetic_fixture'] = fixture
            doc = fitz.open(stream=pdf_bytes, filetype='pdf')
            page = doc[0]
            meta['staged_pdf_bytes'] = len(pdf_bytes)
            eligible = len(pdf_bytes) <= 2 * 1024 * 1024
        else:
            doc = DrawingDocument(path)
            available = {layer.name.casefold(): layer for layer in doc.layers()}
            for name in layers:
                layer = available.get(name.casefold())
                if layer is None:
                    raise ValueError(f'Unknown layer: {name}')
                doc.set_visibility(layer.key, True)
            # Audit the same bounded behavior now enabled by default in the
            # Stage10 candidate. Do not bypass eligibility or memory guards.
            t = time.perf_counter()
            temp, page = doc._get_page_context()
            meta['cad_to_pdf_and_staging_seconds'] = round(time.perf_counter()-t, 4)
            meta['staged_pdf_bytes'] = doc._cad_view_pdf_bytes if doc._cad_view_pdf else None
            stats = doc._cad_selective_last_stats
            meta['selected_entities'] = stats.selected_entities if stats else None
            meta['selective_staging_used'] = stats is not None
            eligible = bool(doc._cad_selective is not None and
                            temp is None and doc._cad_view_pdf is not None and
                            meta['staged_pdf_bytes'] <= 1536 * 1024 and
                            stats is not None and 0 < stats.selected_entities <= 256)
        if page is None:
            return {**meta, 'decision': 'DEFER', 'reason': 'No visible page'}
        meta['page_size_pt'] = [round(page.rect.width, 3), round(page.rect.height, 3)]
        if not eligible:
            return {**meta, 'decision': 'DEFER', 'reason': 'Candidate size/entity guard not satisfied'}
        before = rss_mib()
        t = time.perf_counter()
        if path is None:
            display = page.get_displaylist(annots=True)
        else:
            clips = _view_clips(page, 2)
            if doc._get_preview_display_list(page, temp, tuple(clips[0])) is not None:
                raise AssertionError('Candidate created list too early')
            display = doc._get_preview_display_list(page, temp, tuple(clips[1]))
            if display is None:
                return {**meta, 'decision': 'DEFER', 'reason': 'Runtime candidate gate refused list'}
        build_s = time.perf_counter() - t
        after = rss_mib()
        result = compare(page, display, trials=trials, views=views)
        delta = None if before is None or after is None else round(max(0, after-before), 2)
        parity = result['all_pixel_hashes_equal'] and result['all_pixel_sizes_equal']
        net_speedup = (result['direct_median_seconds'] /
                       max(result['displaylist_median_seconds'] + build_s, 1e-12))
        meta.update(result)
        meta.update({'displaylist_build_seconds': round(build_s, 5),
                     'rss_before_mib': before, 'rss_after_build_mib': after,
                     'displaylist_rss_increase_mib': delta,
                     'net_speedup_including_build_ratio': round(net_speedup, 3)})
        meta['candidate_benchmarks_acceptable'] = bool(
            parity and net_speedup >= 1.1 and delta is not None and delta <= 64
            and views >= 25)
        if path is None:
            meta['decision'] = 'DEFER'
            meta['reason'] = 'Synthetic input cannot authorize field adoption'
        elif delta is None or views < 25:
            meta['decision'] = 'DEFER'
            meta['reason'] = 'Native RSS or 25 distinct viewports not measured'
        else:
            meta['decision'] = ('FIELD_CANDIDATE_PASS' if
                                meta['candidate_benchmarks_acceptable'] else 'REJECT')
            meta['reason'] = ('Needs full ThreePass cross-state/Windows QA before release'
                              if meta['candidate_benchmarks_acceptable'] else
                              'Speed, parity or native memory gate failed')
        return meta
    finally:
        if temp is not None:
            temp.close()
        if doc is not None:
            doc.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, nargs='?')
    parser.add_argument('--synthetic-arcs', action='store_true')
    parser.add_argument('--layer', action='append', default=[])
    parser.add_argument('--trials', type=int, default=3)
    parser.add_argument('--views', type=int, default=25)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.synthetic_arcs == (args.source is not None):
        parser.error('Provide exactly one of source DXF or --synthetic-arcs')
    if not 3 <= args.trials <= 10 or not 5 <= args.views <= 100:
        parser.error('trials must be 3..10 and views 5..100')
    result = audit(None if args.synthetic_arcs else args.source,
                   args.layer, trials=args.trials, views=args.views)
    if result.get('source_sha256_before') is not None:
        result['source_sha256_after'] = file_hash(args.source)
        result['source_unchanged'] = result['source_sha256_before'] == result['source_sha256_after']
        if not result['source_unchanged']:
            raise AssertionError('Source drawing changed during read-only benchmark')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:result.get(k) for k in ('decision','reason', 'all_pixel_hashes_equal',
        'render_speedup_ratio','net_speedup_including_build_ratio','displaylist_rss_increase_mib')},
        ensure_ascii=False))

if __name__ == '__main__':
    main()
