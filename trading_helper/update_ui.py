"""Application-owned update dialogs; no trading actions are performed here."""
from pathlib import Path
import os
import sys

from PySide6.QtCore import QObject, QThread, QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from . import __version__
from .self_update import prepare_update, start_worker
from .ui_theme import DIALOG_THEME
from .update_check import check_for_update, DOWNLOAD_PAGE_URL
from .window_chrome import ThemedDialog


class UpdateJob(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, job, parent):
        super().__init__(parent)
        self.job = job

    def run(self):
        try:
            self.completed.emit(self.job())
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdateDialog(ThemedDialog):
    def __init__(self, notice, parent):
        super().__init__(parent)
        self.busy = False
        self.setWindowTitle("有新版本")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 12)
        self.message = QLabel(
            f"新版 {notice.latest_version} 已推出（目前 {notice.current_version}）。\n"
            "更新後會重新開啟程式，保留方案、校準和交易紀錄。", self)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.later = QPushButton("稍後", self)
        self.later.clicked.connect(self.reject)
        self.install = QPushButton("更新並重新開啟", self)
        self.github = QPushButton("下載完整包", self)
        self.github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DOWNLOAD_PAGE_URL)))
        self.github.hide()
        buttons.addWidget(self.github)
        buttons.addWidget(self.later)
        buttons.addWidget(self.install)
        layout.addLayout(buttons)
        self.setStyleSheet(DIALOG_THEME)
        self.install_chrome()

    def set_busy(self, busy):
        self.busy = busy
        self.progress.setVisible(busy)
        self.install.setEnabled(not busy)
        self.later.setEnabled(not busy)
        self.chrome_close.setEnabled(not busy)
        if busy:
            self.message.setText("正在下載並核對更新，完成後會重新開啟。")

    def reject(self):
        if not self.busy:
            super().reject()


class UpdateController(QObject):
    def __init__(self, window, root):
        super().__init__(window)
        self.window = window
        self.root = Path(root)
        self.notice = None
        self.dialog = None
        self.job = None
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.offer_when_idle)

    def start(self):
        self.job = UpdateJob(lambda: check_for_update(__version__), self)
        self.job.completed.connect(self.found)
        self.job.start()

    def found(self, notice):
        if notice is not None:
            self.notice = notice
            self.timer.start()
            self.offer_when_idle()

    def offer_when_idle(self):
        if (not self.window.isVisible() or QApplication.activeModalWidget() is not None
                or not self.window.can_update()):
            return
        self.timer.stop()
        self.dialog = UpdateDialog(self.notice, self.window)
        self.dialog.install.clicked.connect(self.download)
        self.dialog.open()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def download(self):
        if not self.window.begin_update():
            self.dialog.message.setText("目前有操作正在進行，請完成後再更新。")
            return
        self.dialog.set_busy(True)
        self.job = UpdateJob(lambda: prepare_update(self.root, __version__), self)
        self.job.completed.connect(self.ready)
        self.job.failed.connect(self.failed)
        self.job.start()

    def failed(self, error):
        self.window.end_update()
        self.dialog.set_busy(False)
        self.dialog.message.setText(f"更新未完成，原版本已保留。\n{error}")
        self.dialog.install.setText("重試更新")
        self.dialog.github.show()

    def ready(self, stage):
        try:
            self.window.save_ui_state()
            start_worker(stage, sys.executable, os.getpid())
        except Exception as exc:
            self.failed(str(exc))
            return
        self.window._allow_update_exit = True
        self.dialog.set_busy(False)
        self.dialog.accept()
        self.window.close()
        QApplication.instance().quit()
