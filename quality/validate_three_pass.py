"""Real DXF 1/2/3-pass validation. Does NOT modify the source DXF.

Usage (Windows CMD or bash):
 python quality/validate_three_pass.py path/to/input.dxf --output report.json --artifacts output_folder
Run against baseline and optimized source trees independently, compare JSON.
"""
from __future__ import annotations
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import time
from collections import Counter

from PIL import Image
try:
    import psutil
except ImportError:
    psutil=None
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drawing_editor.core import DrawingDocument, OutputOptions


def digest_file(path):
    d=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):
            d.update(b)
    return d.hexdigest()


def pixels(blob):
    with Image.open(BytesIO(blob)) as im:
        rgb=im.convert('RGB')
        return dict(size=[rgb.width,rgb.height],pixel_sha256=hashlib.sha256(rgb.tobytes()).hexdigest())


def run(source, artifacts):
    proc=psutil.Process() if psutil else None
    rss=lambda:round(proc.memory_info().rss/1024**2,2) if proc else None
    output={'source_bytes':source.stat().st_size,
            'source_sha256_before':digest_file(source),
            'input_basename':source.name}
    t=time.perf_counter()
    with DrawingDocument(source) as d:
        output['catalog_seconds']=round(time.perf_counter()-t,5)
        output['layer_count']=len(d.layers())
        output['default_on_layers']=sum(v.visible for v in d.layers())
        output['states']={}
        def preview(name):
            t=time.perf_counter();blob=d.render_bytes(preview=(1000,700))
            output['states'][name]=dict(**pixels(blob),seconds=round(time.perf_counter()-t,5),rss_mib=rss(),
                          **({'staged_bytes':d._cad_selective_last_stats.staged_bytes,
                              'selected_records':d._cad_selective_last_stats.selected_entities}
                           if d._cad_selective_last_stats else {}))
            return blob
        start=preview('default')
        # Stage 3: move/zoom repeated, no layer-state changes.
        t=time.perf_counter();r=d.render_bytes(preview=(800,600),clip=(1.0,1.0,40.0,40.0));
        output['zoom']=dict(**pixels(r),seconds=round(time.perf_counter()-t,5))
        t=time.perf_counter();r=d.render_bytes(preview=(800,600),clip=(4.0,4.0,44.0,44.0));
        output['pan']=dict(**pixels(r),seconds=round(time.perf_counter()-t,5))
        d.set_visibility('C0285311', True)
        preview('insert_on')
        t=time.perf_counter();r=d.render_bytes(preview=(800,600),clip=(2.0,2.0,42.0,42.0))
        output['insert_zoom']=dict(**pixels(r),seconds=round(time.perf_counter()-t,5))
        # Phase 3: two simultaneously visible INSERT layers + plain polylines.
        d.set_visibility('G0022312',True)
        preview('two_insert_layers')
        d.set_visibility('G0022312',False)
        preview('insert_restored')
        # Exports include native FHD and 20+ megapixel tiled output.
        output['exports']={}
        for fmt,resolution in (('png','fhd'),('jpg','fhd'),('png','custom')):
            opt=(OutputOptions(fmt=fmt,resolution=resolution)
                 if resolution!='custom'
                 else OutputOptions(fmt=fmt,resolution='custom',width=5500,height=5500))
            target=artifacts/f'{fmt}_{resolution}.{fmt}'
            t=time.perf_counter();d.export_image(target,opt)
            with Image.open(target) as im:
                output['exports'][fmt+'_'+resolution]=dict(size=[im.width,im.height],
                      file_sha256=digest_file(target),seconds=round(time.perf_counter()-t,4),bytes=target.stat().st_size)
        d.set_visibility('C0285311',False)
        finish=preview('default_restored')
        output['restored_identical']=start==finish
    output['source_sha256_after']=digest_file(source)
    output['source_unchanged']=output['source_sha256_after']==output['source_sha256_before']
    return output

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('source');ap.add_argument('--output',required=True)
    ap.add_argument('--artifacts',required=True);args=ap.parse_args()
    folder=Path(args.artifacts);folder.mkdir(parents=True,exist_ok=True)
    result=run(Path(args.source),folder)
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':args.output,'times':{k:v['seconds'] for k,v in result['states'].items()},
                      'zoom':result['zoom']['seconds'],'pan':result['pan']['seconds'],
                      'source_unchanged':result['source_unchanged'],'restored_identical':result['restored_identical']},ensure_ascii=False,indent=2),flush=True)
