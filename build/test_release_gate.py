"""Targeted state-transition regression using Qt stand-ins; no native GUI claimed."""
import sys, types, unittest, threading
from unittest.mock import Mock, patch
from types import SimpleNamespace as NS
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
class Obj: pass
class Dialog:
    DialogCode=NS(Accepted=1,Rejected=0)
class App:
    activeModalWidget=staticmethod(lambda:None)
class Timer:
    singleShot=Mock()
def module(name,**kw):
    m=types.ModuleType(name);m.__dict__.update(kw);return m
qt={
'PySide6':module('PySide6'),
'PySide6.QtCore':module('PySide6.QtCore',QObject=Obj,QRunnable=Obj,QThreadPool=Mock(),QTimer=Timer,Signal=lambda *a:None,Slot=lambda *a:lambda f:f,Qt=Mock(),QSize=Mock(),QEventLoop=Mock(),QSettings=Mock()),
'PySide6.QtGui':module('PySide6.QtGui',QIcon=Mock()),
'PySide6.QtWidgets':module('PySide6.QtWidgets',QApplication=App,QDialog=Dialog,QFrame=Mock(),QHBoxLayout=Mock(),QLabel=Mock(),QPlainTextEdit=Mock(),QProgressDialog=Mock(),QPushButton=Mock(),QVBoxLayout=Mock(),QWidget=Obj)}
with patch.dict(sys.modules,qt):
    from drawing_editor import release_ui as ui, control_ui as gate
from drawing_editor.control import Policy, ControlDenied, parse_control
from drawing_editor.release_feed import APP_VERSION, Release, UpdateInfo
rel=Release('9.0.0','internal', 'a'*64, 10,'internal',True)
info=UpdateInfo(APP_VERSION,'9.0.0',True,'안내',rel)
class Tests(unittest.TestCase):
    def setUp(self):
        self.c=object.__new__(ui.ReleaseFeedController)
        self.c.window=Mock(_closing=False,_export_busy=False)
        self.c.window.isVisible.return_value=True
        self.c._manual=True;self.c._task=Mock();self.c._update_task=None
        self.c._progress_dialog=None;self.c._pending=[('notice',False)];self.c._timer=Mock();self.c._mandatory=False;self.c.busy=True
        self.c._enable_buttons=Mock();self.c._show=Mock(return_value=0);self.c.start_update=Mock()
    def assert_exit(self):
        self.c.window.close.assert_called_once();self.c.window.setEnabled.assert_called_with(False)
        self.assertTrue(self.c._mandatory);self.assertFalse(self.c._pending)
    def finish(self, result=info, error=None,automatic=True):
        with patch.object(ui,'can_apply_update',return_value=automatic): self.c.finished('update',result,error)
    def test_no_approved_release_continues(self):
        self.finish(UpdateInfo(APP_VERSION,'9.0.0',False,'',None));self.c.window.close.assert_not_called();self.assertFalse(self.c._mandatory)
    def test_control_block_continues(self):
        self.finish(None,ControlDenied('차단'));self.c.window.close.assert_not_called()
    def test_network_error_continues(self):
        self.finish(None,'NetworkError');self.c.window.close.assert_not_called()
    def test_reject_or_x_closes(self):
        self.finish();self.assert_exit();self.assertEqual(self.c._show.call_args.kwargs['close_label'],'프로그램 종료')
    def test_no_auto_only_exit(self):
        self.finish(automatic=False);self.assert_exit();self.assertIsNone(self.c._show.call_args.kwargs['accept_label'])
    def test_accept_runs_internal_update(self):
        self.c._show.return_value=1
        self.c.start_update.side_effect=lambda r:setattr(self.c,'_update_task',Mock())
        self.finish();self.c.start_update.assert_called_once_with(rel);self.c.window.close.assert_not_called();self.assertTrue(self.c._mandatory)
    def test_start_failure_exits(self):
        self.c._show.return_value=1;self.c.start_update.side_effect=RuntimeError('failed');self.finish();self.assert_exit()
    def test_cancel_locks_main(self):
        self.c._update_task=NS(cancel=threading.Event());self.c._cancel_update();self.assertTrue(self.c._update_task.cancel.is_set());self.c.window.setEnabled.assert_called_with(False)
    def terminal(self, cancel=False,error=None,launch_failure=False):
        self.c._mandatory=True;self.c._update_task=NS(cancel=threading.Event())
        if cancel:self.c._update_task.cancel.set()
        with patch('drawing_editor.onefile_update.launch_update',side_effect=RuntimeError('failed') if launch_failure else None) as launch,patch('drawing_editor.onefile_update.discard_prepared') as discard:
            self.c.update_finished(('prepared',),error)
            self.assert_exit();return launch.call_count,discard.call_count
    def test_download_cancel_exits(self):self.assertEqual(self.terminal(cancel=True),(0,1))
    def test_download_failure_exits(self):self.assertEqual(self.terminal(error='error'),(0,1))
    def test_launch_failure_exits(self):self.assertEqual(self.terminal(launch_failure=True),(1,1))
    def test_success_launch_exits(self):self.assertEqual(self.terminal(),(1,0))
    def test_existing_export_defers_same_result(self):
        self.c.window._export_busy=True;self.finish();self.assertTrue(self.c.busy);self.c.window.close.assert_not_called();self.c.window._export_busy=False
        with patch.object(ui,'can_apply_update',return_value=True):Timer.singleShot.call_args.args[1]()
        self.assert_exit()
    def test_notice_close_continues(self):
        self.c.finished('notice','공지',None);self.c.window.close.assert_not_called()
    def test_required_unavailable_never_enters(self):
        app=Mock();p=Policy(update='required',minimum_version='9.0.0')
        with patch.object(gate,'GateHost',return_value=Mock()),patch.object(gate,'fetch_text',return_value='data'),patch.object(gate,'parse_update_info',return_value=info),patch.object(gate,'can_apply_update',return_value=False),patch.object(gate,'show',return_value=True) as show,patch.object(gate,'required_auto_update') as run:
            self.assertFalse(gate.startup_gate(app,p));run.assert_not_called();self.assertNotIn('action',show.call_args.kwargs)
    def test_required_rejected_never_enters(self):
        app=Mock();p=Policy(update='required',minimum_version='9.0.0')
        with patch.object(gate,'GateHost',return_value=Mock()),patch.object(gate,'fetch_text',return_value='data'),patch.object(gate,'parse_update_info',return_value=info),patch.object(gate,'can_apply_update',return_value=True),patch.object(gate,'show',return_value=False),patch.object(gate,'required_auto_update') as run:
            self.assertFalse(gate.startup_gate(app,p));run.assert_not_called()
    def test_required_accept_uses_internal_update(self):
        app=Mock();p=Policy(update='required',minimum_version='9.0.0')
        with patch.object(gate,'GateHost',return_value=Mock()),patch.object(gate,'fetch_text',return_value='data'),patch.object(gate,'parse_update_info',return_value=info),patch.object(gate,'can_apply_update',return_value=True),patch.object(gate,'show',return_value=True),patch.object(gate,'required_auto_update') as run:
            self.assertFalse(gate.startup_gate(app,p));run.assert_called_once()
    def test_operation_block_precedes_update(self):
        with patch.object(gate,'GateHost',return_value=Mock()),patch.object(gate,'fetch_text') as fetch,patch.object(gate,'show'):
            self.assertFalse(gate.startup_gate(Mock(),Policy(operation='block',update='required',minimum_version='9.0.0')));fetch.assert_not_called()
    def test_no_external_navigation(self):
        for n in ('release_ui.py','control_ui.py'):
            s=(Path.cwd()/'drawing_editor'/n).read_text();self.assertNotIn('openUrl',s);self.assertNotIn('source_url',s);self.assertNotIn('GitHub',s)
if __name__=='__main__':unittest.main(verbosity=2)
