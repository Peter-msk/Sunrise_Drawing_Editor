"""Exercise the actual packaged batch worker with generated, disposable drawings."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import sys


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run_batch(exe, root, jobs, options, cancel=False):
    root.mkdir()
    (root / 'request.json').write_text(json.dumps({'jobs': jobs, 'options': options}), encoding='utf-8')
    if cancel:
        (root / 'cancel.flag').touch()
    proc = subprocess.Popen([str(exe), '--batch-worker', str(root)], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        rc = proc.wait(timeout=240)
    except subprocess.TimeoutExpired:
        if sys.platform == 'win32' and proc.poll() is None:
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                           capture_output=True, timeout=15, check=False)
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=15)
        raise RuntimeError('Packaged worker timed out')
    require(rc == 0, f'Worker exit {rc}')
    response = json.loads((root / 'result.json').read_text(encoding='utf-8'))
    require(response.get('ok') is True, str(response.get('error', 'worker failed')))
    result = response['result']
    require(not result['errors'] and result['cancelled'] is cancel, str(result))
    require(len(result['completed']) == (0 if cancel else len(jobs)), 'Incomplete batch')
    require(all(Path(j['target']).is_file() != cancel for j in jobs), 'Missing or unexpected output')


def check_crop(path, expected_size, color):
    from PIL import Image, ImageChops
    with Image.open(path) as image:
        require(image.format == 'PNG' and image.size == expected_size, f'Wrong cropped size: {path.name} {image.size}')
        rgb = image.convert('RGB')
        expected = Image.new('RGB', rgb.size, color)
        try:
            require(ImageChops.difference(rgb, expected).getbbox() is None, f'Unexpected pixels: {path.name}')
        finally:
            rgb.close()
            expected.close()


def exercise(exe, root, worker=run_batch):
    import fitz
    import ezdxf
    from PIL import Image, ImageChops
    completed = []
    jobs, originals = [], {}
    for n in range(4):
        source = root / f'sheet-{n}.pdf'
        with fitz.open() as doc:
            page = doc.new_page(width=400, height=400)
            page.draw_rect(fitz.Rect(1, 1, 399, 399), color=None, fill=(1, 1, 1))
            keep = doc.add_ocg('Map', on=1)
            hide = doc.add_ocg('Hide', on=1)
            page.draw_rect(fitz.Rect(60+n*10, 70, 300, 310), color=None, fill=(0, 0, 1), oc=keep)
            page.draw_rect(fitz.Rect(5, 5, 20, 20), color=None, fill=(1, 0, 0), oc=hide)
            doc.save(source)
        originals[source] = digest(source)
        jobs.append({'source': str(source), 'states': {keep: True, hide: False},
                     'page_index': 0, 'target': str(root / f'crop-{n}.png')})
    worker(exe, root / 'png', jobs, {'fmt': 'png', 'resolution': 'custom', 'width': 3600,
                                    'height': 3600, 'crop_margins': True})
    for n, job in enumerate(jobs):
        check_crop(Path(job['target']), ((240-n*10)*9, 2160), (0, 0, 255))
    completed.append('four_pdf_ocg_png_crop_pixel_exact')
    jpg = [dict(j, target=str(root / f'full-{n}.jpg')) for n, j in enumerate(jobs)]
    worker(exe, root / 'jpg', jpg, {'fmt': 'jpg', 'resolution': 'custom', 'width': 400, 'height': 400})
    for j in jpg:
        with Image.open(j['target']) as im:
            require(im.format == 'JPEG' and im.size == (400, 400), 'Wrong JPG format or size')
            require(min(im.convert('RGB').getpixel((10, 10))) > 240, 'Hidden red OCG still visible')
    completed.append('four_pdf_jpg_hidden_ocg')
    source = root / 'layers.dxf'
    doc = ezdxf.new('R2013')
    doc.layers.new('ROAD')
    doc.layers.new('WATER')
    doc.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True, dxfattribs={'layer': 'ROAD'})
    doc.modelspace().add_circle((50, 50), 20, dxfattribs={'layer': 'WATER', 'color': 1})
    doc.saveas(source)
    originals[source] = digest(source)
    cad = [{'source': str(source), 'states': {'ROAD': True, 'WATER': visible},
            'page_index': 0, 'target': str(root / f'cad-{visible}.png')} for visible in (True, False)]
    worker(exe, root / 'cad', cad, {'fmt': 'png', 'resolution': 'custom', 'width': 400, 'height': 400})
    with Image.open(cad[0]['target']) as x, Image.open(cad[1]['target']) as y:
        require(x.format == y.format == 'PNG' and x.size == y.size, 'CAD image geometry mismatch')
        require(ImageChops.difference(x.convert('RGB'), y.convert('RGB')).getbbox() is not None, 'DXF layer did not change pixels')
    completed.append('dxf_batch_layer_toggle')
    cancel = [dict(jobs[0], target=str(root / 'cancelled.png'))]
    worker(exe, root / 'cancel', cancel, {'fmt': 'png'}, cancel=True)
    require(not list(root.glob('.drawing-*')), 'Partial export remains')
    completed.append('pre_cancel_no_output')
    require(all(digest(p) == old for p, old in originals.items()), 'Original drawing changed')
    completed.append('source_sha256_preserved')
    return completed


def verify(exe):
    exe = exe.resolve(strict=True)
    before = digest(exe)
    with tempfile.TemporaryDirectory(prefix='sunrise-r24-qa-') as tmp:
        passed = exercise(exe, Path(tmp))
    require(digest(exe) == before, 'EXE changed during verification')
    return {'schema_version': 1, 'sha256': before, 'checks_passed': passed,
            'status': 'SYNTHETIC_PACKAGED_BATCH_PASS_FULL_QA_PENDING',
            'not_run': ['actual_user_onmap', 'dwg_with_real_converter', 'large_400MiB_dxf',
                        'cad_preview_worker', 'mid_export_cancel', 'gui_dpi_theme_rdp',
                        'external_rasters', 'live_github_tls', 'trusted_update_rollback', 'performance_antivirus']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('exe', type=Path)
    p.add_argument('report', type=Path)
    args = p.parse_args()
    try:
        result = verify(args.exe)
        with args.report.open('x', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        print('[PASS] Packaged synthetic drawing QA:', args.report)
        return 0
    except Exception as exc:
        print('[ERROR] Packaged drawing QA:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
