"""Non-blocking notice checking and user-approved onefile release handoff.

This first implementation deliberately does not run or replace a downloaded EXE.
"""
from __future__ import annotations
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QPushButton
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


class ReleaseFeedController(QObject):
    def __init__(self, window, *, auto_check=False):
        super().__init__(window)
        self.window = window
        self.busy = False
        self.manual = False
        self._task = None
        self.button = QPushButton('공지 · 업데이트', window)
        self.button.setObjectName('releaseFeedButton')
        self.button.setToolTip('현재 버전 ' + APP_VERSION + ' · 공식 공지 및 업데이트 확인')
        window.statusBar().addPermanentWidget(self.button)
        self.button.clicked.connect(lambda: self.check(True))
        if auto_check:
            QTimer.singleShot(150, self.check)

    @Slot()
    def check(self, manual=False):
        if self.busy or self.window._closing:
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
            update = box.addButton('업데이트 페이지 열기', QMessageBox.ButtonRole.AcceptRole)
            box.addButton('종료', QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() == update:
                if not QDesktopServices.openUrl(QUrl(release.page)):
                    QMessageBox.warning(self.window, '업데이트 페이지 오류', '공식 배포 페이지를 열지 못했습니다. 다시 시도하세요.')
                    return
            self.window.close()
        elif self.manual:
            if errors:
                QMessageBox.warning(self.window, '확인 실패', '일부 공식 정보를 확인하지 못했습니다.\n' + '\n'.join(errors))
            else:
                QMessageBox.information(self.window, '업데이트 확인', '현재 버전: ' + APP_VERSION + '\n배포 가능한 신규 EXE가 확인되지 않았습니다.')
