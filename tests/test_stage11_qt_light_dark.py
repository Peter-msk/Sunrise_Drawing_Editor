"""Optional real-Qt smoke contracts for the Stage11 light/dark UI fix.

These only run when PySide6 is available. Offscreen mode checks widget
geometry and palette bindings, not real Windows DPI screenshot parity.
"""
from __future__ import annotations

import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest

try:
    from PySide6.QtWidgets import QApplication, QToolBar, QToolButton
    from PySide6.QtCore import Qt
    from drawing_editor.window import DrawingWindow
    QT_READY = True
except ImportError:
    QT_READY = False


@unittest.skipUnless(QT_READY, 'PySide6 is not installed; native Qt QA NOT RUN')
class Stage11QtContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = DrawingWindow()
        self.window.resize(1500, 870)
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.window.close)

    def test_light_dark_shared_style_and_tool_buttons(self):
        for theme in ('light','dark'):
            with self.subTest(theme=theme):
                self.window.set_theme(theme)
                self.app.processEvents()
                style = self.window.styleSheet()
                self.assertIn('QFrame#layerSearchFrame',style)
                self.assertIn('QGroupBox#exportPanel QRadioButton',style)
                self.assertIn('QToolBar#toolbar QToolButton',style)
                self.assertFalse(self.window.layer_search_icon.pixmap().isNull())
                toolbar = self.window.findChild(QToolBar, 'toolbar')
                buttons = toolbar.findChildren(QToolButton)
                self.assertGreaterEqual(len(buttons),2)
                self.assertTrue(self.window.add_action.isEnabled())

    def test_search_icon_optical_center(self):
        self.app.processEvents()
        row = self.window.layer_search_frame
        icon = self.window.layer_search_icon
        # Qt logical pixel alignment, independent of OS devicePixelRatio.
        center_y = icon.mapTo(row, icon.rect().center()).y()
        self.assertLessEqual(abs(center_y - row.rect().center().y()), 3)


if __name__ == '__main__':
    unittest.main()
