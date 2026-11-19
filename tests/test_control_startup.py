"""Entry point wiring with stand-ins; no network, native Qt or document I/O."""
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

import main
from drawing_editor.control import Policy


def module(name, **attributes):
    m = ModuleType(name)
    m.__dict__.update(attributes)
    return m


class StartupControlTests(unittest.TestCase):
    def setUp(self):
        self.app, self.window, self.gate, self.feed = Mock(), Mock(), Mock(return_value=False), Mock()
        self.app.exec.return_value = 7
        self.worker = Mock(return_value=23)
        self.modules = {
            'PySide6': module('PySide6'),
            'PySide6.QtWidgets': module('PySide6.QtWidgets', QApplication=Mock(return_value=self.app)),
            'PySide6.QtGui': module('PySide6.QtGui', QIcon=Mock()),
            'drawing_editor.window': module('drawing_editor.window', DrawingWindow=self.window),
            'drawing_editor.control_ui': module('drawing_editor.control_ui', startup_gate=self.gate),
            'drawing_editor.release_ui': module('drawing_editor.release_ui', ReleaseFeedController=self.feed),
            'drawing_editor.batch_worker': module('drawing_editor.batch_worker', worker_main=self.worker),
            'drawing_editor.cad_worker': module('drawing_editor.cad_worker', worker_main=self.worker),
            'drawing_editor.onefile_update': module('drawing_editor.onefile_update', helper_main=self.worker),
        }

    def run_entry(self, policy, *args):
        with patch.dict(sys.modules, self.modules), patch.object(sys, 'argv', ['app', *args]), patch('drawing_editor.control.check_policy', return_value=policy) as check:
            result = main.main()
        return result, check

    def test_allow_creates_main_window(self):
        rc, check = self.run_entry(Policy(), 'example.pdf')
        self.assertEqual(rc, 7)
        check.assert_called_once_with()
        self.gate.assert_not_called()
        self.window.assert_called_once_with(['example.pdf'])
        self.feed.assert_called_once_with(self.window.return_value, auto_check=True)
        self.window.return_value.show.assert_called_once()

    def test_block_maintenance_and_minimum_never_create_window(self):
        for policy in (Policy(operation='block'), Policy(operation='maintenance'), Policy(update='required', minimum_version='1.0.1')):
            with self.subTest(policy=policy):
                rc, check = self.run_entry(policy)
                self.assertEqual(rc, 0)
                check.assert_called_once_with()
                self.gate.assert_called_with(self.app, policy)
                self.window.assert_not_called()
                self.feed.assert_not_called()
                self.app.exec.assert_not_called()

    def test_internal_worker_dispatch_bypasses_gui(self):
        for flag in ('--cad-worker', '--batch-worker', '--apply-onefile-update'):
            with self.subTest(flag=flag):
                rc, check = self.run_entry(Policy(operation='block'), flag, 'request')
                self.assertEqual(rc, 23)
                self.worker.assert_called_with(['request'])
                check.assert_not_called()
                self.window.assert_not_called()
                self.modules['PySide6.QtWidgets'].QApplication.assert_not_called()
