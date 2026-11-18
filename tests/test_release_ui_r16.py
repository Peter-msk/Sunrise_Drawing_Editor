"""Focused Qt regression; use QT_QPA_PLATFORM=offscreen for headless CI."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtWidgets import QApplication, QMainWindow, QPlainTextEdit, QPushButton
    from PySide6.QtGui import QIcon
    from drawing_editor.release_ui import FeedTask, ReleaseDialog, ReleaseFeedController, panel_style
    from drawing_editor.icons import icon_file
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, 'PySide6 unavailable')
class ReleaseUiRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QMainWindow()
        self.window._theme = 'light'
        self.window._closing = False
        self.window._export_busy = False
        assets = Path(__file__).resolve().parents[1] / 'assets'
        self.window._icon = lambda name: QIcon(icon_file(name, assets, self.window._theme))
        self.controller = ReleaseFeedController(self.window, auto_check=False)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_two_independent_button_clicks(self):
        self.assertEqual(self.controller.notice_button.text(), '공지사항')
        self.assertEqual(self.controller.update_button.text(), '업데이트')
        with patch.object(self.controller, 'check') as check:
            self.controller.notice_button.click()
            self.controller.update_button.click()
            self.assertEqual([c.args for c in check.call_args_list], [('notice',), ('update',)])

    def test_notice_worker_does_not_query_update(self):
        with patch('drawing_editor.release_ui.fetch_text', return_value='notice') as fetch:
            task = FeedTask('notice')
            task.run()
            fetch.assert_called_once_with('notice.txt')

    def test_update_worker_does_not_query_notice(self):
        with patch('drawing_editor.release_ui.fetch_text', return_value='{}') as fetch:
            task = FeedTask('update')
            task.run()
            fetch.assert_called_once_with('latest.json')

    def test_both_themes_and_plain_text_popup(self):
        for theme in ('light', 'dark'):
            self.window._theme = theme
            self.controller.refresh_theme()
            self.assertFalse(self.controller.notice_button.icon().isNull())
            self.assertFalse(self.controller.update_button.icon().isNull())
            for kind in ('notice', 'update'):
                dialog = ReleaseDialog(self.window, kind, 'Title', 'Source', '<b>literal</b>')
                self.assertEqual(dialog.findChild(QPlainTextEdit).toPlainText(), '<b>literal</b>')
                self.assertEqual(dialog.styleSheet(), panel_style(theme))
                self.assertTrue(dialog.findChild(QPushButton).text())
                dialog.deleteLater()
