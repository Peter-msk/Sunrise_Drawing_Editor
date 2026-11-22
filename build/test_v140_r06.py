"""R06 pure state checks plus optional actual Qt interaction checks.
Run with the declared PySide6-Essentials dependency; never count skipped GUI tests as PASS.
"""
from pathlib import Path
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drawing_editor.ui_design import stack_export_actions, panel_layout
from drawing_editor.ui_interaction import advanced_fields, export_action_state

class UIStateTests(unittest.TestCase):
    def test_cancel_survives_selection_refresh(self):
        for count in (0, 1, 5):
            for ready in (False, True):
                self.assertEqual(export_action_state(busy=True, cancel_requested=True, ready=ready,
                    analysis_busy=False, count=count), (False, '취소 요청됨'))
    def test_idle_and_busy_actions(self):
        state = lambda **kw: export_action_state(**dict(dict(busy=False, cancel_requested=False,
            ready=True, analysis_busy=False, count=1), **kw))
        self.assertEqual(state(), (True, '선택 도면 추출'))
        self.assertEqual(state(count=3), (True, '3개 도면 추출'))
        self.assertFalse(state(analysis_busy=True)[0]); self.assertFalse(state(ready=False)[0])
        self.assertEqual(state(busy=True, ready=False), (True, '추출 취소'))
    def test_conditional_field_matrix(self):
        for fmt in ('raster','pdf','svg','dxf'):
            for scope in ('current','all','range'):
                for effect in ('none','region'):
                    for available in (False,True):
                        page,region,viewport=advanced_fields(fmt,scope,effect,available)
                        self.assertEqual(page, scope=='range')
                        self.assertEqual(region, fmt=='raster' and effect=='region')
                        self.assertEqual(viewport, region and scope=='current' and available)
    def test_layout_breakpoints(self):
        for width in (760,899,900,1119,1120,1340,1510):
            self.assertEqual(stack_export_actions(width), width<1120)
            p=panel_layout(width)
            self.assertGreater(width-p.file_width-p.layer_width, 300)

@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Qt dependency unavailable: real widget tests NOT RUN')
class QtInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        from types import SimpleNamespace
        from drawing_editor.core import OutputOptions
        from drawing_editor.batch import LayerRule
        from drawing_editor.layer_tools_ui import AdvancedExportDialog
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.doc=SimpleNamespace(kind='pdf', pages=3, page_index=0, path=self.root/'one.pdf', source_signature=(0,0,100,0,0))
        self.rules={'road':LayerRule('road','pdf',(('ROAD',True),)), 'water':LayerRule('water','pdf',(('WATER',True),))}
        self.dialog=AdvancedExportDialog(None,self.rules,OutputOptions(),[self.doc],viewport=(.1,.2,.8,.9))
        self.addCleanup(self.dialog.close); self.dialog.show(); self.app.processEvents()
    def test_checkboxes_drive_parameters(self):
        from PySide6.QtCore import Qt
        d=self.dialog;d.mode.setCurrentIndex(d.mode.findData('rules'))
        d.items.item(1).setCheckState(Qt.CheckState.Checked)
        self.assertEqual([r.name for r in d.parameters()['rules']], ['water'])
        d._check_all(Qt.CheckState.Checked)
        self.assertEqual([r.name for r in d.parameters()['rules']], ['road','water'])
        d._check_all(Qt.CheckState.Unchecked)
        self.assertEqual(d.parameters()['rules'], [])
        from drawing_editor.core import DrawingError
        with self.assertRaises(DrawingError):d._validated_settings()
    def test_rows_and_viewport_region(self):
        d=self.dialog;self.assertTrue(d.page_range.isHidden());self.assertTrue(d.region_row.isHidden())
        d.effect.setCurrentIndex(d.effect.findData('region'));self.assertFalse(d.region_row.isHidden());self.assertTrue(d.select_region_button.isEnabled())
        from drawing_editor.core import DrawingError
        with self.assertRaises(DrawingError): d.options()
        d.set_drag_region((.1,.2,.8,.9));self.assertEqual(d.options().region,(.1,.2,.8,.9))
        d.scope.setCurrentIndex(d.scope.findData('range'));self.assertFalse(d.page_range.isHidden());self.assertFalse(d.select_region_button.isEnabled())
        d.page_range.setText('2-3');d.format.setCurrentIndex(d.format.findData('pdf'))
        self.assertTrue(d.region_row.isHidden());self.assertIsNone(d.options().region)
        d.scope.setCurrentIndex(d.scope.findData('current'));self.assertEqual(d.parameters()['page_range'],'')
    def test_profile_restore_checked_rules(self):
        from drawing_editor.core import OutputOptions
        from drawing_editor.drawing_analysis import save_profile
        p=self.root/'saved.sdeprofile';save_profile(p,OutputOptions(),mode='rules',scope='range',page_range='2-3',groups=[],rules=['water'])
        with patch('drawing_editor.layer_tools_ui.QFileDialog.getOpenFileName',return_value=(str(p),'')):
            self.dialog._load_profile()
        self.assertEqual([r.name for r in self.dialog.parameters()['rules']],['water'])
        self.assertEqual(self.dialog.parameters()['page_range'],'2-3')
    def test_hidden_inputs_do_not_change_output(self):
        d=self.dialog;d.effect.setCurrentIndex(d.effect.findData('region'));d.set_drag_region((.1,.2,.8,.9))
        d.effect.setCurrentIndex(d.effect.findData('none'));self.assertIsNone(d.options().region)
        d.effect.setCurrentIndex(d.effect.findData('region'));self.assertEqual(d.options().region,(.1,.2,.8,.9))

if __name__=='__main__':unittest.main(verbosity=2)
