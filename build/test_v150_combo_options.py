"""R07 regressions: the confirmation, plan, profile and real output share one PNG crop contract.
Qt widget checks are deliberately skipped when the actual Qt runtime is unavailable.
"""
import hashlib
import importlib.util
import os
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz
from PIL import Image
from drawing_editor.core import (DrawingDocument, DrawingError, LayerInfo, OutputOptions,
                                 close_thread_document)
from drawing_editor.state import DrawingState
from drawing_editor.layer_tools import plan_advanced_exports
from drawing_editor.batch_worker import run_batch_exports_isolated
from drawing_editor.cad_worker import shutdown_all_workers
from drawing_editor.drawing_analysis import save_profile, load_profile, checked_profile


class CombinationRasterExportTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.addCleanup(close_thread_document)
        self.addCleanup(shutdown_all_workers)
        self.root=Path(t.name)
        self.source=self.root/'map.pdf'
        with fitz.open() as pdf:
            road=pdf.add_ocg('ROAD'); water=pdf.add_ocg('WATER')
            page=pdf.new_page(width=100,height=100)
            page.draw_rect(fitz.Rect(23,24,45,77),color=None,fill=(1,0,0),oc=road)
            page.draw_rect(fitz.Rect(55,24,77,77),color=None,fill=(0,0,1),oc=water)
            pdf.save(self.source)
        self.digest=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.doc=DrawingState(self.source)
        with DrawingDocument(self.source) as source:
            self.doc.load_metadata(source.layers(),source.pages)
        self.opts=OutputOptions(fmt='png',resolution='custom',width=400,height=400,
                                background='transparent')

    def run_export(self, options, *, mode='layers'):
        directory=self.root/(f'{mode}-{options.fmt}-{options.background}-{options.crop_margins}')
        directory.mkdir()
        jobs=plan_advanced_exports([self.doc],directory,options,mode=mode)
        output=run_batch_exports_isolated(jobs,options)
        self.assertFalse(output.errors,output.errors)
        self.assertEqual(len(output.completed),len(jobs))
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.digest)
        result=[]
        for name in output.completed:
            with Image.open(name) as image:
                result.append((image.size,image.mode,image.getpixel((0,0))))
        return jobs,result

    def test_transparent_png_without_trim_preserves_page_pixel_size(self):
        jobs, result=self.run_export(self.opts)
        self.assertEqual(len(jobs),2)
        for size,mode,corner in result:
            self.assertEqual(size,(400,400))
            self.assertEqual(mode,'RGBA')
            self.assertEqual(corner[3],0)  # transparent outside the selected OCG ink

    def test_white_margin_trim_is_applied_to_each_separated_layer(self):
        opts=replace(self.opts,crop_margins=True)
        jobs,result=self.run_export(opts)
        self.assertEqual(len(jobs),2)
        for (w,h),mode,corner in result:
            self.assertLess(w,400)
            self.assertLess(h,400)
            self.assertGreater(w,60)
            self.assertGreater(h,160)
            self.assertEqual(mode,'RGBA')

    def test_opaque_png_trim_is_distinct_from_background(self):
        opts=replace(self.opts,background='opaque',crop_margins=True)
        _,result=self.run_export(opts)
        for (w,h),mode,corner in result:
            self.assertLess(w,400)
            self.assertLess(h,400)
            self.assertEqual(mode,'RGB')

    def test_group_output_trim_and_custom_page_plan(self):
        opts=replace(self.opts,crop_margins=True)
        directory=self.root/'groups'; directory.mkdir()
        jobs=plan_advanced_exports([self.doc],directory,opts,mode='groups',groups=('도로','수계'))
        self.assertEqual(len(jobs),2)
        result=run_batch_exports_isolated(jobs,opts)
        self.assertFalse(result.errors, result.errors)
        with Image.open(result.completed[0]) as im:
            self.assertLess(im.width,400)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.digest)

    def test_png_trim_profile_allowed_for_isolated_modes(self):
        opt=replace(self.opts,crop_margins=True)
        for mode,kw in [('layers',dict(groups=[],rules=[])),
                        ('groups',dict(groups=['도로'],rules=[]))]:
            payload=dict(schema_version=1,options=asdict(opt),mode=mode,
                         scope='current',page_range='',**kw)
            self.assertEqual(checked_profile(payload)[0].crop_margins,True)
            path=self.root/(mode+'.sdeprofile')
            save_profile(path,opt,mode=mode,scope='current',page_range='',**kw)
            loaded,data=load_profile(path)
            self.assertTrue(loaded.crop_margins)
            self.assertEqual(data['mode'],mode)

    def test_region_crop_is_still_rejected_and_jpg_no_alpha(self):
        with self.assertRaises(DrawingError):
            replace(self.opts,region=(.1,.2,.8,.9),crop_margins=True).checked()
        with self.assertRaises(DrawingError):
            replace(self.opts,fmt='jpg').checked()
        with self.assertRaises(DrawingError):
            replace(self.opts,fmt='jpg',background='opaque',crop_margins=True).checked()
        jpg=replace(self.opts,fmt='jpg',background='opaque')
        jobs=self.run_export(jpg)
        self.assertEqual(len(jobs[0]),2)
        self.assertTrue(all(i[0]==(400,400) for i in jobs[1]))


@unittest.skipUnless(importlib.util.find_spec('PySide6'),
                     'Qt GUI unavailable: widget theme/options must be verified on Windows')
class CombinationRasterQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from types import SimpleNamespace
        from drawing_editor.layer_tools_ui import AdvancedExportDialog
        from drawing_editor.ui_design import THEMES
        from PySide6.QtGui import QPalette
        self.tokens=THEMES
        self.doc=SimpleNamespace(kind='pdf',pages=2,page_index=0,source_signature=(1,2,100,3,4))
        self.d=AdvancedExportDialog(None,{},OutputOptions(fmt='png',background='transparent',crop_margins=True),
                                    [self.doc],viewport=(0,0,1,1),theme='dark')
        self.addCleanup(self.d.close)
        self.d.show();self.app.processEvents()

    def test_group_trim_not_silently_disabled(self):
        d=self.d
        d.mode.setCurrentIndex(d.mode.findData('layers'))
        self.assertTrue(d.raster_trim.isChecked())
        self.assertTrue(d.options().crop_margins)
        self.assertEqual(d.options().background,'transparent')
        self.assertIn('여백 제거 적용', d.profile_hint.text())
        d.raster_trim.setChecked(False)
        self.assertFalse(d.options().crop_margins)
        self.assertIn('여백 제거 미적용',d.profile_hint.text())

    def test_png_jpg_resolution_and_region_contract(self):
        d=self.d
        d.raster_format.setCurrentIndex(d.raster_format.findData('jpg'))
        self.assertFalse(d.raster_trim.isEnabled())
        self.assertFalse(d.raster_alpha.isEnabled())
        self.assertEqual(d.options().fmt,'jpg')
        d.raster_resolution.setCurrentIndex(d.raster_resolution.findData('dpi'))
        d.raster_dpi.setValue(600)
        self.assertEqual(d.options().dpi,600)
        d.raster_format.setCurrentIndex(d.raster_format.findData('png'))
        self.assertTrue(d.raster_trim.isChecked())
        d.effect.setCurrentIndex(d.effect.findData('region'))
        self.assertFalse(d.raster_trim.isChecked())
        self.assertFalse(d.raster_trim.isEnabled())
        d.set_drag_region((.1,.2,.8,.9))
        self.assertFalse(d.options().crop_margins)
        d.effect.setCurrentIndex(d.effect.findData('none'))
        self.assertTrue(d.raster_trim.isChecked())

    def test_theme_and_scrolled_panel(self):
        from PySide6.QtGui import QPalette
        from PySide6.QtGui import QColor
        d=self.d
        self.assertEqual(d.palette().color(QPalette.ColorRole.Window),QColor(self.tokens['dark'].panel))
        self.assertEqual(d.settings_scroll.viewport().palette().color(QPalette.ColorRole.Window),QColor(self.tokens['dark'].panel))
        d.apply_theme('light')
        self.assertEqual(d.palette().color(QPalette.ColorRole.Window),QColor(self.tokens['light'].panel))
        self.assertEqual(d.settings_scroll.viewport().palette().color(QPalette.ColorRole.Window),QColor(self.tokens['light'].panel))
        from drawing_editor.layer_tools_ui import export_message_box
        message = export_message_box(d, '확인', '테마 테스트', theme='dark', ask=True)
        self.addCleanup(message.close)
        self.assertIn(self.tokens['dark'].panel, message.styleSheet())
        self.assertEqual(message.palette().color(QPalette.ColorRole.Window), QColor(self.tokens['dark'].panel))

if __name__=='__main__':unittest.main(verbosity=2)
