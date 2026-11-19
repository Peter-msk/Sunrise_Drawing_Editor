"""Independent, themed public notice and update panels.

Network I/O stays on a worker. Only the GUI thread owns widgets and dialogs.
"""
from __future__ import annotations

import sys
import threading
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot, Qt, QSize
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel,
                               QPlainTextEdit, QProgressDialog, QPushButton, QVBoxLayout)
from .release_feed import APP_VERSION, fetch_text, parse_update_info, notice_id
from .ui_design import THEMES
from .control import ControlDenied, check_policy, ensure_update_allowed

FEEDS = {'notice': 'notice.txt', 'update': 'latest.json'}


def can_apply_update(release):
    from .runtime_packaging import is_nuitka_candidate
    return (release.automatic and sys.platform == 'win32'
            and bool(getattr(sys, 'frozen', False)) and not is_nuitka_candidate())


def panel_style(theme):
    p = THEMES[theme]
    return f'''
        QDialog#releaseDialog, QProgressDialog#releaseProgress {{
            background:{p.background};color:{p.foreground};
            font-family:"Malgun Gothic","Noto Sans CJK KR",sans-serif;font-size:12px;
        }}
        QDialog#releaseDialog QLabel, QProgressDialog#releaseProgress QLabel {{color:{p.foreground};}}
        QDialog#releaseDialog QLabel#releaseHeading {{font-size:16px;font-weight:700;}}
        QDialog#releaseDialog QLabel#releaseSubtitle {{font-size:11px;color:{p.muted};}}
        QDialog#releaseDialog QFrame#releaseHeader {{background:{p.panel};border:1px solid {p.border};border-radius:8px;}}
        QDialog#releaseDialog QPlainTextEdit#releaseBody {{background:{p.input_background};color:{p.foreground};
            border:1px solid {p.border};border-radius:6px;padding:9px;
            selection-background-color:{p.selection};selection-color:{p.foreground};}}
        QDialog#releaseDialog QPushButton, QProgressDialog#releaseProgress QPushButton {{
            background:{p.input_background};color:{p.foreground};border:1px solid {p.border};
            border-radius:6px;padding:6px 10px;min-height:23px;
        }}
        QDialog#releaseDialog QPushButton:hover,QProgressDialog#releaseProgress QPushButton:hover {{
            background:{p.hover};border-color:{p.primary};}}
        QDialog#releaseDialog QPushButton:focus,QProgressDialog#releaseProgress QPushButton:focus {{
            border:2px solid {p.primary};padding:5px 9px;}}
        QDialog#releaseDialog QPushButton[uxRole="primary"] {{
            background:{p.primary};border-color:{p.primary};color:white;font-weight:700;}}
        QDialog#releaseDialog QPushButton[uxRole="primary"]:hover {{
            background:{p.primary_hover};border-color:{p.primary_hover};}}
        QDialog#releaseDialog QPushButton[uxRole="primary"]:focus {{border:2px solid {p.foreground};}}
        QDialog#releaseDialog QPushButton:disabled,QProgressDialog#releaseProgress QPushButton:disabled {{
            background:{p.background};color:{p.muted};border-color:{p.border};}}
    '''


class ReleaseDialog(QDialog):
    def __init__(self, window, kind, heading, subtitle, content, *,
                 accept_label=None, close_label='닫기'):
        super().__init__(window)
        self.setObjectName('releaseDialog')
        self.setWindowTitle('Sunrise Drawing Editor | ' + ('공지사항' if kind == 'notice' else '업데이트'))
        self.setWindowIcon(window.windowIcon())
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setStyleSheet(panel_style(window._theme))
        screen = window.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        self.resize(min(520, max(320, avail.width()-40)) if avail else 520,
                    min(390, max(260, avail.height()-60)) if avail else 390)
        root = QVBoxLayout(self)
        root.setContentsMargins(12,12,12,12)
        root.setSpacing(8)
        header = QFrame(self)
        header.setObjectName('releaseHeader')
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(10,10,10,10)
        icon = QLabel(header)
        icon.setPixmap(window._icon(kind).pixmap(QSize(24,24)))
        header_row.addWidget(icon)
        titles = QVBoxLayout()
        titles.setSpacing(3)
        title = QLabel(heading, header)
        title.setObjectName('releaseHeading')
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        sub = QLabel(subtitle, header)
        sub.setObjectName('releaseSubtitle')
        sub.setTextFormat(Qt.TextFormat.PlainText)
        sub.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(sub)
        header_row.addLayout(titles, 1)
        root.addWidget(header)
        body = QPlainTextEdit(self)
        body.setObjectName('releaseBody')
        body.setReadOnly(True)
        body.setPlainText(content)
        body.setAccessibleName('공지사항 내용' if kind == 'notice' else '업데이트 상세 내용')
        root.addWidget(body, 1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        close = QPushButton(close_label, self)
        close.clicked.connect(self.reject)
        if accept_label:
            accept = QPushButton(accept_label, self)
            accept.setProperty('uxRole', 'primary')
            accept.clicked.connect(self.accept)
            footer.addWidget(accept)
            # Do not make pressing Enter automatically approve an executable.
            accept.setAutoDefault(False)
        footer.addWidget(close)
        close.setDefault(True)
        close.setFocus()
        root.addLayout(footer)


class FeedTask(QRunnable):
    class Signals(QObject):
        ready = Signal(str, object, object)

    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.signals = self.Signals()

    def run(self):
        try:
            policy = check_policy() if self.kind == 'update' else None
            if policy is not None:
                ensure_update_allowed(policy)
            text = fetch_text(FEEDS[self.kind])
            result = text.strip() if self.kind == 'notice' else parse_update_info(text)
            if policy is not None and result.release is not None:
                ensure_update_allowed(policy, result.release.version)
            self.signals.ready.emit(self.kind, result, None)
        except ControlDenied as exc:
            self.signals.ready.emit(self.kind, None, exc)
        except Exception as exc:
            self.signals.ready.emit(self.kind, None, type(exc).__name__)


class UpdateTask(QRunnable):
    class Signals(QObject):
        done = Signal(object, object)
        progress = Signal(int)

    def __init__(self, release):
        super().__init__()
        self.release = release
        self.cancel = threading.Event()
        self.signals = self.Signals()

    def run(self):
        from .onefile_update import stage_update, report_update_error
        try:
            prepared = stage_update(self.release, cancelled=self.cancel.is_set,
                                    progress=lambda n, total: self.signals.progress.emit(min(99, n*99//total)))
            self.signals.done.emit(prepared, None)
        except Exception as exc:
            self.signals.done.emit(None, report_update_error(exc))


class ReleaseFeedController(QObject):
    def __init__(self, window, *, auto_check=False):
        super().__init__(window)
        self.window = window
        self.busy = False
        self._task = None
        self._update_task = None
        self._progress_dialog = None
        self._pending = []
        self._manual = False
        self._mandatory = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._next)
        self.notice_button = QPushButton('공지사항', window)
        self.update_button = QPushButton('업데이트', window)
        for kind, button, tip in (
            ('notice', self.notice_button, '공식 공지사항 확인'),
            ('update', self.update_button, '현재 버전 ' + APP_VERSION + ' · 공식 업데이트 확인'),
        ):
            button.setObjectName(kind + 'FeedButton')
            button.setProperty('uxRole', 'releaseAction')
            button.setAccessibleName(button.text())
            button.setToolTip(tip)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            window.statusBar().addPermanentWidget(button)
            button.clicked.connect(lambda checked=False, k=kind: self.check(k))
        self.refresh_theme()
        if auto_check:
            self._pending = [('update', False), ('notice', False)]
            self._timer.start(150)

    def refresh_theme(self):
        for kind, button in (('notice', self.notice_button), ('update', self.update_button)):
            button.setIcon(self.window._icon(kind))
            button.setIconSize(QSize(18,18))
            button.style().unpolish(button)
            button.style().polish(button)

    def _enable_buttons(self, enabled):
        self.notice_button.setEnabled(enabled)
        self.update_button.setEnabled(enabled)

    def check(self, kind):
        if kind not in FEEDS or self._mandatory or self.window._closing or self._update_task is not None or self.busy:
            return
        if self.window._export_busy:
            self.window.statusBar().showMessage('추출 완료 후 다시 확인하세요.', 7000)
            return
        # A manual click fetches only that feed; automatic checks stay queued.
        self._pending = [(k, m) for k, m in self._pending if k != kind]
        self._pending.insert(0, (kind, True))
        self._next()

    @Slot()
    def _next(self):
        if self._mandatory or self.window._closing or not self.window.isVisible():
            self._pending.clear()
            return
        if self.busy or self._update_task is not None or not self._pending:
            return
        if self.window._export_busy or QApplication.activeModalWidget() is not None:
            self._timer.start(1000)
            return
        kind, self._manual = self._pending.pop(0)
        self.busy = True
        self._enable_buttons(False)
        self._task = FeedTask(kind)
        self._task.signals.ready.connect(self.finished, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(self._task)

    def _show(self, kind, heading, subtitle, content, **kwargs):
        return ReleaseDialog(self.window, kind, heading, subtitle, content, **kwargs).exec()

    def _exit_for_update(self):
        # The normal closeEvent owns cancellation and worker cleanup. Keep the
        # editor disabled while a native worker is still draining.
        self._mandatory = True
        self._pending.clear()
        self._timer.stop()
        self._enable_buttons(False)
        self.window.setEnabled(False)
        if not self.window._closing:
            self.window.close()

    @Slot(str, object, object)
    def finished(self, kind, result, error):
        self._task = None
        manual = self._manual
        if self.window._closing or not self.window.isVisible():
            self.busy = False
            return
        if self.window._export_busy or QApplication.activeModalWidget() is not None:
            # Keep the confirmed result, rather than re-fetching and possibly
            # losing a mandatory update decision during an existing export.
            QTimer.singleShot(500, lambda: self.finished(kind, result, error))
            return
        try:
            if isinstance(error, ControlDenied):
                if manual:
                    self._show(kind, '업데이트 제한', 'Sunrise Group', str(error))
                return
            if error:
                if manual:
                    self._show(kind, '서버 연결 또는 응답 오류', 'Sunrise Group',
                               '공식 정보를 확인하지 못했습니다. 인터넷 연결을 확인한 뒤 다시 시도하세요.')
                return
            if kind == 'notice':
                if result and (manual or self.window._settings.value('release_notice_seen', '') != notice_id(result)):
                    self._show(kind, 'Sunrise Group 공지사항', 'Sunrise Group', result)
                    self.window._settings.setValue('release_notice_seen', notice_id(result))
                elif manual:
                    self._show(kind, '공지사항', 'Sunrise Group', '등록된 공지사항이 없습니다.')
                return
            info = result
            versions = '현재 버전: v' + info.current + '\n서버 버전: v' + info.latest
            notes = versions + ('\n\n' + info.notes if info.notes else '')
            release = info.release
            if release is None:
                if manual:
                    status = '업데이트 배포 준비 중' if not info.configured else '최신 버전입니다'
                    self._show(kind, status, 'Sunrise Group',
                               notes + ('\n\n다운로드 가능한 신규 EXE가 등록되지 않았습니다.' if not info.configured else ''))
                return
            # A validated newer publication is mandatory even under update=allow.
            # No browser route, and no return to the editor after rejection.
            self._mandatory = True
            self._pending.clear()
            automatic = can_apply_update(release)
            detail = ('업데이트 전까지 프로그램을 사용할 수 없습니다.' if automatic
                      else '이 환경에서는 자동 업데이트를 진행할 수 없습니다. 관리자에게 문의하세요.')
            answer = self._show(kind, '신규 업데이트가 있습니다', 'Sunrise Group',
                                notes + '\n\n' + detail,
                                accept_label='업데이트' if automatic else None, close_label='프로그램 종료')
            if automatic and answer == QDialog.DialogCode.Accepted:
                try:
                    self.start_update(release)
                except Exception:
                    self._show(kind, '업데이트 중단', 'Sunrise Group',
                               '업데이트를 시작하지 못했습니다. 기존 실행파일은 보존됩니다. 관리자에게 문의하세요.',
                               close_label='프로그램 종료')
        finally:
            self.busy = False
            if self._mandatory:
                if self._update_task is None:
                    self._exit_for_update()
            elif self._update_task is None and not self.window._closing:
                self._enable_buttons(True)
                if self._pending:
                    self._timer.start(1000)

    @Slot()
    def _cancel_update(self):
        if self._update_task is not None:
            self._update_task.cancel.set()
            # QProgressDialog hides itself on cancellation. Do not expose an
            # interactive editor while the worker is cleaning its staged file.
            self.window.setEnabled(False)

    @Slot(int)
    def _update_progress(self, value):
        if self._update_task is not None and not self._update_task.cancel.is_set():
            self._progress_dialog.setValue(value)

    def start_update(self, release):
        self._enable_buttons(False)
        dialog = QProgressDialog('Onefile 다운로드 및 검증 중…', '취소', 0, 100, self.window)
        dialog.setObjectName('releaseProgress')
        dialog.setStyleSheet(panel_style(self.window._theme))
        dialog.setWindowTitle('Sunrise 업데이트')
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)
        self._progress_dialog = dialog
        task = UpdateTask(release)
        self._update_task = task
        task.signals.progress.connect(self._update_progress, Qt.ConnectionType.QueuedConnection)
        task.signals.done.connect(self.update_finished, Qt.ConnectionType.QueuedConnection)
        dialog.canceled.connect(self._cancel_update)
        try:
            dialog.show()
            QThreadPool.globalInstance().start(task)
        except Exception:
            self._update_task = None
            self._progress_dialog = None
            dialog.blockSignals(True)
            dialog.close()
            dialog.deleteLater()
            raise

    @Slot(object, object)
    def update_finished(self, prepared, error):
        from .onefile_update import launch_update, discard_prepared, report_update_error
        task, self._update_task = self._update_task, None
        dialog, self._progress_dialog = self._progress_dialog, None
        try:
            if dialog:
                dialog.blockSignals(True)
                dialog.close()
                dialog.deleteLater()
            if error or not prepared or not task or task.cancel.is_set() or self.window._closing or not self.window.isVisible() or self.window._export_busy:
                discard_prepared(prepared)
                if error and task and not task.cancel.is_set() and self.window.isVisible() and not self.window._closing:
                    self._show('update', '업데이트 중단', 'Sunrise Group',
                               '업데이트를 완료하지 못했습니다. 기존 실행파일은 보존됩니다.\n\n' + str(error),
                               close_label='프로그램 종료')
                return
            try:
                launch_update(prepared)
            except Exception as exc:
                discard_prepared(prepared)
                self._show('update', '업데이트 중단', 'Sunrise Group',
                           '업데이트를 시작하지 못했습니다. 기존 실행파일은 보존됩니다.\n\n' + report_update_error(exc, '교체 시작'),
                           close_label='프로그램 종료')
        finally:
            self._exit_for_update()
