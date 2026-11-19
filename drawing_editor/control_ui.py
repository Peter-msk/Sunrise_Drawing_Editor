"""Startup-only gate using the existing themed release dialog and updater."""
from pathlib import Path

from PySide6.QtCore import QEventLoop, QObject, QSettings, QThreadPool, Qt, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QProgressDialog, QWidget

from .control import check_policy, ensure_update_allowed
from .icons import icon_file
from .release_feed import APP_VERSION, fetch_text, parse_update_info
from .release_ui import ReleaseDialog, UpdateTask, panel_style, can_apply_update

ASSETS = Path(__file__).resolve().parents[1] / 'assets'


class GateHost(QWidget):
    def __init__(self):
        super().__init__()
        theme = QSettings('Sunrise', 'DrawingEditor').value('theme', 'light')
        self._theme = theme if theme in ('light', 'dark') else 'light'
        self.setWindowIcon(QIcon(str(ASSETS / 'app.ico')))

    def _icon(self, name):
        return QIcon(icon_file(name, ASSETS, self._theme))


def show(host, title, body, *, action=None):
    dialog = ReleaseDialog(host, 'update', title, 'Sunrise Control · v' + APP_VERSION,
                           body, accept_label=action, close_label='프로그램 종료')
    dialog.setWindowTitle('Sunrise Control | 실행 정책')
    return dialog.exec() == QDialog.DialogCode.Accepted


class UpdateWait(QObject):
    def __init__(self, loop):
        super().__init__()
        self.loop = loop
        self.prepared = None
        self.error = None
        self.finished = False

    @Slot(object, object)
    def done(self, prepared, error):
        self.prepared, self.error = prepared, error
        self.finished = True
        self.loop.quit()


def required_auto_update(host, release):
    from .onefile_update import discard_prepared, launch_update, report_update_error
    dialog = QProgressDialog('Onefile 다운로드 및 검증 중…', '취소', 0, 100, host)
    dialog.setObjectName('releaseProgress')
    dialog.setStyleSheet(panel_style(host._theme))
    dialog.setWindowTitle('Sunrise Control | 필수 업데이트')
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    dialog.setMinimumDuration(0)
    dialog.setValue(0)
    task = UpdateTask(release)
    loop = QEventLoop()
    receiver = UpdateWait(loop)
    task.signals.progress.connect(dialog.setValue, Qt.ConnectionType.QueuedConnection)
    task.signals.done.connect(receiver.done, Qt.ConnectionType.QueuedConnection)
    dialog.canceled.connect(task.cancel.set)
    dialog.show()
    QThreadPool.globalInstance().start(task)
    if not receiver.finished:
        loop.exec()
    dialog.blockSignals(True)
    dialog.close()
    if task.cancel.is_set() or receiver.error or not receiver.prepared:
        discard_prepared(receiver.prepared)
        if receiver.error and not task.cancel.is_set():
            show(host, '필수 업데이트 실패', '업데이트를 완료하지 못했습니다. 기존 실행파일을 보존했습니다.\n\n' + str(receiver.error))
        return
    try:
        launch_update(receiver.prepared)
    except Exception as exc:
        discard_prepared(receiver.prepared)
        show(host, '필수 업데이트 실패', '업데이트를 시작하지 못했습니다. 기존 실행파일을 보존했습니다.\n\n' + report_update_error(exc, '필수 업데이트 교체 시작'))


def startup_gate(app, policy):
    """True only when normal application entry is permitted."""
    if not policy.blocks_entry and not policy.requires_update:
        return True
    previous = app.quitOnLastWindowClosed()
    app.setQuitOnLastWindowClosed(False)
    host = GateHost()
    try:
        if policy.blocks_entry:
            maintenance = policy.operation == 'maintenance'
            show(host, '시스템 점검 중' if maintenance else '프로그램 실행 차단',
                 policy.message or ('현재 점검 중입니다. 나중에 다시 실행하세요.' if maintenance
                                    else 'Sunrise Control 정책에 따라 실행이 제한되었습니다.'))
            return False
        body = ('현재 버전: v' + APP_VERSION + '\n최소 지원 버전: v' + policy.minimum_version
                + ('\n\n' + policy.message if policy.message else ''))
        try:
            release = parse_update_info(fetch_text('latest.json')).release
            if release is None:
                raise ValueError('등록된 신규 EXE가 없습니다.')
            ensure_update_allowed(policy, release.version)
        except Exception:
            show(host, '필수 업데이트 필요', body + '\n\n최소 버전을 충족하는 공식 배포 파일을 확인하지 못했습니다.\n관리자에게 문의하세요.')
            return False
        if not can_apply_update(release):
            show(host, '필수 업데이트 필요', body + '\n\n이 환경에서는 자동 업데이트를 진행할 수 없습니다. 관리자에게 문의하세요.')
            return False
        if show(host, '필수 업데이트 필요', body + '\n\n업데이트 전까지 정상 실행이 제한됩니다.', action='업데이트'):
            try:
                required_auto_update(host, release)
            except Exception:
                show(host, '필수 업데이트 실패', '업데이트를 시작하지 못했습니다. 관리자에게 문의하세요.')
        return False
    finally:
        host.close()
        app.setQuitOnLastWindowClosed(previous)
