"""R05 byte-exact staging, tiled raster and strict preview IPC regression."""
import hashlib
import mmap
import os
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ezdxf
import fitz
from PIL import Image
from drawing_editor.cad_selective import (VisibleDXFSource, SelectiveDXFUnsupported,
    SelectiveDXFCancelled, _write_span, _write_selected_entities, _ENTITY_WRITE_CHUNK)
from drawing_editor import cad_worker, tiles
from drawing_editor.core import DrawingError, source_signature

class R05Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(cad_worker.close_thread_worker)
        self.root = Path(self.temp.name)

    def dxf(self):
        path = self.root/'source.dxf'
        doc = ezdxf.new('R2013')
        for name in ('ROAD','WATER','TREE'): doc.layers.new(name)
        for i in range(120):
            doc.modelspace().add_line((i, i+1), (i+2, i+3), dxfattribs={'layer':'ROAD' if i < 10 else 'WATER' if i < 100 else 'TREE'})
        doc.saveas(path)
        path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
        return path

    def test_staging_sparse_dense_and_repeated(self):
        path = self.dxf(); before = hashlib.sha256(path.read_bytes()).digest()
        source = VisibleDXFSource(path)
        for layers, count in ((['ROAD'],10),(['WATER','TREE'],110),(['ROAD','WATER','TREE'],120),(['ROAD'],10)):
            target = self.root/'stage.dxf'
            stats = source.stage(target,layers)
            result = list(ezdxf.readfile(target).modelspace())
            original = [e for e in ezdxf.readfile(path).modelspace() if e.dxf.layer in layers]
            self.assertEqual(stats.selected_entities,count)
            self.assertEqual([(e.dxf.layer,e.dxf.start,e.dxf.end) for e in result],[(e.dxf.layer,e.dxf.start,e.dxf.end) for e in original])
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)

    def test_large_span_exact_and_cancel(self):
        p=self.root/'source.raw'; q=self.root/'dest.raw'
        payload=(bytes(range(256))*(_ENTITY_WRITE_CHUNK//256+1))*3
        p.write_bytes(payload)
        with p.open('rb') as fp, mmap.mmap(fp.fileno(),0,access=mmap.ACCESS_READ) as source:
            with q.open('wb') as out:_write_span(out,source,13,len(payload)-19)
            self.assertEqual(q.read_bytes(),payload[13:-19])
            checks=iter([False,True])
            with q.open('wb') as out, self.assertRaises(SelectiveDXFCancelled):
                _write_span(out,source,0,len(payload),cancelled=lambda:next(checks))
            self.assertEqual(q.stat().st_size,_ENTITY_WRITE_CHUNK)
            with q.open('wb') as out:
                _write_selected_entities(out,source,[(0,len(payload),b'LINE','road')])
            self.assertEqual(q.read_bytes(),payload)

    def test_short_write_rejected(self):
        class Short:
            def write(self,data): return len(data)-1
        p=self.root/'source.raw';p.write_bytes(b'123456789')
        with p.open('rb') as fp,mmap.mmap(fp.fileno(),0,access=mmap.ACCESS_READ) as source:
            with self.assertRaises(OSError):_write_span(Short(),source,0,9)

    def test_same_size_mtime_replacement(self):
        p=self.dxf(); source=VisibleDXFSource(p); info=p.stat()
        replacement=self.root/'replacement.dxf';replacement.write_bytes(p.read_bytes());os.utime(replacement,ns=(info.st_atime_ns,info.st_mtime_ns));os.replace(replacement,p)
        with self.assertRaises(SelectiveDXFUnsupported):source.stage(self.root/'stage.dxf',['ROAD'])
        self.assertFalse((self.root/'stage.dxf').exists())

    def test_tiled_rotated_transparency_pixels(self):
        with fitz.open() as pdf:
            page=pdf.new_page(width=120,height=80)
            page.draw_rect(fitz.Rect(10,10,110,70), fill=(1,0,0),color=None,fill_opacity=.5)
            page.set_rotation(90)
            for alpha in (False,True):
                width,height=800,1200
                matrix=fitz.Matrix(width/page.rect.width,height/page.rect.height)
                native=page.get_pixmap(matrix=matrix,alpha=alpha)
                stripes=b''.join(s for _,_,s in tiles.raster_stripes(page,width,height,edge=128,transparent=alpha))
                self.assertEqual(stripes,native.samples)

    def test_invalid_ipc_then_recover(self):
        p=self.root/'source.pdf'
        with fitz.open() as pdf:
            oc=pdf.add_ocg('ROAD');page=pdf.new_page(width=100,height=100)
            page.draw_rect(fitz.Rect(10,10,90,90),color=None,fill=(1,0,0),oc=oc);pdf.save(p)
        sig=source_signature(p)
        for states, index in (({oc:'false'},0),({oc:True},False),({oc:True},0.5),({str(oc):True,'0'+str(oc):False},0)):
            with self.assertRaises(DrawingError):cad_worker.render_isolated('preview',str(p),states,index,(100,100),expected_source=sig)
        data,geom=cad_worker.render_isolated('preview',str(p),{oc:False},0,(100,100),expected_source=sig)
        import io
        with Image.open(io.BytesIO(data)) as img:self.assertEqual(img.getpixel((50,50)),(255,255,255))
        self.assertEqual(geom,(100,100))

if __name__=='__main__':unittest.main(verbosity=2)
