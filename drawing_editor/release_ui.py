"""Non-blocking notice checking and user-approved onefile release handoff.

Automatic replacement is gated by release metadata and native Windows trust.
"""
from __future__ import annotations
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QPushButton, QProgressDialog
import sys
import threading
from .release_feed import APP_VERSION, fetch_text, parse_release, notice_id


class FeedTask(QRunnable):
    class Signals(QObject):
        ready = Signal(object, object, object)

    def __init__(self):
        super().__init__()
        self.signals = self.Signals()

    def run(self):
        notice, release, errors = '', None, []
        for name in ('notice.txt', 'latest.json'):
            try:
                content = fetch_text(name)
                if name == 'notice.txt':
                    notice = content.strip()
                else:
                    release = parse_release(content)
            except Exception as exc:
                errors.append(name + ': ' + type(exc).__name__)
        self.signals.ready.emit(notice, release, errors)


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
        from .onefile_update import stage_update
        try:
            prepared = stage_update(self.release, cancelled=self.cancel.is_set,
                                    progress=lambda n, total: self.signals.progress.emit(min(99, n*99//total)))
            self.signals.done.emit(prepared, None)
        except Exception as exc:
            self.signals.done.emit(None, str(exc))


class ReleaseFeedController(QObject):
    def __init__(self, window, *, auto_check=False):
        super().__init__(window)
        self.window = window
        self.busy = False
        self.manual = False
        self._task = None
        self._update_task = None
        self._progress_dialog = None
        self.button = QPushButton('공지 · 업데이트', window)
        self.button.setObjectName('releaseFeedButton')
        self.button.setToolTip('현재 버전 ' + APP_VERSION + ' · 공식 공지 및 업데이트 확인')
        window.statusBar().addPermanentWidget(self.button)
        self.button.clicked.connect(lambda: self.check(True))
        if auto_check:
            QTimer.singleShot(150, self.check)

    @Slot()
    def check(self, manual=False):
        if self.busy or self._update_task is not None or self.window._closing:
            return
        self.busy = True
        self.manual = manual
        self.button.setEnabled(False)
        self._task = FeedTask()
        self._task.signals.ready.connect(self.finished, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(self._task)

    @Slot(object, object, object)
    def finished(self, notice, release, errors):
        self.busy = False
        self._task = None
        self.button.setEnabled(True)
        if self.window._closing or not self.window.isVisible():
            return
        # Do not interrupt active drawing exports. Ask again from the button.
        if self.window._export_busy:
            self.window.statusBar().showMessage('추출 완료 후 공지 · 업데이트를 확인하세요.', 10000)
            return
        if notice and (self.manual or self.window._settings.value('release_notice_seen', '') != notice_id(notice)):
            box = QMessageBox(self.window)
            box.setWindowTitle('Sunrise Group 공지')
            box.setTextFormat(Qt.TextFormat.PlainText)
            box.setText(notice)
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.exec()
            self.window._settings.setValue('release_notice_seen', notice_id(notice))
        if release:
            box = QMessageBox(self.window)
            box.setWindowTitle('Sunrise Drawing Editor 업데이트')
            box.setTextFormat(Qt.TextFormat.PlainText)
            box.setText('신규 버전 ' + release.version + '이 있습니다.\n현재 버전: ' + APP_VERSION
                        + '\n공식 배포 페이지에서 서명된 Onefile EXE를 확인하고 교체하세요.')
            automatic = release.automatic and sys.platform == 'win32' and bool(getattr(sys, 'frozen', False))
            if automatic:
                box.setText('신규 버전 ' + release.version + '이 있습니다.\n현재 버전: ' + APP_VERSION
                            + '\n서명과 SHA-256을 검증한 뒤 현재 EXE를 교체합니다.')
            update = box.addButton('업데이트' if automatic else '업데이트 페이지 열기', QMessageBox.ButtonRole.AcceptRole)
            box.addButton('종료', QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() == update:
                if automatic:
                    self.start_update(release)
                    return
                if not QDesktopServices.openUrl(QUrl(release.page)):
                    QMessageBox.warning(self.window, '업데이트 페이지 오류', '공식 배포 페이지를 열지 못했습니다. 다시 시도하세요.')
                    return
            self.window.close()
        elif self.manual:
            if errors:
                QMessageBox.warning(self.window, '확인 실패', '일부 공식 정보를 확인하지 못했습니다.\n' + '\n'.join(errors))
            else:
                QMessageBox.information(self.window, '업데이트 확인', '현재 버전: ' + APP_VERSION + '\n배포 가능한 신규 EXE가 확인되지 않았습니다.')


    def start_update(self, release):
        self.button.setEnabled(False)
        dialog = QProgressDialog('Onefile 다운로드 및 검증 중…', '취소', 0, 100, self.window)
        dialog.setWindowTitle('Sunrise 업데이트')
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)
        self._progress_dialog = dialog
        task = UpdateTask(release)
        self._update_task = task
        task.signals.progress.connect(dialog.setValue, Qt.ConnectionType.QueuedConnection)
        task.signals.done.connect(self.update_finished, Qt.ConnectionType.QueuedConnection)
        dialog.canceled.connect(task.cancel.set)
        QThreadPool.globalInstance().start(task)
        dialog.show()

    @Slot(object, object)
    def update_finished(self, prepared, error):
        from .onefile_update import launch_update
        task, self._update_task = self._update_task, None
        dialog, self._progress_dialog = self._progress_dialog, None
        if dialog:
            dialog.close()
            dialog.deleteLater()
        self.button.setEnabled(True)
        if error:
            if self.window.isVisible() and not self.window._closing:
                QMessageBox.warning(self.window, '업데이트 중단', error + '\n기존 EXE는 변경되지 않았습니다.')
            return
        if not task or task.cancel.is_set() or self.window._closing or not self.window.isVisible() or self.window._export_busy:
            return
        try:
            launch_update(prepared)
        except Exception as exc:
            QMessageBox.warning(self.window, '업데이트 중단', str(exc) + '\n기존 EXE는 변경되지 않았습니다.')
            return
        self.window.close()
