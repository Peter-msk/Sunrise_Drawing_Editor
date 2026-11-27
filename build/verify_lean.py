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


def check_alpha_crop(exe, root, originals, worker):
    """Check the four independent PNG background/trim choices through the worker."""
    import fitz
    from PIL import Image, ImageDraw
    source = root / 'alpha-crop.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=400)
        keep = doc.add_ocg('Map', on=1)
        hide = doc.add_ocg('Hide', on=1)
        page.draw_rect(fitz.Rect(100, 100, 300, 300), color=None, fill=(0, 0, 1), oc=keep)
        page.draw_rect(fitz.Rect(150, 150, 250, 250), color=None, fill=(1, 1, 1), oc=keep)
        page.draw_rect(fitz.Rect(5, 5, 20, 20), color=None, fill=(1, 0, 0), oc=hide)
        doc.save(source)
    originals[source] = digest(source)
    for transparent in (True, False):
        for trim in (False, True):
            name = f'alpha-{int(transparent)}-trim-{int(trim)}'
            target = root / (name + '.png')
            jobs = [{'source': str(source), 'states': {keep: True, hide: False},
                     'page_index': 0, 'target': str(target)}]
            worker(exe, root / name, jobs, {'fmt': 'png', 'resolution': 'custom',
                   'width': 400, 'height': 400, 'background': 'transparent' if transparent else 'opaque',
                   'crop_margins': trim})
            mode = 'RGBA' if transparent else 'RGB'
            bg = (0, 0, 0, 0) if transparent else (255, 255, 255)
            blue = (0, 0, 255, 255) if transparent else (0, 0, 255)
            white = (255, 255, 255, 255) if transparent else (255, 255, 255)
            with Image.new(mode, (400, 400), bg) as canvas:
                draw = ImageDraw.Draw(canvas)
                draw.rectangle((100, 100, 299, 299), fill=blue)
                draw.rectangle((150, 150, 249, 249), fill=white)
                expected = canvas.crop((100, 100, 300, 300)) if trim else canvas.copy()
                with expected, Image.open(target) as actual:
                    require(actual.format == 'PNG' and actual.mode == mode and actual.size == expected.size,
                            f'PNG alpha/trim geometry mismatch: {name}')
                    require(actual.tobytes() == expected.tobytes(), f'PNG alpha/trim pixel mismatch: {name}')


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
    check_alpha_crop(exe, root, originals, worker)
    completed.append('png_alpha_crop_independent_pixel_exact')
    source = root / 'layers.dxf'
    doc = ezdxf.new('R2013')
    doc.layers.new('ROAD')
    doc.layers.new('WATER')
    doc.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True, dxfattribs={'layer': 'ROAD'})
    doc.modelspace().add_circle((50, 50), 20, dxfattribs={'layer': 'WATER', 'color': 1})
    doc.saveas(source)
    originals[source] = digest(source)
    # Include default layers: R09's complete snapshot contract also applies to QA.
    cad_states = {str(layer.dxf.name): not layer.is_off() and not layer.is_frozen() for layer in doc.layers}
    cad = [{'source': str(source), 'states': dict(cad_states, ROAD=True, WATER=visible),
            'page_index': 0, 'target': str(root / f'cad-{visible}.png')} for visible in (True, False)]
    worker(exe, root / 'cad', cad, {'fmt': 'png', 'resolution': 'custom', 'width': 400, 'height': 400})
    with Image.open(cad[0]['target']) as x, Image.open(cad[1]['target']) as y:
        require(x.format == y.format == 'PNG' and x.size == y.size, 'CAD image geometry mismatch')
        require(ImageChops.difference(x.convert('RGB'), y.convert('RGB')).getbbox() is not None, 'DXF layer did not change pixels')
    completed.append('dxf_batch_layer_toggle')
    with Image.open(cad[0]['target']) as x, Image.open(cad[1]['target']) as y:
        colors = x.convert('RGB').getcolors(400*400)
        hidden = y.convert('RGB').getcolors(400*400)
        require(colors is not None and any(r>g+80 and r>b+80 for _,(r,g,b) in colors), 'Original DXF red missing')
        require(hidden is not None and not any(r>g+80 and r>b+80 for _,(r,g,b) in hidden), 'Hidden DXF red remains')
    completed.append('dxf_original_color_pixels')
    region = [dict(jobs[0], target=str(root / 'region.png'))]
    worker(exe, root / 'region', region, {'fmt':'png','resolution':'custom','width':400,'height':400,
                                          'region':[.25,.25,.75,.75]})
    check_crop(Path(region[0]['target']), (400,400), (0,0,255))
    completed.append('pdf_region_native_pixels')
    # v1.4.0: require real native outputs; never treat PNG-in-PDF as vector.
    native = [dict(jobs[0], target=str(root / 'native.pdf'))]
    worker(exe, root / 'native-pdf', native, {'fmt':'pdf'})
    with fitz.open(native[0]['target']) as output:
        require(output.page_count == 1 and not output[0].get_images() and bool(output[0].get_drawings()), 'Native PDF paths missing')
        require({k: bool(v['on']) for k,v in output.get_ocgs().items()} == jobs[0]['states'], 'Saved PDF OCG state mismatch')
        pix = output[0].get_pixmap()
        require(pix.pixel(10,10) == (255,255,255) and pix.pixel(150,150) == (0,0,255), 'PDF visibility pixels mismatch')
    completed.append('pdf_native_vector_ocg')
    svg = [dict(jobs[0], target=str(root / 'visible.svg'))]
    worker(exe, root / 'native-svg', svg, {'fmt':'svg'})
    import xml.etree.ElementTree as ET
    svg_text = Path(svg[0]['target']).read_text(encoding='utf-8')
    require(any(node.tag.endswith('}path') for node in ET.fromstring(svg_text).iter()) and '#0000ff' in svg_text and '#ff0000' not in svg_text, 'SVG visible paths mismatch')
    completed.append('svg_visible_paths')
    # Includes the default layers because native export requires complete state.
    source_doc = ezdxf.readfile(source)
    states = {str(layer.dxf.name): str(layer.dxf.name) == 'ROAD' for layer in source_doc.layers}
    vector = [dict(cad[0], states=states, target=str(root / 'selected.dxf'))]
    worker(exe, root / 'native-dxf', vector, {'fmt':'dxf'})
    output = ezdxf.readfile(vector[0]['target'])
    entities = list(output.modelspace())
    require(len(entities) == 1 and entities[0].dxftype() == 'LWPOLYLINE' and entities[0].dxf.layer == 'ROAD', 'DXF selected entity mismatch')
    require([tuple(p) for p in entities[0].get_points('xy')] == [(0,0),(100,0),(100,100),(0,100)], 'DXF coordinates mismatch')
    require(output.units == source_doc.units and not output.audit().has_errors, 'DXF unit/structure mismatch')
    completed.append('dxf_selected_coordinates')
    # R03: exercise the compound object's native output in the same actual
    # packaged worker path. Older 1.4.0 release evidence remains readable.
    compound_source = root / 'compound.dxf'
    compound = ezdxf.new('R2013')
    compound.units = 6
    compound.layers.new('ROAD')
    compound.styles.get('Standard').dxf.font = 'custom.shx'
    block = compound.blocks.new('SURVEY', base_point=(1, 2, 0))
    block.block_record.dxf.units = 6
    block.add_circle((3, 4), 2)
    m = compound.modelspace()
    m.add_blockref('SURVEY', (200000, 500000, 7), dxfattribs={'layer':'ROAD', 'rotation':35})
    m.add_text('SURVEY', dxfattribs={'layer':'ROAD', 'insert':(200000, 500010)})
    m.add_mtext('Survey\\Ppoint', dxfattribs={'layer':'ROAD'})
    hatch = m.add_hatch(dxfattribs={'layer':'ROAD'})
    hatch.set_pattern_fill('ANSI31', scale=2, angle=17)
    hatch.paths.add_polyline_path([(0,0), (5,0), (5,5)], is_closed=True)
    compound.saveas(compound_source)
    originals[compound_source] = digest(compound_source)
    compound_job = [{'source': str(compound_source), 'states': {str(l.dxf.name): True for l in compound.layers},
                     'page_index': 0, 'target': str(root / 'compound-output.dxf')}]
    worker(exe, root / 'compound-dxf', compound_job, {'fmt':'dxf'})
    compound_output = ezdxf.readfile(compound_job[0]['target'])
    from ezdxf.lldxf.tagwriter import TagCollector
    def comparable(entity):
        return [(tag.code, tag.value) for tag in TagCollector.dxftags(entity)
                if tag.code not in (5, 330, 390, 347, 348)]
    compound_input = ezdxf.readfile(compound_source)
    require([comparable(e) for e in compound_input.modelspace()] == [comparable(e) for e in compound_output.modelspace()], 'Compound modelspace data mismatch')
    require([comparable(e) for e in compound_input.blocks['SURVEY']] == [comparable(e) for e in compound_output.blocks['SURVEY']], 'Compound block data mismatch')
    require(compound_output.blocks['SURVEY'].block_record.dxf.units == 6 and compound_output.styles.get('Standard').dxf.font == 'custom.shx', 'Compound resource mismatch')
    audit = compound_output.audit()
    require(not audit.has_errors and not audit.fixes, 'Compound output audit failed')
    completed.append('dxf_compound_native')
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
    # A distinct protocol return code prevents old binaries accepting unknown CLI arguments.
    from pe_version import expected_version
    version = expected_version()['strings']['ProductVersion']
    result = subprocess.run([str(exe), '--verify-update-version', version],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=120)
    require(result.returncode == 42, 'Packaged executable version protocol failed')
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
