"""Deterministic real-engine synthetic benchmark; use own source for QA."""
import json, hashlib, tempfile, statistics, time
from pathlib import Path
from unittest.mock import patch
import ezdxf
from drawing_editor.core import DrawingDocument
from drawing_editor.cad_catalog import read_ascii_dxf_layers


def now(): return time.perf_counter()

def build(path, count):
    d=ezdxf.new('R2013');d.layers.new('GRID');d.layers.new('ANNOTATION');m=d.modelspace()
    rows=200; cols=count//rows
    for i in range(cols):
        for j in range(rows):
            x,y=i*100.,j*100.
            m.add_line((x,y),(x+20,y+10),dxfattribs={'layer':'GRID'})
    m.add_text('ANNOTATION',dxfattribs={'layer':'ANNOTATION','height':150,'insert':(cols*50,rows*50)})
    d.saveas(path)


def snapshot(d,clip):
    d._cad_pdf_cache.clear()  # simulate a PDF too large to fit cache
    t=now();out=d.render_bytes(preview=(1000,750),clip=clip)
    return now()-t,hashlib.sha256(out).hexdigest(),out


def measure_one(path,limit):
    from PIL import Image, ImageChops
    from io import BytesIO
    t=now();parsed=read_ascii_dxf_layers(path);catalog=now()-t
    t=now();doc=DrawingDocument(path);full_catalog=now()-t
    try:
        native=[(l.name,l.visible) for l in doc.layers()]
        assert native==[(l.name,l.visible) for l in parsed]
    finally:doc.close()
    records=[]
    for do_index in (False,True):
        with DrawingDocument(path) as d:
            d._cad_recording_attempted=True  # force large CAD safe path
            t=now();d.render_bytes(preview=(850,600)); overview=now()-t
            w,h=d.page_size()
            clips=[(w*.4,h*.3,w*.6,h*.5),(w*.65,h*.52,w*.85,h*.75)]
            if not do_index:
                with patch('drawing_editor.core.CADGridIndex',side_effect=ValueError('Disabled for baseline')):
                    timings=[snapshot(d,c) for c in clips]
            else:
                timings=[snapshot(d,c) for c in clips]
            records.append({'indexed':do_index,'overview_sec':overview,
                            'details_sec':[round(t[0],5) for t in timings],
                            'images':[t[2] for t in timings],
                            'runs':d._cad_spatial_runs})
    pixels_equal=[]
    for old,new in zip(records[0]['images'],records[1]['images']):
        with Image.open(BytesIO(old)) as a,Image.open(BytesIO(new)) as b:
            aa=a.convert('RGB');bb=b.convert('RGB')
            pixels_equal.append(a.size==b.size and ImageChops.difference(aa,bb).getbbox() is None)
    return {'dxf_bytes':path.stat().st_size,'catalog_stream_sec':round(catalog,6),
            'catalog_ezdxf_sec':round(full_catalog,6),
            'overview_before_sec':round(records[0]['overview_sec'],5),
            'overview_after_sec':round(records[1]['overview_sec'],5),
            'detail_full_sec':records[0]['details_sec'],
            'detail_index_sec':records[1]['details_sec'],
            'pixel_equal':pixels_equal,
            'spatial_fast_used':records[1]['runs']==2}

if __name__=='__main__':
    out={}
    with tempfile.TemporaryDirectory() as tmp:
        for count in (8000,24000):
            path=Path(tmp)/f'{count}.dxf';build(path,count)
            result=measure_one(path,count);out[str(count)]=result
            print(count, {k:v for k,v in result.items() if k!='pixel_equal'},flush=True)
            assert all(result['pixel_equal'])
    dest=Path(__file__).with_name('LARGE_CAD_BENCHMARK.json')
    dest.write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8')
