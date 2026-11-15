"""Stage14: OnMap PDF render isolation + rapid toggle + vector UI contracts.

Synthetic page/color checks prove PDF OCG integer xrefs survive native IPC.
Real user's OnMap PDF and Windows GUI video must be re-tested separately.
"""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import ast
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
WINDOW=(ROOT/'drawing_editor/window.py').read_text(encoding='utf-8')
CAD=(ROOT/'drawing_editor/cad_worker.py').read_text(encoding='utf-8')
WINDOW_TREE=ast.parse(WINDOW)
WINDOW_CLASS=next(x for x in WINDOW_TREE.body if isinstance(x,ast.ClassDef)
                  and x.name=='DrawingWindow')


def method(name):
    node=next(x for x in WINDOW_CLASS.body
              if isinstance(x,ast.FunctionDef) and x.name==name)
    return ast.get_source_segment(WINDOW,node)


class Stage14UiAndWorkScheduling(unittest.TestCase):
    def test_one_toggle_and_multi_toggle_are_coalesced(self):
        self.assertIn('self.preview_timer.start(260 if layer_interaction else 110)',
                      method('request_preview'))
        for name in ('_layer_changed','set_filtered_layers','set_all_layers'):
            self.assertIn('self.request_preview(layer_interaction=True)',method(name))
        self.assertIn('self._preview_cancel.set()',method('request_preview'))

    def test_layered_pdf_runs_outside_gui_native_process(self):
        self.assertIn('self._isolate_pdf or should_isolate_cad(self.path)',
                      WINDOW)
        self.assertIn("isolate_pdf=(doc.kind == 'pdf' and bool(doc.layers()))",
                      method('_start_preview'))
        self.assertIn("isolate_pdf=(doc.kind == 'pdf' and bool(doc.layers()))",
                      method('_start_detail'))
        self.assertIn('render_isolated(',WINDOW)
        self.assertIn('subprocess.Popen(',CAD)
        self.assertIn('states = {int(key): bool(value)',CAD)
        self.assertIn('req["path"], states, int(req["page"])',CAD)

    def test_stale_preview_never_overwrites_current_state(self):
        self.assertIn('if seq==self._preview_seq and not self._preview_pending:',
                      method('_success'))
        self.assertIn('if self._preview_pending:self._start_preview()',
                      method('_success'))

    def test_layer_checkbox_custom_checked_unchecked_and_hover(self):
        theme=method('_apply_theme')
        for tag in (
            'QTreeWidget::indicator:checked,QCheckBox::indicator:checked',
            'QTreeWidget::indicator:unchecked:hover',
            'QTreeWidget::indicator:disabled,QCheckBox::indicator:disabled',
            'image:url("{tick_icon}")',
            'tick_icon = (ASSETS/\'checkbox_tick_white.svg\')',
        ):
            self.assertIn(tag,theme)

    def test_vector_icon_theme_and_semantic_coverage(self):
        names=('add','apply','delete','deselect','drawing','export','fit','folder',
               'hidden','moon','next','prev','remove','save','search',
               'select_all','sun','visible','zoom_in','zoom_out')
        for name in names:
            for variant in ('','_light','_dark'):
                path=ROOT/'assets'/f'icon_{name}{variant}.svg'
                with self.subTest(name=path.name):
                    root=ET.parse(path).getroot()
                    self.assertEqual(root.attrib.get('viewBox'),'0 0 24 24')
                    self.assertTrue(len(root)>0)
                    self.assertEqual(root[0].tag.split('}')[-1],'g')
                    self.assertTrue(root[0].attrib.get('transform','').startswith('translate('))
        for file in ('icon_export_white.svg','icon_stop_white.svg','checkbox_tick_white.svg'):
            ET.parse(ROOT/'assets'/file)
        # Removing a file from a list is explicitly NOT deleting a rule.
        self.assertNotEqual(
            (ROOT/'assets'/'icon_remove_light.svg').read_bytes(),
            (ROOT/'assets'/'icon_delete_light.svg').read_bytes())
        self.assertNotEqual(
            (ROOT/'assets'/'icon_add_light.svg').read_bytes(),
            (ROOT/'assets'/'icon_folder_light.svg').read_bytes())
        self.assertNotEqual(
            (ROOT/'assets'/'icon_add_dark.svg').read_bytes(),
            (ROOT/'assets'/'icon_add_light.svg').read_bytes())


class Stage14PDFWorkerRoundTrip(unittest.TestCase):
    def test_layer_off_and_back_on_using_real_isolated_worker(self):
        import fitz
        from drawing_editor.cad_worker import render_isolated,shutdown_all_workers
        from PIL import Image
        with tempfile.TemporaryDirectory(prefix='sunrise-stage14-ocg-') as temp:
            source=Path(temp)/'onmap-layered.pdf'
            with fitz.open() as pdf:
                page=pdf.new_page(width=240,height=180)
                ids=[]
                for i in range(11):
                    xref=pdf.add_ocg(f'Layer {i}',on=1)
                    ids.append(xref)
                    x0=20+(i%5)*35
                    y0=22+(i//5)*42
                    page.draw_rect(fitz.Rect(x0,y0,x0+23,y0+23),
                                   color=(0.9,0.1,0.1),fill=(0.9,0.1,0.1),oc=xref)
                pdf.save(source)
            all_on={key:True for key in ids}
            one_off=dict(all_on);one_off[ids[0]]=False
            try:
                p1,g1=render_isolated('preview',str(source),all_on,0,(480,360))
                p2,g2=render_isolated('preview',str(source),one_off,0,(480,360))
                p3,g3=render_isolated('preview',str(source),all_on,0,(480,360))
                self.assertEqual(g1,g2)
                self.assertEqual(g1,g3)
                self.assertNotEqual(p1,p2)
                self.assertEqual(p1,p3)
                with Image.open(BytesIO(p1)) as result:
                    self.assertEqual(result.size,(480,360))
                with Image.open(BytesIO(p2)) as result:
                    self.assertEqual(result.size,(480,360))
            finally:
                shutdown_all_workers()


if __name__=='__main__':
    unittest.main()
