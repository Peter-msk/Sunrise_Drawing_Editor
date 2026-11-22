"""Native vector output contracts exercised through real source workers."""
import sys, tempfile, unittest, hashlib, xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fitz, ezdxf
from drawing_editor.core import DrawingDocument, DrawingError, OutputOptions, source_signature
from drawing_editor.state import DrawingState
from drawing_editor.layer_tools import plan_advanced_exports
from drawing_editor.batch_worker import run_batch_exports_isolated
from drawing_editor.drawing_analysis import save_profile, load_profile

class VectorTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
    def state(self,p):
        s=DrawingState(p)
        with DrawingDocument(p) as d:s.load_metadata(d.layers(),d.pages)
        return s
    def pdf(self):
        p=self.root/'source.pdf'
        with fitz.open() as d:
            a=d.add_ocg('ROAD',on=True);b=d.add_ocg('WATER',on=True)
            for i in range(2):
                page=d.new_page(width=100,height=100);page.draw_rect(fitz.Rect(0,0,50,100),fill=(1,0,0),color=None,oc=a);page.draw_rect(fitz.Rect(50,0,100,100),fill=(0,0,1),color=None,oc=b);page.insert_text((5,10),'TEXT');page.set_rotation(i*90)
            d.save(p)
        s=self.state(p);s.set_visibility(a,False);return s,a,b
    def dxf(self,unsupported=False):
        p=self.root/'model.dxf';d=ezdxf.new('R2013');d.units=6;d.layers.new('ROAD',dxfattribs={'color':1});d.layers.new('WATER');m=d.modelspace();m.add_line((200000,500000,7),(200010,500020,8),dxfattribs={'layer':'ROAD'});m.add_circle((200000,500000),4,dxfattribs={'layer':'WATER'});m.add_lwpolyline([(200001,500001,0.2),(200003,500005,0)],format='xyb',dxfattribs={'layer':'ROAD'});d.layout().add_circle((0,0),99)
        if unsupported:m.add_xline((0,0),(1,0),dxfattribs={'layer':'ROAD'})
        d.saveas(p);s=self.state(p);s.set_visibility('WATER',False);return s
    def export(self,d,fmt,**params):
        opts=OutputOptions(fmt=fmt);jobs=plan_advanced_exports([d],self.root,opts,**params);r=run_batch_exports_isolated(jobs,opts);self.assertFalse(r.errors,r);return [Path(p) for p in r.completed]
    def sha(self,p):return hashlib.sha256(p.read_bytes()).hexdigest()
    def test_pdf_native_page_ocg_and_hidden_retained(self):
        d,a,b=self.pdf();old=self.sha(d.path);d.page_index=1;out=self.export(d,'pdf')[0]
        with fitz.open(out) as p:
            self.assertEqual(p.page_count,1);self.assertEqual(p[0].rotation,90);self.assertEqual(p.get_ocgs()[a]['on'],False);self.assertEqual(p.get_ocgs()[b]['on'],True);self.assertIn('TEXT',p[0].get_text());self.assertEqual(p[0].get_images(),[]);self.assertTrue(p[0].get_drawings());pix=p[0].get_pixmap();self.assertEqual(pix.pixel(50,25),(255,255,255));self.assertEqual(pix.pixel(50,75),(0,0,255))
        self.assertEqual(self.sha(d.path),old)
    def test_svg_visible_native_paths(self):
        d,a,b=self.pdf();old=self.sha(d.path);paths=self.export(d,'svg',scope='all');self.assertEqual(len(paths),2)
        for p in paths:
            root=ET.parse(p).getroot();data=p.read_text();self.assertTrue(any(el.tag.endswith('}path') for el in root.iter()));self.assertIn('#0000ff',data);self.assertNotIn('#ff0000',data);self.assertNotIn('<image',data)
        self.assertEqual(self.sha(d.path),old)
    def test_pdf_without_layers_hybrid_content(self):
        from PIL import Image
        from io import BytesIO
        p=self.root/'hybrid.pdf'
        with fitz.open() as d:
            page=d.new_page(width=100,height=100)
            with Image.new('RGB',(8,8),(0,255,0)) as im, BytesIO() as buf:
                im.save(buf,format='PNG');page.insert_image(fitz.Rect(0,0,30,30),stream=buf.getvalue())
            page.draw_rect(fitz.Rect(50,50,90,90),fill=(0,0,1),color=None);d.save(p)
        d=self.state(p);old=self.sha(p)
        native=self.export(d,'pdf')[0];svg=self.export(d,'svg')[0]
        with fitz.open(native) as f:
            self.assertTrue(f[0].get_images());self.assertTrue(f[0].get_drawings())
        tags={el.tag.rsplit('}',1)[-1] for el in ET.parse(svg).getroot().iter()}
        self.assertTrue({'image','path'} <= tags);self.assertEqual(self.sha(p),old)
    def test_pdf_hidden_data_can_be_reenabled(self):
        d,a,b=self.pdf();native=self.export(d,'pdf')[0]
        # This is a deliberate contract, not a sanitizing export.
        with fitz.open(native) as f:
            f.set_layer_ui_config(next(i['number'] for i in f.layer_ui_configs() if i['text']=='ROAD'),action=0)
            self.assertEqual(f[0].get_pixmap().pixel(20,50),(255,0,0))
    def test_dxf_coordinates_units_geometry_only(self):
        d=self.dxf();old=self.sha(d.path);out=self.export(d,'dxf')[0];result=ezdxf.readfile(out);m=result.modelspace();self.assertEqual(result.units,6);self.assertEqual(len(m),2);self.assertEqual(tuple(m.query('LINE')[0].dxf.start),(200000,500000,7));self.assertEqual(tuple(m.query('LINE')[0].dxf.end),(200010,500020,8));self.assertEqual(list(m.query('LWPOLYLINE')[0].get_points('xyb'))[0][2],.2);self.assertEqual(result.layers.get('ROAD').dxf.color,1);self.assertFalse(result.audit().has_errors);self.assertFalse(len(result.layout()));self.assertEqual(self.sha(d.path),old)
    def test_unsupported_selected_dxf_fails_without_partial(self):
        d=self.dxf(True);o=OutputOptions(fmt='dxf');j=plan_advanced_exports([d],self.root,o);r=run_batch_exports_isolated(j,o);self.assertEqual(len(r.errors),1);self.assertIn('XLINE',r.errors[0][1]);self.assertFalse(Path(j[0].target).exists());self.assertFalse(list(self.root.glob('.drawing-*')))
    def test_format_options_and_source_preflight(self):
        d,_,_=self.pdf()
        for opts in (OutputOptions(fmt='pdf',resolution='dpi',dpi=300),OutputOptions(fmt='svg',region=(0,0,1,1)),OutputOptions(fmt='dxf',background='transparent')):
            with self.assertRaises(DrawingError):opts.checked()
        with self.assertRaises(DrawingError):plan_advanced_exports([d],self.root,OutputOptions(fmt='dxf'))
    def test_cancel_collision_and_stale(self):
        d,_,_=self.pdf();o=OutputOptions(fmt='svg');j=plan_advanced_exports([d],self.root,o);target=Path(j[0].target);r=run_batch_exports_isolated(j,o,cancelled=lambda:True);self.assertTrue(r.cancelled);self.assertFalse(target.exists());target.write_text('protected');r=run_batch_exports_isolated(j,o);self.assertTrue(r.errors);self.assertEqual(target.read_text(),'protected');target.unlink();d.path.write_bytes(d.path.read_bytes()+b'\n');r=run_batch_exports_isolated(j,o);self.assertTrue(r.errors);self.assertFalse(target.exists())
    def test_vector_profile_compatibility(self):
        p=self.root/'v.sdeprofile';o=OutputOptions(fmt='svg');save_profile(p,o,mode='current',scope='all',page_range='',groups=[],rules=[]);self.assertEqual(load_profile(p)[0],o)
if __name__=='__main__':unittest.main(verbosity=2)
