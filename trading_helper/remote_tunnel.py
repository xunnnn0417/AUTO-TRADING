"""Explicitly started temporary HTTPS access using an existing cloudflared."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal


def cloudflared_path() -> str:
    # No downloads, shell commands, service installation or firewall changes.
    for root in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles')):
        if root and (path := Path(root) / 'cloudflared' / 'cloudflared.exe').is_file():
            return str(path)
    return shutil.which('cloudflared') or ''


class QuickTunnel(QObject):
    ready = Signal(str)
    failed = Signal(str)
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.errorOccurred.connect(self._error)
        self.process.finished.connect(self._finished)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.setInterval(60_000)
        self.timeout.timeout.connect(lambda: self._fail('手機連線逾時，請確認網路後重新開啟。'))
        self.url = ''
        self.message = '尚未開啟手機外網連線'
        self.connected = False
        self._buffer = ''
        self._folder = None
        self._stopping = False
        self._failed = False

    @property
    def running(self):
        return self.process.state() != QProcess.NotRunning

    def start(self, local_origin: str):
        if self.running:
            raise ValueError('手機連線正在執行，請先停止。')
        if not re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]{0,4}', local_origin):
            raise ValueError('手機連線只能連到本程式的本機入口。')
        executable = cloudflared_path()
        if not executable:
            raise ValueError('尚未安裝 Cloudflare 連線工具，請先在電腦安裝 cloudflared。')
        self._stopping = self._failed = False
        self.connected = False
        self.url = self._buffer = ''
        self.message = '正在建立手機網址…'
        self._folder = tempfile.TemporaryDirectory(prefix='helper-mobile-')
        config = Path(self._folder.name) / 'quick-tunnel.yaml'
        config.write_text('{}\n', encoding='utf-8')
        environment = QProcessEnvironment.systemEnvironment()
        for key in environment.keys():
            if key.startswith(('TUNNEL_', 'CLOUDFLARED_')):
                environment.remove(key)
        self.process.setProcessEnvironment(environment)
        self.process.setProgram(executable)
        self.process.setArguments([
            'tunnel', '--config', str(config), '--no-autoupdate',
            '--metrics', '127.0.0.1:0', '--protocol', 'http2',
            '--edge-ip-version', '4', '--url', local_origin,
        ])
        self.timeout.start()
        self.process.start()
        self.changed.emit()

    def _read(self):
        self._consume(bytes(self.process.readAllStandardOutput()).decode('utf-8', 'replace'))

    def _consume(self, text):
        if self._stopping or self._failed:
            return
        self._buffer += text
        lines = self._buffer.split('\n')
        self._buffer = lines.pop()[-4096:]
        for line in lines:
            match = re.search(r'https://([a-z0-9]+(?:-[a-z0-9]+)*)\.trycloudflare\.com(?=[\s|/]|$)', line)
            if match:
                self.url = match.group(0)
            if 'Registered tunnel connection' in line and self.url and not self.connected:
                self.connected = True
                self.timeout.stop()
                self.message = '手機外網連線已建立（臨時網址）'
                self.ready.emit(self.url)
                self.changed.emit()
            elif 'Unregistered tunnel connection' in line and self.connected:
                self._fail('手機外網連線已中斷，請重新開啟；不會重送操作。')

    def _error(self, _error):
        if not self._stopping:
            self._fail('無法啟動手機連線工具，請確認工具與網路。')

    def _finished(self, *_):
        if not self._stopping and not self._failed:
            self._fail('手機外網連線已結束；不會重送操作。')

    def _fail(self, message):
        if self._failed or self._stopping:
            return
        self._failed = True
        self.stop()
        self.message = message
        self.failed.emit(message)
        self.changed.emit()

    def stop(self):
        self._stopping = True
        self.timeout.stop()
        self.connected = False
        self.url = ''
        if self.running:
            # Only our own child process; never touch another tunnel or broker.
            self.process.kill()
            self.process.waitForFinished(1500)
        if self._folder is not None:
            self._folder.cleanup()
            self._folder = None
        self.message = '手機外網連線已停止'
        self.changed.emit()
