"""Region selection + dialog theme regression. Qt tests must not count as PASS if skipped."""
from pathlib import Path
import importlib.util
import math
import os
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drawing_editor.ui_interaction import normalized_drag_region
from drawing_editor.ui_design import THEMES


class RegionMathTests(unittest.TestCase):
    def test_reverse_drag(self):
        self.assertEqual(normalized_drag_region((1000., 500.), (800., 400.), (200., 100.)),
                         (.2, .2, .8, .8))

    def test_clips_outside_page(self):
        self.assertEqual(normalized_drag_region((200., 100.), (-40., -10.), (100., 130.)),
                         (0., 0., .5, 1.))

    def test_rotated_visible_page_size(self):
        # A rotated A4 page is drawn with its displayed width/height.
        self.assertEqual(normalized_drag_region((842., 595.), (84.2, 119.), (421., 476.)),
                         (.1, .2, .5, .8))

    def test_no_or_tiny_selection(self):
        self.assertIsNone(normalized_drag_region((100., 100.), (20., 20.), (20., 80.)))
        self.assertIsNone(normalized_drag_region((100., 100.), (20., 20.), (20.00001, 80.)))
        self.assertIsNone(normalized_drag_region((0., 100.), (20., 20.), (80., 80.)))
        self.assertIsNone(normalized_drag_region((100., 100.), (math.nan, 20.), (80., 80.)))
        self.assertIsNone(normalized_drag_region((100., 100.), (math.inf, 20.), (80., 80.)))

    def test_theme_tokens_differ_for_main_and_dialog(self):
        self.assertNotEqual(THEMES['light'].panel, THEMES['dark'].panel)
        self.assertNotEqual(THEMES['light'].input_background, THEMES['dark'].input_background)



class ActualPdfExportTest(unittest.TestCase):
    def test_drag_rectangle_drives_original_pdf_crop_not_screenshot(self):
        import hashlib
        import tempfile
        import fitz
        from PIL import Image
        from drawing_editor.core import DrawingDocument, OutputOptions, close_thread_document
        from drawing_editor.state import DrawingState
        from drawing_editor.layer_tools import plan_advanced_exports
        from drawing_editor.batch_worker import run_batch_exports_isolated
        from drawing_editor.cad_worker import shutdown_all_workers
        with tempfile.TemporaryDirectory() as root:
            src = Path(root) / 'original.pdf'
            with fitz.open() as pdf:
                p = pdf.new_page(width=200, height=100)
                p.draw_rect(fitz.Rect(0, 0, 100, 100), color=None, fill=(1, 0, 0))
                p.draw_rect(fitz.Rect(100, 0, 200, 100), color=None, fill=(0, 0, 1))
                pdf.save(src)
            orig = hashlib.sha256(src.read_bytes()).hexdigest()
            doc = DrawingState(src)
            with DrawingDocument(src) as loaded:
                doc.load_metadata(loaded.layers(), loaded.pages)
            # This region came from a reversed mouse drag over the displayed page.
            region = normalized_drag_region((200.,100.), (150.,90.), (50.,10.))
            opts = OutputOptions(resolution='custom',width=400,height=200,region=region)
            try:
                jobs = plan_advanced_exports([doc],Path(root),opts)
                result = run_batch_exports_isolated(jobs,opts)
                self.assertFalse(result.errors)
                self.assertEqual(len(result.completed),1)
                with Image.open(result.completed[0]) as image:
                    self.assertEqual(image.size,(250,200))
                    self.assertGreater(image.getpixel((30,100))[0],245)
                    self.assertGreater(image.getpixel((220,100))[2],245)
                self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(),orig)
            finally:
                close_thread_document()
                shutdown_all_workers()

@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Qt unavailable: drag and dialog widget tests NOT RUN')
class QtDragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_dark_popup_and_no_coordinate_input(self):
        from types import SimpleNamespace
        from drawing_editor.core import OutputOptions, DrawingError
        from drawing_editor.layer_tools_ui import AdvancedExportDialog
        doc=SimpleNamespace(kind='pdf',pages=1,page_index=0,source_signature=(0,0,1,0,0))
        dlg=AdvancedExportDialog(None,{},OutputOptions(),[doc],viewport=(0,0,1,1),theme='dark')
        self.addCleanup(dlg.close)
        dlg.show();self.app.processEvents()
        self.assertEqual(dlg.objectName(),'advancedExportDialog')
        self.assertNotIn('영역 좌표 (%)',dlg.styleSheet())
        self.assertIn(THEMES['dark'].panel,dlg.styleSheet())
        self.assertTrue(dlg.page_range.isHidden())
        dlg.effect.setCurrentIndex(dlg.effect.findData('region'))
        self.assertFalse(dlg.region_row.isHidden())
        with self.assertRaises(DrawingError):dlg.options()
        dlg.set_drag_region((.15,.25,.65,.75))
        self.assertEqual(dlg.options().region,(.15,.25,.65,.75))
        self.assertIn('선택 완료',dlg.region_summary.text())
        dlg.apply_theme('light')
        self.assertIn(THEMES['light'].panel,dlg.styleSheet())

    def test_real_canvas_mouse_drag_and_cancel(self):
        from PySide6.QtCore import Qt, QPoint
        from PySide6.QtGui import QPixmap, QPainter
        from PySide6.QtWidgets import QApplication
        from PySide6.QtTest import QTest
        from drawing_editor.window import ImageCanvas
        canvas=ImageCanvas();self.addCleanup(canvas.close)
        canvas.resize(520,420)
        pix=QPixmap(200,100);pix.fill(Qt.GlobalColor.white)
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);pix.save(buffer,'PNG')
        canvas.show_png(bytes(buffer.data()),(200.,100.))
        canvas.show();self.app.processEvents()
        selected=[];cancelled=[]
        canvas.regionPicked.connect(lambda v:selected.append(v))
        canvas.regionPickCancelled.connect(lambda :cancelled.append(True))
        self.assertTrue(canvas.begin_region_pick())
        a=canvas.mapFromScene(40.,25.); b=canvas.mapFromScene(160.,75.)
        QTest.mousePress(canvas.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,a)
        QTest.mouseMove(canvas.viewport(),b)
        QTest.mouseRelease(canvas.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,b)
        self.app.processEvents()
        self.assertEqual(len(selected),1)
        for got,exp in zip(selected[0],(.2,.25,.8,.75)):
            self.assertAlmostEqual(got,exp,places=2)
        self.assertTrue(canvas.begin_region_pick())
        QTest.keyClick(canvas,Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertEqual(cancelled,[True])

if __name__=='__main__':unittest.main(verbosity=2)
