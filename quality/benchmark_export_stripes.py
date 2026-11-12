"""Reproducible isolated BEFORE/AFTER stripe benchmark (no benchmark claims on real 100MB drawings)."""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import json
import statistics
import struct
import tempfile
import time
import zlib

import fitz
import numpy as np
from PIL import Image, ImageChops
from drawing_editor.tiles import save_png_tiled


def legacy_stripes(page, width, height, edge=512):
    rect=page.rect
    sx,sy=width/rect.width,height/rect.height
    matrix=fitz.Matrix(sx,sy)
    base=fitz.IRect((rect*matrix).irect)
    edge_y=max(1,min(edge,12_000_000//max(3,width*3)))
    for y0 in range(0,height,edge_y):
        y1=min(height,y0+edge_y)
        stripe=bytearray(b'\xff'*(width*(y1-y0)*3))
        for x0 in range(0,width,edge):
            x1=min(width,x0+edge)
            halo=2
            cx0,cy0=max(0,x0-halo),max(0,y0-halo)
            cx1,cy1=min(width,x1+halo),min(height,y1+halo)
            clip=fitz.Rect(rect.x0+cx0/sx,rect.y0+cy0/sy,
                           rect.x0+cx1/sx,rect.y0+cy1/sy)
            pix=page.get_pixmap(matrix=matrix,clip=clip,colorspace=fitz.csRGB,
                                alpha=False,annots=True)
            px0,py0=pix.irect[0]-base.x0,pix.irect[1]-base.y0
            left,right=max(0,px0),min(width,px0+pix.width)
            top,bottom=max(y0,py0),min(y1,py0+pix.height)
            if right<=left or bottom<=top:continue
            src=pix.samples_mv
            count=(right-left)*3
            for yy in range(top,bottom):
                i=((yy-py0)*pix.width+left-px0)*3
                j=((yy-y0)*width+left)*3
                stripe[j:j+count]=src[i:i+count]
            del src
        yield y0,y1,stripe


def _chunk(stream,label,data):
    stream.write(struct.pack('!I',len(data)))
    stream.write(label)
    stream.write(data)
    stream.write(struct.pack('!I',zlib.crc32(data,zlib.crc32(label))&0xffffffff))


def baseline_png(page,output,w,h,dpi):
    output.write(b'\x89PNG\r\n\x1a\n')
    _chunk(output,b'IHDR',struct.pack('!IIBBBBB',w,h,8,2,0,0,0))
    ppm=round(dpi/.0254)
    _chunk(output,b'pHYs',struct.pack('!IIB',ppm,ppm,1))
    enc=zlib.compressobj(level=4)
    buf=[];sz=0
    for y0,y1,stripe in legacy_stripes(page,w,h):
        for n in range(y1-y0):
            start=n*w*3
            compressed=enc.compress(b'\x00'+stripe[start:start+w*3])
            if compressed:buf.append(compressed);sz+=len(compressed)
            if sz>=256_000:
                _chunk(output,b'IDAT',b''.join(buf));buf=[];sz=0
    buf.append(enc.flush())
    if buf:_chunk(output,b'IDAT',b''.join(buf))
    _chunk(output,b'IEND',b'')


class CountPage:
    def __init__(self,page):
        self.page=page
        self.rect=page.rect
        self.calls=0
    def get_pixmap(self,**kwargs):
        self.calls+=1
        return self.page.get_pixmap(**kwargs)


def benchmark():
    result={'kind':'synthetic vector PDF (not real OnMap)',
            'canvas_points':[600,850], 'export_pixels':[2500,3542],
            'runs_each':2, 'environment':'local Linux engine', 'records':{}}
    with fitz.open() as pdf:
        page=pdf.new_page(width=600,height=850)
        shape=page.new_shape()
        for i in range(1100):
            y=30+(i%120)*6.6
            x=(i*7)%430
            shape.draw_line((x,y),(x+130,y+((i%11)-5)*2))
        shape.finish(color=(.25,.4,.6),width=.65)
        shape.commit()
        out={}
        for key,fn in [('before',baseline_png),('after',save_png_tiled)]:
            times=[];pixels=None;number=None
            for i in range(2):
                counted=CountPage(page)
                output=BytesIO()
                t0=time.perf_counter()
                fn(counted,output,2500,3542,300)
                times.append(time.perf_counter()-t0)
                number=counted.calls
                if i==0:pixels=output.getvalue()
            out[key]=pixels
            result['records'][key]={
                'times_seconds':[round(t,5) for t in times],
                'median_seconds':round(statistics.median(times),5),
                'get_pixmap_calls':number,
                'png_bytes':len(pixels)}
        a=Image.open(BytesIO(out['before'])).convert('RGB')
        b=Image.open(BytesIO(out['after'])).convert('RGB')
        pix=page.get_pixmap(matrix=fitz.Matrix(2500/600,3542/850),
                            colorspace=fitz.csRGB,alpha=False,annots=True)
        reference=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        result['image_test']={'dimensions_match':a.size==b.size==reference.size}
        for title,img in [('before',a),('after',b)]:
            diff=np.abs(np.asarray(img,dtype=np.int16)-np.asarray(reference,dtype=np.int16))
            result['image_test'][title+'_vs_direct']={
                'changed_pixel_fraction':round(float(np.any(diff!=0,axis=2).mean()),6),
                'mean_absolute_channel_delta':round(float(diff.mean()),6),
                'max_channel_delta':int(diff.max())}
        ab=np.abs(np.asarray(a,dtype=np.int16)-np.asarray(b,dtype=np.int16))
        result['image_test']['before_vs_after']={
            'changed_pixel_fraction':round(float(np.any(ab!=0,axis=2).mean()),6),
            'max_channel_delta':int(ab.max())}
        result['median_speedup']=round(result['records']['before']['median_seconds']/result['records']['after']['median_seconds'],2)
    return result


if __name__=='__main__':
    r=benchmark()
    path=Path(__file__).resolve().parent/'EXPORT_STRIPE_BENCHMARK.json'
    path.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(r,ensure_ascii=False,indent=2))
